import json
import time

from discogs_client.exceptions import HTTPError
from flask import Blueprint, jsonify, request, session

from config import IMPORT_IDEMPOTENCY_TTL_SECONDS
from extensions import redis_conn
from services.discogs_service import (
    add_release_to_folder,
    album_identity_key,
    build_import_request_fingerprint,
    cache_collection_membership_entry,
    ensure_collection_membership_cache_warm,
    get_collection_folder,
    get_discogs_client,
    get_discogs_collection_folders,
    get_discogs_identity,
    get_lookup_queue_stats,
    is_album_in_collection_cache,
    is_discogs_duplicate_error,
    is_release_in_collection_cache,
    mirror_collection_cache_entry_to_albums,
    resolve_release_match,
)
from services.import_history_service import (
    create_import_history_entry,
    list_import_history,
)

discogs_bp = Blueprint("discogs", __name__, url_prefix="/discogs")


@discogs_bp.route("/import-history", methods=["GET"])
def get_import_history():
    try:
        d = get_discogs_client()
        user = get_discogs_identity(d)
    except ValueError:
        return jsonify({"error": "User not authenticated"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    try:
        history_rows = list_import_history(user.username)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"imports": history_rows})


@discogs_bp.route("/collection-folders", methods=["GET"])
def get_collection_folders():
    try:
        d = get_discogs_client()
        user = get_discogs_identity(d)
        collection_folders = get_discogs_collection_folders(user)
    except ValueError:
        return jsonify({"error": "User not authenticated"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    folders = []
    for folder in collection_folders:
        folders.append(
            {
                "id": folder.id,
                "name": folder.name,
                "count": folder.count,
            }
        )

    return jsonify({"folders": folders})


@discogs_bp.route("/worker-status", methods=["GET"])
def discogs_worker_status():
    """Expose worker and queue status to debug validation pipeline health."""
    try:
        stats = get_lookup_queue_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@discogs_bp.route("/validate", methods=["POST"])
def validate_entries():
    body = request.get_json(silent=True)
    entries = body.get("entries") if body else None

    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "Missing 'entries' in request body"}), 400

    try:
        get_discogs_client()
    except ValueError:
        return jsonify({"error": "User not authenticated"}), 401

    validations = []

    for entry in entries:
        entry_id = entry.get("id")
        artist = str(entry.get("artist", "")).strip()
        title = str(entry.get("title", "")).strip()

        if not artist or not title:
            validations.append(
                {
                    "id": entry_id,
                    "status": "invalid",
                    "message": "Artist and title are required",
                }
            )
            continue

        match = resolve_release_match(artist, title, enqueue_if_missing=True)
        validations.append({"id": entry_id, **match})

    return jsonify({"validations": validations})


@discogs_bp.route("/import", methods=["POST"])
def import_entries():
    body = request.get_json(silent=True)
    folder_id = body.get("folder_id") if body else None
    entries = body.get("entries") if body else None

    if folder_id is None:
        return jsonify({"error": "Missing 'folder_id' in request body"}), 400

    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "Missing 'entries' in request body"}), 400

    try:
        folder_id = int(folder_id)
    except (TypeError, ValueError):
        return jsonify({"error": "'folder_id' must be an integer"}), 400

    import_fingerprint = build_import_request_fingerprint(folder_id, entries)
    user_scope = session.get("access_token", "anonymous")
    import_key_suffix = f"{user_scope}:{folder_id}:{import_fingerprint}"
    import_result_key = f"discogs:import:result:{import_key_suffix}"
    import_lock_key = f"discogs:import:lock:{import_key_suffix}"

    cached_import_result = redis_conn.get(import_result_key)
    if cached_import_result:
        try:
            return jsonify(json.loads(cached_import_result))
        except json.JSONDecodeError:
            redis_conn.delete(import_result_key)

    lock_acquired = redis_conn.set(
        import_lock_key,
        "1",
        nx=True,
        ex=IMPORT_IDEMPOTENCY_TTL_SECONDS,
    )

    if not lock_acquired:
        deadline = time.time() + 4.0
        while time.time() < deadline:
            cached_import_result = redis_conn.get(import_result_key)
            if cached_import_result:
                try:
                    return jsonify(json.loads(cached_import_result))
                except json.JSONDecodeError:
                    redis_conn.delete(import_result_key)
                    break
            time.sleep(0.1)

        return jsonify({"error": "An identical import is already in progress"}), 409

    try:
        try:
            d = get_discogs_client()
            user = get_discogs_identity(d)
            collection_folders = get_discogs_collection_folders(user)
        except ValueError:
            return jsonify({"error": "User not authenticated"}), 401
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        target_folder = get_collection_folder(collection_folders, folder_id)
        if target_folder is None:
            return jsonify(
                {"error": "Selected collection folder is not available"}
            ), 404

        try:
            ensure_collection_membership_cache_warm(
                d,
                user.username,
                target_folder,
            )
        except Exception as warm_error:
            # Non-fatal: fallback duplicate detection still runs via API response.
            print(f"Collection cache warm-up failed: {warm_error}")

        pending_release_ids = set()
        pending_album_keys = set()
        results = []

        for entry in entries:
            entry_id = entry.get("id")
            artist = str(entry.get("artist", "")).strip()
            title = str(entry.get("title", "")).strip()
            release_id = entry.get("release_id")
            entry_album_key = album_identity_key(artist, title)

            if not release_id:
                match = resolve_release_match(artist, title, enqueue_if_missing=False)
                if match["status"] != "valid":
                    results.append(
                        {
                            "id": entry_id,
                            "status": "rejected",
                            "artist": artist,
                            "title": title,
                            "message": match["message"],
                        }
                    )
                    continue
                release_id = match["release_id"]

                matched_album_key = album_identity_key(
                    match.get("matched_artist", artist),
                    match.get("matched_title", title),
                )
                if matched_album_key in pending_album_keys:
                    results.append(
                        {
                            "id": entry_id,
                            "status": "skipped",
                            "artist": artist,
                            "title": title,
                            "release_id": release_id,
                            "message": "A matching album is already in this import batch",
                        }
                    )
                    continue
                entry_album_key = matched_album_key

            try:
                normalized_release_id = int(release_id)
            except (TypeError, ValueError):
                results.append(
                    {
                        "id": entry_id,
                        "status": "failed",
                        "artist": artist,
                        "title": title,
                        "release_id": release_id,
                        "message": "Invalid Discogs release ID",
                    }
                )
                continue

            if normalized_release_id in pending_release_ids:
                results.append(
                    {
                        "id": entry_id,
                        "status": "skipped",
                        "artist": artist,
                        "title": title,
                        "release_id": normalized_release_id,
                        "message": "Release is already in this import batch",
                    }
                )
                continue

            if is_release_in_collection_cache(
                user.username,
                folder_id,
                normalized_release_id,
            ):
                mirror_collection_cache_entry_to_albums(
                    normalized_release_id,
                    entry_album_key,
                )
                results.append(
                    {
                        "id": entry_id,
                        "status": "skipped",
                        "artist": artist,
                        "title": title,
                        "release_id": normalized_release_id,
                        "message": "Release already exists in selected folder (cached)",
                    }
                )
                continue

            if entry_album_key in pending_album_keys:
                results.append(
                    {
                        "id": entry_id,
                        "status": "skipped",
                        "artist": artist,
                        "title": title,
                        "release_id": normalized_release_id,
                        "message": "A matching album is already in this import batch",
                    }
                )
                continue

            if is_album_in_collection_cache(
                user.username,
                folder_id,
                entry_album_key,
            ):
                mirror_collection_cache_entry_to_albums(
                    normalized_release_id,
                    entry_album_key,
                )
                results.append(
                    {
                        "id": entry_id,
                        "status": "skipped",
                        "artist": artist,
                        "title": title,
                        "release_id": normalized_release_id,
                        "message": "A matching album already exists in selected folder (cached)",
                    }
                )
                continue

            try:
                add_release_to_folder(
                    d, user.username, folder_id, normalized_release_id
                )
                pending_release_ids.add(normalized_release_id)
                pending_album_keys.add(entry_album_key)
                cache_collection_membership_entry(
                    user.username,
                    folder_id,
                    normalized_release_id,
                    entry_album_key,
                )
                results.append(
                    {
                        "id": entry_id,
                        "status": "added",
                        "artist": artist,
                        "title": title,
                        "release_id": normalized_release_id,
                    }
                )
            except HTTPError as e:
                if is_discogs_duplicate_error(e):
                    cache_collection_membership_entry(
                        user.username,
                        folder_id,
                        normalized_release_id,
                        entry_album_key,
                    )
                    results.append(
                        {
                            "id": entry_id,
                            "status": "skipped",
                            "artist": artist,
                            "title": title,
                            "release_id": normalized_release_id,
                            "message": "Release already exists in the selected Discogs folder",
                        }
                    )
                    continue

                results.append(
                    {
                        "id": entry_id,
                        "status": "failed",
                        "artist": artist,
                        "title": title,
                        "release_id": release_id,
                        "message": e.msg,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "id": entry_id,
                        "status": "failed",
                        "artist": artist,
                        "title": title,
                        "release_id": release_id,
                        "message": str(e),
                    }
                )

        added_count = sum(1 for result in results if result["status"] == "added")
        skipped_count = sum(1 for result in results if result["status"] == "skipped")
        failed_count = sum(
            1 for result in results if result["status"] in {"failed", "rejected"}
        )

        response_payload = {
            "folder_id": folder_id,
            "results": results,
            "added_count": added_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
        }

        try:
            create_import_history_entry(
                discogs_username=user.username,
                folder_id=folder_id,
                folder_name=getattr(target_folder, "name", None),
                status="completed" if failed_count == 0 else "completed_with_errors",
                added_count=added_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
                results=results,
            )
        except Exception as history_error:
            print(f"Failed to persist import history: {history_error}")

        redis_conn.setex(
            import_result_key,
            IMPORT_IDEMPOTENCY_TTL_SECONDS,
            json.dumps(response_payload),
        )

        return jsonify(response_payload)
    finally:
        redis_conn.delete(import_lock_key)
