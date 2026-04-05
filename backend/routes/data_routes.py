import os

from flask import Blueprint, session, request

from config import (
    ALLOWED_MIME,
    DELETE_CAPTURE_AFTER_PROCESS,
)
from ocr_functions.process_image import main as process_image_main
from services.storage_service import (
    build_capture_checksum,
    build_capture_object_key,
    build_capture_signature,
    build_capture_user_scope,
    create_capture_manifest_record,
    delete_capture_from_bucket,
    download_capture_from_bucket,
    find_latest_capture_object_key,
    get_capture_manifest_record_by_object_key,
    get_latest_capture_manifest_record,
    get_latest_capture_manifest_record_any,
    list_capture_objects_for_scope,
    mark_capture_manifest_status,
    upload_capture_to_bucket,
    verify_uploaded_capture,
    verify_capture_signature,
    with_temp_file_from_bytes,
)
from services.discogs_service import (
    get_discogs_client,
    get_discogs_collection_folders,
    get_discogs_identity,
    iter_discogs_paginated_items,
)

data_bp = Blueprint("data", __name__)


def _read_verified_capture_bytes(record):
    """Verify the signed manifest before reading bytes so routes share one trust path."""
    is_valid_signature = verify_capture_signature(
        user_scope=record.get("user_scope"),
        object_key=record.get("object_key"),
        checksum=record.get("checksum_sha256"),
        signature=record.get("signature"),
    )
    if not is_valid_signature:
        raise PermissionError("Capture ownership signature is invalid")

    file_bytes = download_capture_from_bucket(record.get("object_key"))
    suffix = os.path.splitext(record.get("object_key"))[1] or ".jpg"
    return file_bytes, suffix


@data_bp.route("/data/capture-debug", methods=["GET"])
def capture_debug():
    """Debug endpoint for capture lookup path (scope, manifest, bucket visibility)."""
    access_token = session.get("access_token")
    if not access_token:
        return {"error": "User not authenticated"}, 401

    user_scope = build_capture_user_scope(access_token)
    latest_uploaded = get_latest_capture_manifest_record(
        user_scope, statuses=["uploaded"]
    )
    latest_processed = get_latest_capture_manifest_record(
        user_scope, statuses=["processed"]
    )
    latest_any_scope = get_latest_capture_manifest_record_any(
        statuses=["uploaded", "processed"]
    )
    scope_objects = list_capture_objects_for_scope(user_scope)

    return {
        "user_scope": user_scope,
        "latest_uploaded": latest_uploaded,
        "latest_processed": latest_processed,
        "latest_any_scope": latest_any_scope,
        "scope_object_count": len(scope_objects),
        "scope_objects": scope_objects[:5],
    }


@data_bp.route("/data/upload", methods=["POST"])
def upload_image():
    """Upload an image to Supabase Storage and persist signed capture metadata."""
    try:
        access_token = session.get("access_token")
        if not access_token:
            raise ValueError("User not authenticated")
    except ValueError:
        return {"error": "User not authenticated"}, 401

    if "file" not in request.files:
        return {"error": "No file field in request"}, 400

    file = request.files["file"]

    if file.mimetype not in ALLOWED_MIME:
        return {"error": "Unsupported file type"}, 415

    suffix = ".jpg" if file.mimetype == "image/jpeg" else ".png"
    file_bytes = file.read()
    if not file_bytes:
        return {"error": "Uploaded file is empty"}, 400

    user_scope = build_capture_user_scope(access_token)
    object_key = build_capture_object_key(user_scope, file_bytes, suffix)
    checksum = build_capture_checksum(file_bytes)
    signature = build_capture_signature(user_scope, object_key, checksum)

    try:
        upload_capture_to_bucket(object_key, file_bytes, file.mimetype)
        verify_uploaded_capture(object_key, checksum)

        create_capture_manifest_record(
            user_scope=user_scope,
            object_key=object_key,
            content_type=file.mimetype,
            checksum=checksum,
            signature=signature,
        )
    except Exception as e:
        try:
            delete_capture_from_bucket(object_key)
        except Exception:
            pass
        return {"error": str(e)}, 500

    return {"path": object_key, "storage": "supabase"}


@data_bp.route("/data/scan", methods=["POST"])
def scan_image():
    body = request.get_json(silent=True)
    if not body or "path" not in body:
        return {"error": "Missing 'path' in request body"}, 400

    path = body["path"]

    if os.path.isfile(path):
        try:
            albums = process_image_main(path)
            return {"albums": albums}
        except Exception as e:
            return {"error": str(e)}, 500

    access_token = session.get("access_token")
    if not access_token:
        return {"error": "User not authenticated"}, 401

    user_scope = build_capture_user_scope(access_token)
    record = get_capture_manifest_record_by_object_key(user_scope, path)
    if not record:
        return {"error": "Capture not found for this user"}, 404

    try:
        file_bytes, suffix = _read_verified_capture_bytes(record)
    except PermissionError as error:
        return {"error": str(error)}, 403
    except Exception:
        return {"error": "File not found"}, 404

    try:
        albums = with_temp_file_from_bytes(file_bytes, suffix, process_image_main)
        return {"albums": albums}
    except Exception as e:
        return {"error": str(e)}, 500


@data_bp.route("/process/latest", methods=["GET"])
def process_latest_image():
    """Process the most recently uploaded capture for the authenticated user."""
    try:
        access_token = session.get("access_token")
        if not access_token:
            raise ValueError("User not authenticated")
    except ValueError:
        return {"error": "User not authenticated"}, 401

    user_scope = build_capture_user_scope(access_token)
    latest_capture = get_latest_capture_manifest_record(
        user_scope, statuses=["uploaded"]
    )
    if not latest_capture:
        latest_capture = get_latest_capture_manifest_record(
            user_scope, statuses=["processed"]
        )

    if not latest_capture:
        fallback_object_key = find_latest_capture_object_key(user_scope)
        if not fallback_object_key:
            scope_objects = list_capture_objects_for_scope(user_scope)
            latest_any_scope = get_latest_capture_manifest_record_any(
                statuses=["uploaded", "processed"]
            )
            return {
                "error": "No images found",
                "debug": {
                    "user_scope": user_scope,
                    "scope_object_count": len(scope_objects),
                    "latest_any_scope": latest_any_scope,
                },
            }, 404

        try:
            fallback_bytes = download_capture_from_bucket(fallback_object_key)
        except Exception:
            return {"error": "No images found"}, 404

        fallback_checksum = build_capture_checksum(fallback_bytes)
        fallback_signature = build_capture_signature(
            user_scope,
            fallback_object_key,
            fallback_checksum,
        )

        try:
            create_capture_manifest_record(
                user_scope=user_scope,
                object_key=fallback_object_key,
                content_type="image/jpeg",
                checksum=fallback_checksum,
                signature=fallback_signature,
            )
        except Exception:
            pass

        latest_capture = {
            "id": None,
            "user_scope": user_scope,
            "object_key": fallback_object_key,
            "checksum_sha256": fallback_checksum,
            "signature": fallback_signature,
            "status": "uploaded",
        }

    latest_image_key = latest_capture.get("object_key")
    try:
        file_bytes, suffix = _read_verified_capture_bytes(latest_capture)
    except PermissionError as error:
        return {"error": str(error)}, 403
    except Exception:
        return {"error": "Image file not found or has expired"}, 404

    try:
        result = with_temp_file_from_bytes(file_bytes, suffix, process_image_main)

        if DELETE_CAPTURE_AFTER_PROCESS:
            try:
                delete_capture_from_bucket(latest_image_key)
                if latest_capture.get("id") is not None:
                    mark_capture_manifest_status(latest_capture.get("id"), "deleted")
            except Exception as cleanup_error:
                print(
                    f"Failed to delete processed capture from bucket: {cleanup_error}"
                )
        else:
            if latest_capture.get("id") is not None:
                mark_capture_manifest_status(latest_capture.get("id"), "processed")

        return {
            "success": True,
            "image_path": latest_image_key,
            "storage": "supabase",
            "result": result,
        }
    except Exception as e:
        return {"error": str(e)}, 500


@data_bp.route("/data/albums", methods=["GET"])
def get_albums():
    try:
        d = get_discogs_client()
        user = get_discogs_identity(d)
    except ValueError:
        return {"error": "User not authenticated"}, 401

    albums = []
    collection_folders = get_discogs_collection_folders(user)
    if not collection_folders:
        return albums

    for album in iter_discogs_paginated_items(
        collection_folders[0].releases, authenticated=True
    ):
        albums.append(
            {"name": album.release.artists[0].name, "title": album.release.title}
        )

    return albums
