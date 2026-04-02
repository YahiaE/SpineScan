import hashlib
import hmac
import os
import tempfile
import time

from config import CAPTURE_SIGNATURE_SECRET, SUPABASE_UPLOAD_BUCKET
from extensions import supabase


def build_capture_user_scope(access_token):
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()[:24]


def build_capture_object_key(user_scope, file_bytes, suffix):
    fingerprint = hashlib.sha256(file_bytes).hexdigest()[:12]
    timestamp_ms = int(time.time() * 1000)
    return f"{user_scope}/{timestamp_ms}-{fingerprint}{suffix}"


def build_capture_checksum(file_bytes):
    return hashlib.sha256(file_bytes).hexdigest()


def build_capture_signature(user_scope, object_key, checksum):
    payload = f"{user_scope}:{object_key}:{checksum}".encode("utf-8")
    secret = (CAPTURE_SIGNATURE_SECRET or "").encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def verify_capture_signature(user_scope, object_key, checksum, signature):
    expected = build_capture_signature(user_scope, object_key, checksum)
    return hmac.compare_digest(expected, str(signature or ""))


def upload_capture_to_bucket(object_key, file_bytes, content_type):
    return supabase.storage.from_(SUPABASE_UPLOAD_BUCKET).upload(
        path=object_key,
        file=file_bytes,
        file_options={
            "content-type": content_type,
            "upsert": False,
        },
    )


def download_capture_from_bucket(object_key):
    return supabase.storage.from_(SUPABASE_UPLOAD_BUCKET).download(object_key)


def delete_capture_from_bucket(object_key):
    return supabase.storage.from_(SUPABASE_UPLOAD_BUCKET).remove([object_key])


def create_capture_manifest_record(
    user_scope,
    object_key,
    content_type,
    checksum,
    signature,
):
    return (
        supabase.table("captures")
        .insert(
            {
                "user_scope": user_scope,
                "object_key": object_key,
                "content_type": content_type,
                "checksum_sha256": checksum,
                "signature": signature,
                "status": "uploaded",
            }
        )
        .execute()
    )


def get_latest_capture_manifest_record(user_scope, statuses=None):
    query = (
        supabase.table("captures")
        .select(
            "id, user_scope, object_key, content_type, checksum_sha256, signature, status"
        )
        .eq("user_scope", user_scope)
        .order("created_at", desc=True)
        .limit(1)
    )

    if statuses:
        if len(statuses) == 1:
            query = query.eq("status", statuses[0])
        else:
            query = query.in_("status", statuses)

    response = query.execute()
    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None


def get_capture_manifest_record_by_object_key(user_scope, object_key):
    response = (
        supabase.table("captures")
        .select(
            "id, user_scope, object_key, content_type, checksum_sha256, signature, status"
        )
        .eq("user_scope", user_scope)
        .eq("object_key", object_key)
        .in_("status", ["uploaded", "processed"])
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None


def mark_capture_manifest_status(capture_id, status):
    return (
        supabase.table("captures")
        .update(
            {
                "status": status,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        .eq("id", capture_id)
        .execute()
    )


def find_latest_capture_object_key(user_scope):
    """Best-effort fallback to find latest capture object in a user scope folder."""
    try:
        objects = supabase.storage.from_(SUPABASE_UPLOAD_BUCKET).list(user_scope)
    except Exception:
        return None

    if not objects:
        return None

    object_names = []
    for item in objects:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name:
            object_names.append(name)

    if not object_names:
        return None

    latest_name = max(object_names)
    return f"{user_scope}/{latest_name}"


def list_capture_objects_for_scope(user_scope):
    """Return object keys in the user's bucket scope, newest name first."""
    try:
        objects = supabase.storage.from_(SUPABASE_UPLOAD_BUCKET).list(user_scope)
    except Exception:
        return []

    names = []
    for item in objects or []:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name:
            names.append(name)

    names.sort(reverse=True)
    return [f"{user_scope}/{name}" for name in names]


def get_latest_capture_manifest_record_any(statuses=None):
    """Best-effort latest capture row across scopes (debug/ops visibility)."""
    query = (
        supabase.table("captures")
        .select(
            "id, user_scope, object_key, content_type, checksum_sha256, signature, status, created_at"
        )
        .order("created_at", desc=True)
        .limit(1)
    )

    if statuses:
        if len(statuses) == 1:
            query = query.eq("status", statuses[0])
        else:
            query = query.in_("status", statuses)

    response = query.execute()
    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None


def verify_uploaded_capture(object_key, expected_checksum):
    """Confirm uploaded object can be downloaded and checksum matches."""
    uploaded_bytes = download_capture_from_bucket(object_key)
    actual_checksum = build_capture_checksum(uploaded_bytes)
    if actual_checksum != expected_checksum:
        raise RuntimeError("Uploaded capture checksum mismatch")
    return True


def with_temp_file_from_bytes(file_bytes, suffix, callback):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(file_bytes)
        tmp.flush()
        tmp.close()
        return callback(tmp.name)
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
