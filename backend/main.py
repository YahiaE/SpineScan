"""Flask backend for Discogs OAuth and collection enrichment using OCR.

This module provides:
- OAuth callback/token exchange endpoints for mobile deep-link auth flow.
- Helpers to normalize collection keys and deduplicate entries.
- Utilities to merge OCR-detected albums into a user's Discogs collection.

Environment variables used:
- FLASK_SECRET_KEY
- CONSUMER_KEY
- CONSUMER_SECRET
"""

import os
import time
import tempfile
import json
import hashlib
import unicodedata
import redis
from datetime import datetime, timezone
from difflib import SequenceMatcher
import discogs_client
from dotenv import load_dotenv
from discogs_client.exceptions import HTTPError
from flask import Flask, session, request, jsonify
from flask_cors import CORS
from rq import Queue, Worker
from rq.registry import (
    DeferredJobRegistry,
    FailedJobRegistry,
    FinishedJobRegistry,
    StartedJobRegistry,
)
from supabase import create_client, Client
from ocr_functions.reader import main as ocr_main
from ocr_functions.process_image import main as process_image_main

load_dotenv()  # Must run before any project imports that read env vars

app = Flask(__name__)

# Supabase is the durable source of truth for album lookups.
supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_PUBLISHABLE_KEY"),
)

CORS(
    app,
    supports_credentials=True,
    origins=["http://localhost:5173", "http://192.168.1.146:5173"],
)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Redis is used for fast cache reads and short-lived workflow state.
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
lookup_queue = Queue(os.getenv("DISCOGS_LOOKUP_QUEUE", "discogs-lookups"), connection=r)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY"
)  # Set a secret key for the Flask session, used for signing cookies and protecting session data.

# Configure standard session settings for CORS
app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=86400,  # 24 hours
)

DISCOGS_RATE_WINDOW_SECONDS = 60
DISCOGS_AUTH_REQUEST_LIMIT = int(os.getenv("DISCOGS_AUTH_RPM", "50"))
DISCOGS_UNAUTH_REQUEST_LIMIT = int(os.getenv("DISCOGS_UNAUTH_RPM", "20"))
DISCOGS_MAX_RETRIES = int(os.getenv("DISCOGS_MAX_RETRIES", "3"))
ALBUM_LOOKUP_CACHE_TTL_SECONDS = int(
    os.getenv("ALBUM_LOOKUP_CACHE_TTL_SECONDS", str(60 * 60 * 24 * 14))
)
ALBUM_LOOKUP_INVALID_CACHE_TTL_SECONDS = int(
    os.getenv("ALBUM_LOOKUP_INVALID_CACHE_TTL_SECONDS", str(60 * 60 * 6))
)
ALBUM_LOOKUP_PENDING_TTL_SECONDS = int(
    os.getenv("ALBUM_LOOKUP_PENDING_TTL_SECONDS", "300")
)
DISCOGS_LOOKUP_JOB_TIMEOUT_SECONDS = int(
    os.getenv("DISCOGS_LOOKUP_JOB_TIMEOUT_SECONDS", "180")
)
IMPORT_IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IMPORT_IDEMPOTENCY_TTL_SECONDS", "180"))
ALBUM_LOOKUP_CACHE_VERSION = os.getenv("ALBUM_LOOKUP_CACHE_VERSION", "v2")
# RQ workers must import jobs by module path, not from a running __main__ script.
DISCOGS_LOOKUP_JOB_FUNC = "main.run_album_lookup_job"


# Mark session as permanent
@app.before_request
def before_request():
    session.permanent = True


def get_user_data_dir():
    """Get or create a user-specific data directory based on session access_token.

    Returns:
        str: Path to user's data directory

    Raises:
        ValueError: If user is not authenticated
    """
    access_token = session.get("access_token")
    if not access_token:
        raise ValueError("User not authenticated")

    base_data_dir = os.path.join(os.path.dirname(__file__), "data")
    user_data_dir = os.path.join(base_data_dir, access_token)

    os.makedirs(user_data_dir, exist_ok=True)
    return user_data_dir


def get_discogs_client():
    """Create an authenticated Discogs client from the current session."""
    access_token = session.get("access_token")
    access_token_secret = session.get("access_token_secret")

    if not access_token or not access_token_secret:
        raise ValueError("User not authenticated")

    client = create_discogs_oauth_client()
    client.set_token(access_token, access_token_secret)
    return client


def get_public_discogs_client():
    """Create a Discogs client for shared public metadata lookups."""
    return create_discogs_oauth_client()


def get_discogs_consumer_credentials():
    """Load Discogs app credentials from env and fail fast if missing."""
    consumer_key = os.getenv("CONSUMER_KEY")
    consumer_secret = os.getenv("CONSUMER_SECRET")

    if not consumer_key or not consumer_secret:
        raise RuntimeError(
            "Discogs consumer credentials are not configured. "
            "Set CONSUMER_KEY and CONSUMER_SECRET in backend env."
        )

    return consumer_key, consumer_secret


def create_discogs_oauth_client():
    """Create a Discogs client backed by OAuth fetcher methods."""
    consumer_key, consumer_secret = get_discogs_consumer_credentials()

    return discogs_client.Client(
        "my_user_agent/1.0",
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
    )


def get_discogs_rate_bucket_key(authenticated):
    # Bucket per minute so all app instances share a common rate window.
    bucket_start = int(time.time() // DISCOGS_RATE_WINDOW_SECONDS)
    bucket_name = "auth" if authenticated else "unauth"
    return f"discogs:rate:{bucket_name}:{bucket_start}"


def acquire_discogs_rate_limit_slot(authenticated=True):
    """Block until a shared Discogs rate-limit slot is available."""
    limit = (
        DISCOGS_AUTH_REQUEST_LIMIT if authenticated else DISCOGS_UNAUTH_REQUEST_LIMIT
    )

    while True:
        # INCR gives us an atomic counter for this time bucket.
        bucket_key = get_discogs_rate_bucket_key(authenticated)
        current_count = r.incr(bucket_key)
        if current_count == 1:
            r.expire(bucket_key, DISCOGS_RATE_WINDOW_SECONDS * 2)

        if current_count <= limit:
            return

        # If over limit, roll back this reservation and wait for the next slot.
        r.decr(bucket_key)
        wait_seconds = max(
            0.25,
            DISCOGS_RATE_WINDOW_SECONDS
            - (time.time() % DISCOGS_RATE_WINDOW_SECONDS)
            + 0.05,
        )
        time.sleep(min(wait_seconds, 5.0))


def call_discogs(api_call, authenticated=True):
    """Run a Discogs API call under a shared rate limiter with basic 429 retry."""
    last_error = None

    for attempt in range(DISCOGS_MAX_RETRIES):
        acquire_discogs_rate_limit_slot(authenticated=authenticated)

        try:
            return api_call()
        except HTTPError as error:
            last_error = error
            if getattr(error, "status_code", None) != 429:
                raise

            if attempt == DISCOGS_MAX_RETRIES - 1:
                raise

            # Exponential backoff on Discogs rate-limit responses.
            time.sleep(min(2**attempt, 8))

    if last_error is not None:
        raise last_error


def iter_discogs_paginated_items(paginated, authenticated=True):
    """Iterate a Discogs paginated list while rate-limiting each page fetch."""
    total_pages = call_discogs(lambda: paginated.pages, authenticated=authenticated)

    for page_index in range(1, total_pages + 1):
        page_items = call_discogs(
            lambda page_index=page_index: paginated.page(page_index),
            authenticated=authenticated,
        )
        for item in page_items:
            yield item


def get_discogs_identity(client):
    return call_discogs(client.identity, authenticated=True)


def get_discogs_collection_folders(user):
    return call_discogs(lambda: user.collection_folders, authenticated=True)


def normalize_text(value):
    """Normalize strings for tolerant artist/title comparisons."""
    text = str(value or "")
    # Fold accents (Beyonce/Beyoncé) and unify common smart punctuation.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = (
        text.replace("’", "'")
        .replace("`", "'")
        .replace("‘", "'")
        .replace("–", "-")
        .replace("—", "-")
    )

    normalized = "".join(ch.lower() for ch in text if ch.isalnum() or ch.isspace())
    return " ".join(normalized.split()).strip()


def strip_version_suffix(value):
    """Remove common version suffixes that should not invalidate a match."""
    text = str(value or "")
    for marker in ["(", "[", " - deluxe", " - remaster", " - expanded"]:
        index = text.lower().find(marker)
        if index > 0:
            text = text[:index]
            break
    return normalize_text(text)


def primary_artist_name(value):
    """Take the first artist from compound artist strings for looser matching."""
    text = str(value or "")
    lowered = text.lower()
    for separator in [" feat. ", " featuring ", " ft. ", " & ", ",", "/", ";"]:
        index = lowered.find(separator)
        if index >= 0:
            return text[:index].strip()
    return text.strip()


def text_similarity(left, right):
    return SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio()


def token_overlap(left, right):
    left_tokens = set(normalize_text(left).split())
    right_tokens = set(normalize_text(right).split())

    if not left_tokens or not right_tokens:
        return 0.0

    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def parse_release_result(result):
    """Extract comparable artist/title fields from a Discogs search result."""
    raw_title = getattr(result, "title", "") or ""
    raw_artist = ""

    artists = getattr(result, "artists", None)
    if artists:
        raw_artist = ", ".join(
            getattr(artist, "name", str(artist)) for artist in artists if artist
        )

    if not raw_artist and " - " in raw_title:
        raw_artist, raw_title = raw_title.split(" - ", 1)

    # Discogs search titles can include "Artist - Title" even when `artists`
    # is also populated. Remove duplicated artist prefix for cleaner scoring.
    if raw_artist and " - " in raw_title:
        title_prefix, title_remainder = raw_title.split(" - ", 1)
        normalized_prefix = normalize_text(title_prefix)
        normalized_artist = normalize_text(raw_artist)
        normalized_primary_artist = normalize_text(primary_artist_name(raw_artist))

        should_strip_prefix = normalized_prefix in {
            normalized_artist,
            normalized_primary_artist,
        } or (
            bool(normalized_prefix)
            and (
                normalized_prefix in normalized_artist
                or normalized_prefix in normalized_primary_artist
                or normalized_artist.startswith(normalized_prefix)
                or normalized_primary_artist.startswith(normalized_prefix)
            )
        )

        if should_strip_prefix:
            raw_title = title_remainder

    return raw_artist.strip(), raw_title.strip()


def score_candidate(artist, title, matched_artist, matched_title):
    """Score a Discogs candidate against OCR-extracted artist and title."""
    artist_primary = primary_artist_name(artist)
    matched_artist_primary = primary_artist_name(matched_artist)

    title_base = strip_version_suffix(title)
    matched_title_base = strip_version_suffix(matched_title)

    artist_score = max(
        text_similarity(artist, matched_artist),
        text_similarity(artist_primary, matched_artist_primary),
        token_overlap(artist, matched_artist),
    )
    title_score = max(
        text_similarity(title, matched_title),
        text_similarity(title_base, matched_title_base),
        token_overlap(title, matched_title),
    )

    exact_artist = normalize_text(artist_primary) == normalize_text(
        matched_artist_primary
    )
    exact_title = title_base == matched_title_base and bool(title_base)

    combined_score = (artist_score * 0.45) + (title_score * 0.55)
    # Small bonuses reward strong exact matches.
    if exact_artist:
        combined_score += 0.08
    if exact_title:
        combined_score += 0.12

    return {
        "artist_score": artist_score,
        "title_score": title_score,
        "combined_score": min(combined_score, 1.0),
        "exact_artist": exact_artist,
        "exact_title": exact_title,
    }


def iter_release_candidates(client, artist, title, authenticated=True):
    """Yield unique Discogs release candidates from multiple query strategies."""
    primary_artist = primary_artist_name(artist)
    queries = [
        {"type": "release", "artist": artist, "release_title": title},
        {"type": "release", "artist": primary_artist, "release_title": title},
        {"type": "release", "q": f"{artist} {title}"},
        {"type": "release", "q": f"{primary_artist} {title}"},
        {"type": "release", "q": title, "artist": artist},
    ]

    seen_release_ids = set()

    for query in queries:
        try:
            search_results = call_discogs(
                lambda query=query: client.search(**query),
                authenticated=authenticated,
            )
        except Exception:
            continue

        for index, result in enumerate(
            iter_discogs_paginated_items(search_results, authenticated=authenticated)
        ):
            # Keep search bounded for predictable response and worker time.
            if index >= 10:
                break

            release_id = getattr(result, "id", None)
            if not release_id or release_id in seen_release_ids:
                continue

            seen_release_ids.add(release_id)
            yield result


def find_best_release_match(client, artist, title, authenticated=True):
    """Find the best matching Discogs release for a scanned album entry."""
    best_match = None

    for result in iter_release_candidates(
        client, artist, title, authenticated=authenticated
    ):
        matched_artist, matched_title = parse_release_result(result)
        scores = score_candidate(artist, title, matched_artist, matched_title)

        if (
            best_match is None
            or scores["combined_score"] > best_match["combined_score"]
        ):
            best_match = {
                "release_id": getattr(result, "id", None),
                "matched_artist": matched_artist,
                "matched_title": matched_title,
                **scores,
            }

    if not best_match:
        return {
            "status": "invalid",
            "message": "No Discogs release match found",
        }

    # Final quality gate before accepting a candidate as valid.
    # Allow an exact title plus strong artist similarity to pass, even when
    # punctuation/diacritics reduce one raw similarity component.
    has_strong_exact_title_match = (
        best_match["exact_title"] and best_match["artist_score"] >= 0.50
    )

    is_valid = best_match["release_id"] is not None and (
        (
            best_match["artist_score"] >= 0.58
            and best_match["title_score"] >= 0.68
            and best_match["combined_score"] >= 0.72
        )
        or has_strong_exact_title_match
    )

    return {
        "status": "valid" if is_valid else "invalid",
        "message": "Matched Discogs release"
        if is_valid
        else (
            f"Closest Discogs match was {best_match['matched_artist']} - "
            f"{best_match['matched_title']}"
        ),
        **best_match,
    }


def add_release_to_folder(client, username, folder_id, release_id):
    """Add a release to a Discogs collection folder."""
    url = (
        f"{client._base_url}/users/{username}/collection/"
        f"folders/{folder_id}/releases/{release_id}"
    )
    return call_discogs(lambda: client._post(url, None), authenticated=True)


def get_collection_folder(collection_folders, folder_id):
    """Return the selected Discogs collection folder object if it exists."""
    for folder in collection_folders:
        if folder.id == folder_id:
            return folder
    return None


def get_existing_folder_state(folder):
    """Load existing release IDs and logical album keys already present in a folder."""
    existing_release_ids = set()
    existing_album_keys = set()

    for item in iter_discogs_paginated_items(folder.releases, authenticated=True):
        release = getattr(item, "release", None)
        if not release:
            continue

        release_id = getattr(release, "id", None)
        if release_id is not None:
            existing_release_ids.add(int(release_id))

        release_title = getattr(release, "title", "")
        release_artists = getattr(release, "artists", None) or []
        release_artist = ""
        if release_artists:
            release_artist = getattr(release_artists[0], "name", "")

        if release_artist and release_title:
            existing_album_keys.add(album_identity_key(release_artist, release_title))

    return existing_release_ids, existing_album_keys


def is_discogs_duplicate_error(error):
    """Best-effort detection for Discogs duplicate-in-folder API responses."""
    message = str(getattr(error, "msg", "") or error).lower()
    status_code = getattr(error, "status_code", None)

    duplicate_markers = [
        "already in",
        "already exists",
        "duplicate",
        "already added",
    ]

    if any(marker in message for marker in duplicate_markers):
        return True

    return status_code in {409, 422} and "already" in message


def build_import_request_fingerprint(folder_id, entries):
    """Build a stable fingerprint for import idempotency."""
    normalized_entries = []
    for entry in entries:
        normalized_entries.append(
            {
                "id": str(entry.get("id", "")).strip(),
                "artist": str(entry.get("artist", "")).strip().lower(),
                "title": str(entry.get("title", "")).strip().lower(),
                "release_id": str(entry.get("release_id", "")).strip(),
            }
        )

    normalized_entries.sort(
        key=lambda item: (
            item["id"],
            item["artist"],
            item["title"],
            item["release_id"],
        )
    )

    payload = {
        "folder_id": int(folder_id),
        "entries": normalized_entries,
    }
    encoded_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded_payload.encode("utf-8")).hexdigest()


def album_identity_key(artist, title):
    """Build a normalized key for a logical album regardless of release variant."""
    return (
        normalize_text(primary_artist_name(artist)),
        strip_version_suffix(title),
    )


def album_lookup_normalized_key(artist, title):
    """Serialize the album identity key for Redis and Postgres lookups."""
    normalized_artist, normalized_title = album_identity_key(artist, title)
    return f"{normalized_artist}::{normalized_title}"


def album_lookup_cache_key(normalized_key):
    # Cached final result (valid or invalid).
    return f"discogs:lookup:{ALBUM_LOOKUP_CACHE_VERSION}:album:{normalized_key}"


def album_lookup_pending_key(normalized_key):
    # Short-lived marker that a background lookup is running.
    return f"discogs:lookup:{ALBUM_LOOKUP_CACHE_VERSION}:album:pending:{normalized_key}"


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


def build_pending_lookup_result(message="Queued for Discogs lookup"):
    return {
        "status": "pending",
        "message": message,
    }


def build_lookup_result_from_row(row, fallback_artist, fallback_title):
    """Translate a persisted albums row into the validation response shape."""
    release_id = row.get("discogs_release_id")

    if release_id is None:
        return {
            "status": "invalid",
            "message": "No Discogs release match found",
        }

    return {
        "status": "valid",
        "message": "Matched Discogs release",
        "release_id": int(release_id),
        "matched_artist": row.get("artist") or fallback_artist,
        "matched_title": row.get("album") or fallback_title,
    }


def read_cached_lookup_result(normalized_key):
    # Fast path: return immediately on Redis hit.
    payload = r.get(album_lookup_cache_key(normalized_key))
    if not payload:
        return None

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        r.delete(album_lookup_cache_key(normalized_key))
        return None


def write_cached_lookup_result(normalized_key, result, ttl_seconds=None):
    # Keep only the response fields the API needs to return.
    cacheable_result = {
        "status": result.get("status"),
        "message": result.get("message"),
        "release_id": result.get("release_id"),
        "matched_artist": result.get("matched_artist"),
        "matched_title": result.get("matched_title"),
    }

    effective_ttl = ttl_seconds or ALBUM_LOOKUP_CACHE_TTL_SECONDS

    r.setex(
        album_lookup_cache_key(normalized_key),
        effective_ttl,
        json.dumps(cacheable_result),
    )
    r.delete(album_lookup_pending_key(normalized_key))
    return cacheable_result


def fetch_lookup_row_from_postgres(normalized_key):
    # Durable fallback when Redis does not have the key.
    try:
        response = (
            supabase.table("albums")
            .select("artist, album, normalized_key, discogs_release_id")
            .eq("normalized_key", normalized_key)
            .limit(1)
            .execute()
        )
    except Exception as error:
        print(f"Failed to read cached album lookup from Supabase: {error}")
        return None

    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None


def persist_lookup_result(normalized_key, requested_artist, requested_title, match):
    # Persist valid matches in Postgres, and cache results in Redis.
    # Invalid results are Redis-only to avoid growing the albums table with NULL release rows.
    release_id = match.get("release_id") if match.get("status") == "valid" else None
    stored_artist = (
        match.get("matched_artist") if release_id is not None else requested_artist
    ) or requested_artist
    stored_album = (
        match.get("matched_title") if release_id is not None else requested_title
    ) or requested_title

    if release_id is None:
        try:
            # If this key already exists from older behavior, clear it.
            supabase.table("albums").delete().eq(
                "normalized_key", normalized_key
            ).execute()
        except Exception as error:
            print(f"Failed to delete invalid album lookup from Supabase: {error}")

        return write_cached_lookup_result(
            normalized_key,
            {
                "status": "invalid",
                "message": match.get("message") or "No Discogs release match found",
                "release_id": None,
                "matched_artist": None,
                "matched_title": None,
            },
            ttl_seconds=ALBUM_LOOKUP_INVALID_CACHE_TTL_SECONDS,
        )

    try:
        (
            supabase.table("albums")
            .upsert(
                {
                    "artist": stored_artist,
                    "album": stored_album,
                    "normalized_key": normalized_key,
                    "discogs_release_id": int(release_id),
                    "updated_at": utc_timestamp(),
                },
                on_conflict="normalized_key",
            )
            .execute()
        )
    except Exception as error:
        print(f"Failed to persist album lookup to Supabase: {error}")

    return write_cached_lookup_result(
        normalized_key,
        {
            "status": "valid",
            "message": match.get("message") or "Matched Discogs release",
            "release_id": int(release_id),
            "matched_artist": match.get("matched_artist"),
            "matched_title": match.get("matched_title"),
        },
    )


def enqueue_album_lookup_job(artist, title, normalized_key):
    # Deduplicate jobs by setting a pending key first.
    pending_key = album_lookup_pending_key(normalized_key)
    existing_job_id = r.get(pending_key)
    if existing_job_id:
        return existing_job_id

    acquired = r.set(
        pending_key,
        "queued",
        nx=True,
        ex=ALBUM_LOOKUP_PENDING_TTL_SECONDS,
    )
    if not acquired:
        return r.get(pending_key)

    try:
        job = lookup_queue.enqueue(
            DISCOGS_LOOKUP_JOB_FUNC,
            artist,
            title,
            normalized_key,
            job_timeout=DISCOGS_LOOKUP_JOB_TIMEOUT_SECONDS,
            result_ttl=0,
            failure_ttl=ALBUM_LOOKUP_PENDING_TTL_SECONDS,
        )
    except Exception:
        r.delete(pending_key)
        raise

    r.setex(pending_key, ALBUM_LOOKUP_PENDING_TTL_SECONDS, job.id)
    return job.id


def has_lookup_worker_available():
    """Return True when at least one worker is listening to the lookup queue."""
    try:
        workers = Worker.all(connection=r, queue=lookup_queue)
        return len(workers) > 0
    except Exception:
        return False


def count_lookup_pending_markers():
    """Count Redis pending markers used to deduplicate lookup jobs."""
    count = 0
    for _ in r.scan_iter(
        match=f"discogs:lookup:{ALBUM_LOOKUP_CACHE_VERSION}:album:pending:*"
    ):
        count += 1
    return count


def get_lookup_queue_stats():
    """Collect queue and worker telemetry for the validation pipeline."""
    workers = Worker.all(connection=r, queue=lookup_queue)
    started_registry = StartedJobRegistry(queue=lookup_queue)
    failed_registry = FailedJobRegistry(queue=lookup_queue)
    finished_registry = FinishedJobRegistry(queue=lookup_queue)
    deferred_registry = DeferredJobRegistry(queue=lookup_queue)

    return {
        "queue_name": lookup_queue.name,
        "workers_online": len(workers),
        "queued_jobs": lookup_queue.count,
        "started_jobs": len(started_registry),
        "failed_jobs": len(failed_registry),
        "finished_jobs": len(finished_registry),
        "deferred_jobs": len(deferred_registry),
        "pending_markers": count_lookup_pending_markers(),
        "sync_fallback_active": len(workers) == 0,
        "timestamp": utc_timestamp(),
    }


def resolve_release_match(artist, title, enqueue_if_missing=True):
    """Resolve an album validation from Redis, Postgres, or the async queue."""
    normalized_key = album_lookup_normalized_key(artist, title)
    pending_key = album_lookup_pending_key(normalized_key)

    # 1) Redis cache lookup.
    cached_result = read_cached_lookup_result(normalized_key)
    if cached_result:
        return cached_result

    # 2) Postgres lookup.
    persisted_row = fetch_lookup_row_from_postgres(normalized_key)
    if persisted_row:
        return write_cached_lookup_result(
            normalized_key,
            build_lookup_result_from_row(persisted_row, artist, title),
        )

    # 3) If already queued, return pending.
    if r.get(pending_key):
        if has_lookup_worker_available():
            return build_pending_lookup_result()
        # Clear stale pending markers when no worker is running.
        r.delete(pending_key)

    # Import flow can request "do not enqueue" and just observe pending state.
    if not enqueue_if_missing:
        return build_pending_lookup_result("Validation has not completed yet")

    if not has_lookup_worker_available():
        # Dev fallback: avoid infinite pending loops when worker is not started.
        try:
            return run_album_lookup_job(artist, title, normalized_key)
        except Exception as error:
            return {
                "status": "invalid",
                "message": f"Discogs lookup failed without worker: {error}",
            }

    # 4) Queue Discogs lookup.
    try:
        enqueue_album_lookup_job(artist, title, normalized_key)
    except Exception as error:
        return {
            "status": "invalid",
            "message": f"Failed to queue Discogs lookup: {error}",
        }

    return build_pending_lookup_result()


def run_album_lookup_job(artist, title, normalized_key=None):
    """Worker entrypoint for Discogs album lookups on cache misses."""
    lookup_key = normalized_key or album_lookup_normalized_key(artist, title)

    try:
        # Worker uses public Discogs search (no per-user auth context needed).
        client = get_public_discogs_client()
        match = find_best_release_match(client, artist, title, authenticated=False)
        return persist_lookup_result(lookup_key, artist, title, match)
    except Exception as error:
        r.delete(album_lookup_pending_key(lookup_key))
        print(f"Discogs lookup job failed for {artist} - {title}: {error}")
        raise


@app.route("/auth/request_token", methods=["GET"])
def get_request_token():
    """Create an OAuth request token and return Discogs authorize URL.

    Also stores `request_token` and `request_token_secret` in session so the
    access-token exchange step can complete later.
    """
    try:
        # Start OAuth handshake with Discogs.
        d = create_discogs_oauth_client()
        request_token, request_token_secret, url = call_discogs(
            lambda: d.get_authorize_url("http://192.168.1.146:5000/auth/callback"),
            authenticated=False,
        )

        print(request_token, request_token_secret, url)

        r.hset(
            request_token,
            mapping={
                # Redis holds temporary OAuth state between redirect steps.
                "request_token_secret": request_token_secret,
                "oauth_verifier": "",
                "created_at": time.time(),
            },
        )

        session["request_token"] = request_token
        session["request_token_secret"] = request_token_secret

        return jsonify(
            {
                "authorize_url": url,
                "oauth_token": request_token,
                "oauth_token_secret": request_token_secret,
            }
        )
    except HTTPError as e:
        return jsonify({"error": str(e)}), 500
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/auth/callback", methods=["GET"])
def callback():
    oauth_token = request.args.get("oauth_token")
    oauth_verifier = request.args.get("oauth_verifier")
    if r.hgetall(oauth_token):
        r.hset(oauth_token, "oauth_verifier", oauth_verifier)

    return jsonify({"ok": True, "oauth_token": oauth_token})


@app.route("/auth/access_token", methods=["GET"])
def exchange_access_token():
    oauth_token = request.args.get("oauth_token") or session.get("request_token")
    token_data = r.hgetall(oauth_token) if oauth_token else {}

    if not token_data:
        return {"error": "Missing or invalid oauth_token"}, 400

    oauth_token_secret = token_data.get("request_token_secret")
    oauth_verifier = token_data.get("oauth_verifier")

    if not oauth_verifier:
        return {"error": "Authorization not completed yet"}, 409

    print(oauth_token, oauth_token_secret)

    try:
        d = create_discogs_oauth_client()

        d.set_token(oauth_token, oauth_token_secret)
        # Exchange verifier for long-lived access token pair.
        access_token, access_token_secret = call_discogs(
            lambda: d.get_access_token(oauth_verifier),
            authenticated=False,
        )

        session["access_token"] = access_token
        session["access_token_secret"] = access_token_secret

        r.delete(oauth_token)

        print(access_token, access_token_secret)

        return jsonify(
            {
                "access_token": access_token,
                "access_token_secret": access_token_secret,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


@app.route("/data/upload", methods=["POST"])
def upload_image():
    """Upload an image to the authenticated user's data directory and track in Redis."""
    try:
        user_data_dir = get_user_data_dir()
        access_token = session.get("access_token")
    except ValueError:
        return {"error": "User not authenticated"}, 401

    if "file" not in request.files:
        return {"error": "No file field in request"}, 400

    file = request.files["file"]

    if file.mimetype not in ALLOWED_MIME:
        return {"error": "Unsupported file type"}, 415

    suffix = ".jpg" if file.mimetype == "image/jpeg" else ".png"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=user_data_dir)
    try:
        file.save(tmp.name)
    except Exception as e:
        os.unlink(tmp.name)
        return {"error": str(e)}, 500

    # Store image path in Redis with 1-hour TTL
    redis_key = f"user:{access_token}:latest_image"
    r.setex(redis_key, 3600, tmp.name)

    return {"path": tmp.name}


@app.route("/data/scan", methods=["POST"])
def scan_image():
    body = request.get_json(silent=True)
    if not body or "path" not in body:
        return {"error": "Missing 'path' in request body"}, 400

    path = body["path"]

    if not os.path.isfile(path):
        return {"error": "File not found"}, 404

    try:
        # OCR output is normalized into artist/title pairs.
        albums = ocr_main(path)
        return {"albums": albums}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/process/latest", methods=["GET"])
def process_latest_image():
    """Process the most recently taken image for the authenticated user.

    Retrieves the latest image path from Redis and processes it using the
    process_image module. Returns the extracted and cleaned album information.
    """
    try:
        access_token = session.get("access_token")
        if not access_token:
            raise ValueError("User not authenticated")
    except ValueError:
        return {"error": "User not authenticated"}, 401

    # Retrieve image path from Redis
    redis_key = f"user:{access_token}:latest_image"
    latest_image = r.get(redis_key)

    if not latest_image:
        return {"error": "No images found"}, 404

    if not os.path.isfile(latest_image):
        return {"error": "Image file not found or has expired"}, 404

    try:
        result = process_image_main(latest_image)
        return {"success": True, "image_path": latest_image, "result": result}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/data/albums", methods=["GET"])
def get_albums():
    try:
        d = get_discogs_client()
        user = get_discogs_identity(d)
    except ValueError:
        return jsonify({"error": "User not authenticated"}), 401

    albums = []
    collection_folders = get_discogs_collection_folders(user)
    if not collection_folders:
        return jsonify(albums)

    for album in iter_discogs_paginated_items(
        collection_folders[0].releases, authenticated=True
    ):
        albums.append(
            {"name": album.release.artists[0].name, "title": album.release.title}
        )

    return jsonify(albums)


@app.route("/discogs/collection-folders", methods=["GET"])
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


@app.route("/discogs/worker-status", methods=["GET"])
def discogs_worker_status():
    """Expose worker and queue status to debug validation pipeline health."""
    try:
        stats = get_lookup_queue_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/discogs/validate", methods=["POST"])
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

        # Validation is cache-first and async-aware.
        match = resolve_release_match(artist, title, enqueue_if_missing=True)
        validations.append({"id": entry_id, **match})

    return jsonify({"validations": validations})


@app.route("/discogs/import", methods=["POST"])
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

    cached_import_result = r.get(import_result_key)
    if cached_import_result:
        try:
            return jsonify(json.loads(cached_import_result))
        except json.JSONDecodeError:
            r.delete(import_result_key)

    lock_acquired = r.set(
        import_lock_key,
        "1",
        nx=True,
        ex=IMPORT_IDEMPOTENCY_TTL_SECONDS,
    )

    if not lock_acquired:
        # Another identical import request is likely in-flight or just completed.
        deadline = time.time() + 4.0
        while time.time() < deadline:
            cached_import_result = r.get(import_result_key)
            if cached_import_result:
                try:
                    return jsonify(json.loads(cached_import_result))
                except json.JSONDecodeError:
                    r.delete(import_result_key)
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

        # Track only this request's additions to avoid stale folder snapshots.
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
                # Import does not trigger new Discogs requests; it only consumes ready data.
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

            # Secondary logical dedupe after release resolution/normalization.
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

            try:
                add_release_to_folder(
                    d, user.username, folder_id, normalized_release_id
                )
                pending_release_ids.add(normalized_release_id)
                pending_album_keys.add(entry_album_key)
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

        r.setex(
            import_result_key,
            IMPORT_IDEMPOTENCY_TTL_SECONDS,
            json.dumps(response_payload),
        )

        return jsonify(response_payload)
    finally:
        r.delete(import_lock_key)


if __name__ == "__main__":
    """Run local Flask app for development."""
    import os

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
