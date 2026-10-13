import json
import secrets
import time

from discogs_client.exceptions import HTTPError
from flask import Blueprint, jsonify, request, session

from config import (
    DISCOGS_RATE_WINDOW_SECONDS,
    IMPORT_IDEMPOTENCY_TTL_SECONDS,
    IMPORT_MAX_ENTRIES,
    IMPORT_REQUESTS_PER_WINDOW,
    VALIDATE_MAX_ENTRIES,
    VALIDATE_REQUESTS_PER_WINDOW,
)
from extensions import redis_conn
from services.discogs_service import (
    add_release_to_folder,
    album_identity_key,
    build_import_request_fingerprint,
    ensure_collection_membership_cache_warm,
    get_collection_folder,
    get_discogs_client,
    get_discogs_collection_folders,
    get_discogs_identity,
    get_lookup_statuses,
    get_lookup_queue_stats,
    build_lookup_request_context,
    is_discogs_duplicate_error,
    resolve_release_match,
    sync_collection_membership_cache,
)
from services.import_history_service import (
    create_import_history_entry,
    list_import_history,
)

discogs_bp = Blueprint("discogs", __name__, url_prefix="/discogs")


def _user_rate_limit_key(action):
    user_scope = session.get("access_token", "anonymous")
    bucket_start = int(time.time() // DISCOGS_RATE_WINDOW_SECONDS)
    return f"discogs:user-rate:{action}:{user_scope}:{bucket_start}"


def _consume_user_rate_slot(action, max_requests_per_window):
    """Return True when the user can proceed inside the current rate window.

    Fails open: if Redis is unavailable, the request is allowed through rather
    than returning a 500.
    """
    if max_requests_per_window <= 0:
        return True

    try:
        key = _user_rate_limit_key(action)
        current_count = redis_conn.incr(key)
        if current_count == 1:
            redis_conn.expire(key, DISCOGS_RATE_WINDOW_SECONDS * 2)
        return current_count <= max_requests_per_window
    except Exception:
        return True


def _build_import_idempotency_keys(folder_id, entries):
    import_fingerprint = build_import_request_fingerprint(folder_id, entries)
    user_scope = session.get("access_token", "anonymous")
    key_suffix = f"{user_scope}:{folder_id}:{import_fingerprint}"
    return (
        f"discogs:import:result:{key_suffix}",
        f"discogs:import:lock:{key_suffix}",
    )


def _delete_import_lock_if_owned(lock_key, lock_token):
    redis_conn.eval(
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end",
        1,
        lock_key,
        lock_token,
    )


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

    if len(entries) > VALIDATE_MAX_ENTRIES:
        return (
            jsonify(
                {
                    "error": f"Too many entries. Maximum allowed is {VALIDATE_MAX_ENTRIES}",
                }
            ),
            413,
        )

    if not _consume_user_rate_slot("validate", VALIDATE_REQUESTS_PER_WINDOW):
        return (
            jsonify({"error": "Validation rate limit exceeded. Please retry shortly."}),
            429,
        )

    try:
        get_discogs_client()
    except ValueError:
        return jsonify({"error": "User not authenticated"}), 401

    validations = []
    lookup_context = build_lookup_request_context()

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

        if len(artist) > 200 or len(title) > 200:
            validations.append(
                {
                    "id": entry_id,
                    "status": "invalid",
                    "message": "Artist and title must be 200 characters or fewer",
                }
            )
            continue

        match = resolve_release_match(
            artist,
            title,
            enqueue_if_missing=True,
            lookup_context=lookup_context,
        )

        validations.append({"id": entry_id, **match})

    return jsonify({"validations": validations})


@discogs_bp.route("/validation-status", methods=["POST"])
def validation_status():
    body = request.get_json(silent=True)
    entries = body.get("entries") if body else None

    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "Missing 'entries' in request body"}), 400

    if len(entries) > VALIDATE_MAX_ENTRIES:
        return (
            jsonify(
                {
                    "error": f"Too many entries. Maximum allowed is {VALIDATE_MAX_ENTRIES}",
                }
            ),
            413,
        )

    if not _consume_user_rate_slot(
        "validation-status", VALIDATE_REQUESTS_PER_WINDOW * 4
    ):
        return jsonify({"error": "Validation status rate limit exceeded."}), 429

    try:
        get_discogs_client()
    except ValueError:
        return jsonify({"error": "User not authenticated"}), 401

    valid_entries = []
    immediate_results = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") is None:
            return jsonify({"error": "Each entry must include an 'id'"}), 400

        artist = str(entry.get("artist", "")).strip()
        title = str(entry.get("title", "")).strip()
        if not artist or not title:
            immediate_results.append(
                {
                    "id": entry["id"],
                    "status": "invalid",
                    "message": "Artist and title are required",
                }
            )
        elif len(artist) > 200 or len(title) > 200:
            immediate_results.append(
                {
                    "id": entry["id"],
                    "status": "invalid",
                    "message": "Artist and title must be 200 characters or fewer",
                }
            )
        else:
            valid_entries.append(
                {"id": entry["id"], "artist": artist, "title": title}
            )

    status_payload = get_lookup_statuses(valid_entries) if valid_entries else {
        "validations": [],
        "retry_ids": [],
    }
    status_payload["validations"] = immediate_results + status_payload["validations"]
    return jsonify(status_payload)


@discogs_bp.route("/import-status", methods=["POST"])
def import_status():
    body = request.get_json(silent=True)
    folder_id = body.get("folder_id") if body else None
    entries = body.get("entries") if body else None

    if folder_id is None:
        return jsonify({"error": "Missing 'folder_id' in request body"}), 400
    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "Missing 'entries' in request body"}), 400
    if len(entries) > IMPORT_MAX_ENTRIES:
        return (
            jsonify(
                {
                    "error": f"Too many entries. Maximum allowed is {IMPORT_MAX_ENTRIES}",
                }
            ),
            413,
        )
    try:
        folder_id = int(folder_id)
    except (TypeError, ValueError):
        return jsonify({"error": "'folder_id' must be an integer"}), 400

    if not _consume_user_rate_slot(
        "import-status", max(60, IMPORT_REQUESTS_PER_WINDOW * 30)
    ):
        return jsonify({"error": "Import status rate limit exceeded."}), 429

    try:
        get_discogs_client()
    except ValueError:
        return jsonify({"error": "User not authenticated"}), 401

    result_key, lock_key = _build_import_idempotency_keys(folder_id, entries)
    cached_result, lock_value = redis_conn.mget([result_key, lock_key])
    if cached_result:
        try:
            return jsonify(
                {"status": "completed", "result": json.loads(cached_result)}
            )
        except json.JSONDecodeError:
            redis_conn.delete(result_key)

    if lock_value:
        return jsonify({"status": "in_progress"}), 202

    return jsonify({"status": "not_found"}), 404


@discogs_bp.route("/import", methods=["POST"])
def import_entries():
    body = request.get_json(silent=True)
    folder_id = body.get("folder_id") if body else None
    entries = body.get("entries") if body else None

    if folder_id is None:
        return jsonify({"error": "Missing 'folder_id' in request body"}), 400

    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "Missing 'entries' in request body"}), 400

    if len(entries) > IMPORT_MAX_ENTRIES:
        return (
            jsonify(
                {
                    "error": f"Too many entries. Maximum allowed is {IMPORT_MAX_ENTRIES}",
                }
            ),
            413,
        )

    if not _consume_user_rate_slot("import", IMPORT_REQUESTS_PER_WINDOW):
        return (
            jsonify({"error": "Import rate limit exceeded. Please retry shortly."}),
            429,
        )

    try:
        folder_id = int(folder_id)
    except (TypeError, ValueError):
        return jsonify({"error": "'folder_id' must be an integer"}), 400

    import_result_key, import_lock_key = _build_import_idempotency_keys(
        folder_id, entries
    )

    cached_import_result = redis_conn.get(import_result_key)
    if cached_import_result:
        try:
            return jsonify(json.loads(cached_import_result))
        except json.JSONDecodeError:
            redis_conn.delete(import_result_key)

    lock_token = secrets.token_hex(16)
    lock_acquired = redis_conn.set(
        import_lock_key,
        lock_token,
        nx=True,
        ex=IMPORT_IDEMPOTENCY_TTL_SECONDS,
    )

    if not lock_acquired:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            cached_import_result = redis_conn.get(import_result_key)
            if cached_import_result:
                try:
                    return jsonify(json.loads(cached_import_result))
                except json.JSONDecodeError:
                    redis_conn.delete(import_result_key)
                    break

            if not redis_conn.get(import_lock_key):
                lock_acquired = redis_conn.set(
                    import_lock_key,
                    lock_token,
                    nx=True,
                    ex=IMPORT_IDEMPOTENCY_TTL_SECONDS,
                )
                if lock_acquired:
                    cached_import_result = redis_conn.get(import_result_key)
                    if cached_import_result:
                        _delete_import_lock_if_owned(import_lock_key, lock_token)
                        try:
                            return jsonify(json.loads(cached_import_result))
                        except json.JSONDecodeError:
                            redis_conn.delete(import_result_key)
                    break

            time.sleep(0.1)

        if not lock_acquired:
            return jsonify({"status": "in_progress"}), 202

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

        collection_membership = None
        try:
            collection_membership = ensure_collection_membership_cache_warm(
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
        collection_entries_to_cache = {}
        album_entries_to_mirror = []
        cached_release_ids, cached_album_keys = collection_membership or (set(), set())

        for entry in entries:
            entry_id = entry.get("id")
            artist = str(entry.get("artist", "")).strip()
            title = str(entry.get("title", "")).strip()
            release_id = entry.get("release_id")
            entry_album_key = album_identity_key(artist, title)

            if len(artist) > 200 or len(title) > 200:
                results.append(
                    {
                        "id": entry_id,
                        "status": "rejected",
                        "artist": artist[:200],
                        "title": title[:200],
                        "message": "Artist and title must be 200 characters or fewer",
                    }
                )
                continue

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

            if normalized_release_id in cached_release_ids:
                album_entries_to_mirror.append(
                    (normalized_release_id, entry_album_key)
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

            serialized_entry_album_key = "::".join(entry_album_key)
            if serialized_entry_album_key in cached_album_keys:
                album_entries_to_mirror.append(
                    (normalized_release_id, entry_album_key)
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
                cached_release_ids.add(normalized_release_id)
                cached_album_keys.add(serialized_entry_album_key)
                collection_entries_to_cache[normalized_release_id] = entry_album_key
                album_entries_to_mirror.append(
                    (normalized_release_id, entry_album_key)
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
                    cached_release_ids.add(normalized_release_id)
                    cached_album_keys.add(serialized_entry_album_key)
                    collection_entries_to_cache[normalized_release_id] = entry_album_key
                    album_entries_to_mirror.append(
                        (normalized_release_id, entry_album_key)
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

        sync_collection_membership_cache(
            user.username,
            folder_id,
            collection_entries_to_cache,
            album_entries_to_mirror,
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
        _delete_import_lock_if_owned(import_lock_key, lock_token)
