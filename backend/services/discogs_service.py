import hashlib
import json
import os
import secrets
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from collections import deque
from datetime import datetime, timezone
from difflib import SequenceMatcher
from threading import BoundedSemaphore, Lock

from services.lazy_loader import get_discogs_client_class, get_discogs_Client
from discogs_client.exceptions import HTTPError
from flask import session
from redis.exceptions import NoScriptError
from rq import Worker
from rq.registry import (
    DeferredJobRegistry,
    FailedJobRegistry,
    FinishedJobRegistry,
    StartedJobRegistry,
)

from config import (
    ALBUM_LOOKUP_CACHE_VERSION,
    ALBUM_LOOKUP_INVALID_CACHE_TTL_SECONDS,
    ALBUM_LOOKUP_PENDING_TTL_SECONDS,
    COLLECTION_CACHE_TTL_SECONDS,
    COLLECTION_CACHE_VERSION,
    DISCOGS_COLLECTION_WARM_MAX_PAGES,
    DISCOGS_AUTH_REQUEST_LIMIT,
    DISCOGS_LOOKUP_EARLY_ACCEPT_SCORE,
    DISCOGS_LOOKUP_BREAKER_TTL_SECONDS,
    DISCOGS_LOOKUP_JOB_FUNC,
    DISCOGS_LOOKUP_JOB_TIMEOUT_SECONDS,
    DISCOGS_LOOKUP_MAX_CALLS_PER_ALBUM,
    DISCOGS_LOOKUP_MAX_JOB_AGE_SECONDS,
    DISCOGS_LOOKUP_MAX_QUEUE_DEPTH,
    DISCOGS_LOOKUP_MAX_PAGES_PER_QUERY,
    DISCOGS_LOOKUP_MAX_STARTED_JOBS,
    DISCOGS_LOOKUP_MAX_QUERY_STRATEGIES,
    DISCOGS_LOOKUP_429_BREAK_THRESHOLD,
    DISCOGS_LOOKUP_SYNC_FAILURE_THRESHOLD,
    DISCOGS_MAX_RETRIES,
    DISCOGS_RATE_WINDOW_SECONDS,
    DISCOGS_SYNC_LOOKUP_ENABLED,
    DISCOGS_SYNC_LOOKUP_MAX_IN_FLIGHT,
    DISCOGS_SYNC_LOOKUP_TIMEOUT_SECONDS,
    DISCOGS_UNAUTH_REQUEST_LIMIT,
)
from extensions import lookup_queue, redis_conn, supabase


_sync_lookup_executor = ThreadPoolExecutor(
    max_workers=max(1, DISCOGS_SYNC_LOOKUP_MAX_IN_FLIGHT)
)
_sync_lookup_slots = BoundedSemaphore(max(1, DISCOGS_SYNC_LOOKUP_MAX_IN_FLIGHT))
_discogs_metrics_lock = Lock()
_discogs_latencies = deque(maxlen=5000)
_discogs_calls_total = 0
_discogs_calls_authenticated_total = 0
_discogs_calls_unauthenticated_total = 0
_discogs_rate_limited_429_total = 0
_discogs_errors_total = 0
_AUTH_SESSION_REDIS_PREFIX = "discogs:auth-session:v1"

try:
    _AUTH_SESSION_TTL_SECONDS = max(
        300,
        int(os.getenv("AUTH_SESSION_TTL_SECONDS", "86400")),
    )
except (TypeError, ValueError):
    _AUTH_SESSION_TTL_SECONDS = 86400

try:
    _AUTH_SESSION_REFRESH_INTERVAL_SECONDS = max(
        60,
        int(os.getenv("AUTH_SESSION_REFRESH_INTERVAL_SECONDS", "1800")),
    )
except (TypeError, ValueError):
    _AUTH_SESSION_REFRESH_INTERVAL_SECONDS = 1800

try:
    _AUTH_SESSION_LOCAL_CACHE_TTL_SECONDS = max(
        5,
        int(os.getenv("AUTH_SESSION_LOCAL_CACHE_TTL_SECONDS", "30")),
    )
except (TypeError, ValueError):
    _AUTH_SESSION_LOCAL_CACHE_TTL_SECONDS = 30

try:
    _AUTH_SESSION_LOCAL_CACHE_MISS_TTL_SECONDS = max(
        1,
        int(os.getenv("AUTH_SESSION_LOCAL_CACHE_MISS_TTL_SECONDS", "5")),
    )
except (TypeError, ValueError):
    _AUTH_SESSION_LOCAL_CACHE_MISS_TTL_SECONDS = 5

try:
    _LOOKUP_STATS_CACHE_TTL_SECONDS = max(
        1,
        int(os.getenv("LOOKUP_STATS_CACHE_TTL_SECONDS", "2")),
    )
except (TypeError, ValueError):
    _LOOKUP_STATS_CACHE_TTL_SECONDS = 2

try:
    _STALE_JOB_SWEEP_INTERVAL_SECONDS = max(
        5,
        int(os.getenv("STALE_JOB_SWEEP_INTERVAL_SECONDS", "30")),
    )
except (TypeError, ValueError):
    _STALE_JOB_SWEEP_INTERVAL_SECONDS = 30

_auth_session_local_cache = {}
_auth_session_local_cache_lock = Lock()
_discogs_rate_limit_acquire_script_sha = None
_discogs_rate_limit_script_lock = Lock()
_lookup_stats_cache = {"value": None, "expires_at": 0.0}
_lookup_stats_cache_lock = Lock()
_last_stale_job_sweep_at = 0.0
_stale_job_sweep_lock = Lock()

_DISCogs_RATE_LIMIT_ACQUIRE_SCRIPT = """
local configured_limit = tonumber(redis.call('GET', KEYS[1]) or ARGV[1])
local default_limit = tonumber(ARGV[1])
local ttl_seconds = tonumber(ARGV[2])

if not configured_limit or configured_limit < 1 then
    configured_limit = default_limit
end

if redis.call('GET', KEYS[2]) then
    return {0, 1, configured_limit, 0}
end

local current_count = redis.call('INCRBY', KEYS[3], 1)
if current_count == 1 then
    redis.call('EXPIRE', KEYS[3], ttl_seconds)
end

if current_count <= configured_limit then
    return {1, 0, configured_limit, current_count}
end

redis.call('DECRBY', KEYS[3], 1)
return {0, 0, configured_limit, current_count - 1}
"""


def _quantile(values, quantile):
    if not values:
        return 0.0

    sorted_values = sorted(values)
    index = int((len(sorted_values) - 1) * quantile)
    index = max(0, min(index, len(sorted_values) - 1))
    return float(sorted_values[index])


def record_discogs_api_call(authenticated, duration_seconds, status_code):
    global _discogs_calls_total
    global _discogs_calls_authenticated_total
    global _discogs_calls_unauthenticated_total
    global _discogs_rate_limited_429_total
    global _discogs_errors_total

    with _discogs_metrics_lock:
        _discogs_calls_total += 1
        if authenticated:
            _discogs_calls_authenticated_total += 1
        else:
            _discogs_calls_unauthenticated_total += 1

        _discogs_latencies.append(float(duration_seconds))

        if int(status_code) == 429:
            _discogs_rate_limited_429_total += 1

        if int(status_code) >= 400:
            _discogs_errors_total += 1


def get_discogs_call_metrics():
    with _discogs_metrics_lock:
        latencies = list(_discogs_latencies)
        calls_total = _discogs_calls_total
        calls_authenticated = _discogs_calls_authenticated_total
        calls_unauthenticated = _discogs_calls_unauthenticated_total
        rate_limited_429_total = _discogs_rate_limited_429_total
        errors_total = _discogs_errors_total

    avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
    p95_latency = _quantile(latencies, 0.95)

    return {
        "calls_total": calls_total,
        "calls_authenticated_total": calls_authenticated,
        "calls_unauthenticated_total": calls_unauthenticated,
        "rate_limited_429_total": rate_limited_429_total,
        "errors_total": errors_total,
        "latency_avg_seconds": avg_latency,
        "latency_p95_seconds": p95_latency,
    }


def _auth_session_key(auth_session_id):
    return f"{_AUTH_SESSION_REDIS_PREFIX}:{auth_session_id}"


def _get_or_create_auth_session_id():
    auth_session_id = session.get("auth_session_id")
    if auth_session_id:
        return auth_session_id

    auth_session_id = secrets.token_urlsafe(32)
    session["auth_session_id"] = auth_session_id
    return auth_session_id


def persist_discogs_auth_tokens(access_token, access_token_secret, discogs_username):
    """Persist Discogs auth server-side and keep only opaque id in cookie session."""
    auth_session_id = _get_or_create_auth_session_id()
    auth_key = _auth_session_key(auth_session_id)

    redis_conn.hset(
        auth_key,
        mapping={
            "access_token": access_token,
            "access_token_secret": access_token_secret,
            "discogs_username": discogs_username or "",
            "updated_at": utc_timestamp(),
        },
    )
    redis_conn.expire(auth_key, _AUTH_SESSION_TTL_SECONDS)
    session["auth_session_ttl_refreshed_at"] = time.time()
    _set_cached_auth_session_data(
        auth_session_id,
        {
            "access_token": access_token,
            "access_token_secret": access_token_secret,
            "discogs_username": discogs_username or "",
        },
    )

    # Keep non-sensitive username in session for existing flow compatibility.
    session["discogs_username"] = discogs_username

    # Remove legacy token fields from cookie-backed session.
    session.pop("access_token", None)
    session.pop("access_token_secret", None)


def get_discogs_auth_tokens():
    """Read Discogs auth from Redis by opaque auth-session id."""
    try:
        auth_session_id = session.get("auth_session_id")
        if auth_session_id:
            auth_key = _auth_session_key(auth_session_id)
            token_data = _get_auth_session_token_data(auth_session_id)
            access_token = token_data.get("access_token")
            access_token_secret = token_data.get("access_token_secret")
            if access_token and access_token_secret:
                _refresh_auth_session_ttl_if_needed(auth_key)
                return access_token, access_token_secret

        return None, None
    except RuntimeError:
        return None, None


def get_discogs_auth_session_status():
    """Return non-sensitive status details for auth-session observability."""
    try:
        auth_session_id = session.get("auth_session_id")
        session_username = session.get("discogs_username")
        legacy_cookie_fields_present = bool(
            session.get("access_token") or session.get("access_token_secret")
        )

        if not auth_session_id:
            return {
                "source": "none",
                "authorized": False,
                "has_auth_session_id": False,
                "redis_record_found": False,
                "legacy_cookie_fields_present": legacy_cookie_fields_present,
                "discogs_username": session_username,
            }

        auth_key = _auth_session_key(auth_session_id)
        token_data = _get_auth_session_token_data(auth_session_id)
        has_tokens = bool(
            token_data.get("access_token") and token_data.get("access_token_secret")
        )

        if token_data:
            _refresh_auth_session_ttl_if_needed(auth_key)

        return {
            "source": "redis" if has_tokens else "none",
            "authorized": has_tokens,
            "has_auth_session_id": True,
            "redis_record_found": bool(token_data),
            "legacy_cookie_fields_present": legacy_cookie_fields_present,
            "discogs_username": token_data.get("discogs_username") or session_username,
        }
    except RuntimeError:
        return {
            "source": "none",
            "authorized": False,
            "has_auth_session_id": False,
            "redis_record_found": False,
            "legacy_cookie_fields_present": False,
            "discogs_username": None,
        }
    except Exception:
        return {
            "source": "error",
            "authorized": False,
            "has_auth_session_id": bool(session.get("auth_session_id")),
            "redis_record_found": False,
            "legacy_cookie_fields_present": bool(
                session.get("access_token") or session.get("access_token_secret")
            ),
            "discogs_username": session.get("discogs_username"),
        }


def get_discogs_access_token():
    access_token, _ = get_discogs_auth_tokens()
    return access_token


def _refresh_auth_session_ttl_if_needed(auth_key):
    last_refreshed_at = session.get("auth_session_ttl_refreshed_at")
    now = time.time()

    try:
        last_refreshed_at = float(last_refreshed_at)
    except (TypeError, ValueError):
        last_refreshed_at = None

    if (
        last_refreshed_at is not None
        and now - last_refreshed_at < _AUTH_SESSION_REFRESH_INTERVAL_SECONDS
    ):
        return

    redis_conn.expire(auth_key, _AUTH_SESSION_TTL_SECONDS)
    session["auth_session_ttl_refreshed_at"] = now


def _set_cached_auth_session_data(auth_session_id, token_data):
    now = time.time()
    ttl_seconds = (
        _AUTH_SESSION_LOCAL_CACHE_TTL_SECONDS
        if token_data
        else _AUTH_SESSION_LOCAL_CACHE_MISS_TTL_SECONDS
    )
    with _auth_session_local_cache_lock:
        _auth_session_local_cache[auth_session_id] = {
            "token_data": token_data,
            "expires_at": now + ttl_seconds,
        }


def _get_cached_auth_session_data(auth_session_id):
    now = time.time()
    with _auth_session_local_cache_lock:
        cached_entry = _auth_session_local_cache.get(auth_session_id)
        if not cached_entry:
            return None

        if cached_entry.get("expires_at", 0) <= now:
            _auth_session_local_cache.pop(auth_session_id, None)
            return None

        return cached_entry.get("token_data") or {}


def _get_auth_session_token_data(auth_session_id):
    token_data = _get_cached_auth_session_data(auth_session_id)
    if token_data is not None:
        return token_data

    auth_key = _auth_session_key(auth_session_id)
    access_token, access_token_secret, discogs_username = redis_conn.hmget(
        auth_key,
        ["access_token", "access_token_secret", "discogs_username"],
    )
    token_data = {}
    if access_token or access_token_secret or discogs_username:
        token_data = {
            "access_token": access_token or "",
            "access_token_secret": access_token_secret or "",
            "discogs_username": discogs_username or "",
        }
    _set_cached_auth_session_data(auth_session_id, token_data)
    return token_data


def get_discogs_auth_tokens_for_session(auth_session_id):
    """Resolve Discogs credentials inside the worker from an opaque session ID."""
    if not auth_session_id:
        return None, None

    token_data = _get_auth_session_token_data(auth_session_id)
    access_token = token_data.get("access_token")
    access_token_secret = token_data.get("access_token_secret")
    if not access_token or not access_token_secret:
        return None, None

    return access_token, access_token_secret


def get_discogs_client():
    """Create an authenticated Discogs client from the current session."""
    access_token, access_token_secret = get_discogs_auth_tokens()

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

    discogs_client_module = get_discogs_client_class()  # Lazy load discogs_client

    return discogs_client_module.Client(
        "my_user_agent/1.0",
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
    )


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def get_discogs_rate_bucket_scope(authenticated, access_token=None):
    if authenticated and access_token:
        token_hash = hashlib.sha256(str(access_token).encode("utf-8")).hexdigest()[:12]
        return f"user:{token_hash}"

    return "global"


def get_discogs_rate_bucket_key(authenticated, scope="global"):
    bucket_start = int(time.time() // DISCOGS_RATE_WINDOW_SECONDS)
    bucket_name = "auth" if authenticated else "unauth"
    return f"discogs:rate:{bucket_name}:{scope}:{bucket_start}"


def discogs_rate_limit_total_key(authenticated, scope="global"):
    bucket_name = "auth" if authenticated else "unauth"
    return f"discogs:rate:{bucket_name}:{scope}:total"


def discogs_rate_limit_block_key(authenticated, scope="global"):
    bucket_name = "auth" if authenticated else "unauth"
    return f"discogs:rate:{bucket_name}:{scope}:blocked"


def lookup_breaker_key():
    return f"discogs:lookup:{ALBUM_LOOKUP_CACHE_VERSION}:breaker"


def lookup_429_streak_key():
    return f"discogs:lookup:{ALBUM_LOOKUP_CACHE_VERSION}:429-streak"


def lookup_sync_failures_key():
    return f"discogs:lookup:{ALBUM_LOOKUP_CACHE_VERSION}:sync-failures"


def build_degraded_lookup_result(
    message="Validation delayed. Please try again shortly.",
):
    return build_pending_lookup_result(message)


def open_lookup_breaker(reason, ttl_seconds=DISCOGS_LOOKUP_BREAKER_TTL_SECONDS):
    try:
        redis_conn.setex(lookup_breaker_key(), max(1, int(ttl_seconds)), reason)
    except Exception:
        pass


def get_lookup_breaker_reason():
    try:
        return redis_conn.get(lookup_breaker_key())
    except Exception:
        return None


def get_lookup_breaker_state():
    reason = get_lookup_breaker_reason()
    return bool(reason), reason


def is_lookup_breaker_open():
    breaker_open, _ = get_lookup_breaker_state()
    return breaker_open


def record_discogs_429():
    try:
        streak = redis_conn.incr(lookup_429_streak_key())
        if streak == 1:
            redis_conn.expire(lookup_429_streak_key(), DISCOGS_RATE_WINDOW_SECONDS)

        if streak >= DISCOGS_LOOKUP_429_BREAK_THRESHOLD:
            open_lookup_breaker("discogs_429")
    except Exception:
        pass


def record_sync_lookup_failure():
    try:
        failure_count = redis_conn.incr(lookup_sync_failures_key())
        if failure_count == 1:
            redis_conn.expire(
                lookup_sync_failures_key(),
                DISCOGS_LOOKUP_BREAKER_TTL_SECONDS,
            )

        if failure_count >= DISCOGS_LOOKUP_SYNC_FAILURE_THRESHOLD:
            open_lookup_breaker("sync_lookup_failure")
    except Exception:
        pass


def _try_acquire_discogs_rate_limit_slot(authenticated, rate_scope):
    default_limit = (
        DISCOGS_AUTH_REQUEST_LIMIT if authenticated else DISCOGS_UNAUTH_REQUEST_LIMIT
    )
    keys = [
        discogs_rate_limit_total_key(authenticated, rate_scope),
        discogs_rate_limit_block_key(authenticated, rate_scope),
        get_discogs_rate_bucket_key(authenticated, rate_scope),
    ]
    args = [default_limit, DISCOGS_RATE_WINDOW_SECONDS * 2]

    result = _eval_discogs_rate_limit_script(keys, args)
    granted = bool(int(result[0]))
    blocked = bool(int(result[1]))
    limit = _safe_int(result[2], default_limit)
    current_count = _safe_int(result[3], 0)
    return {
        "granted": granted,
        "blocked": blocked,
        "limit": limit,
        "current_count": current_count,
    }


def _get_discogs_rate_limit_script_sha():
    global _discogs_rate_limit_acquire_script_sha

    with _discogs_rate_limit_script_lock:
        if _discogs_rate_limit_acquire_script_sha:
            return _discogs_rate_limit_acquire_script_sha

        _discogs_rate_limit_acquire_script_sha = redis_conn.script_load(
            _DISCogs_RATE_LIMIT_ACQUIRE_SCRIPT
        )
        return _discogs_rate_limit_acquire_script_sha


def _eval_discogs_rate_limit_script(keys, args):
    script_sha = _get_discogs_rate_limit_script_sha()

    try:
        return redis_conn.evalsha(script_sha, len(keys), *keys, *args)
    except NoScriptError:
        pass
    except Exception as error:
        if "NOSCRIPT" not in str(error).upper():
            raise

    global _discogs_rate_limit_acquire_script_sha
    with _discogs_rate_limit_script_lock:
        _discogs_rate_limit_acquire_script_sha = None

    script_sha = _get_discogs_rate_limit_script_sha()
    return redis_conn.evalsha(script_sha, len(keys), *keys, *args)


def _extract_discogs_headers_from_http_error(error):
    response = getattr(error, "response", None)
    if response is None:
        return {}

    headers = getattr(response, "headers", None)
    if not headers:
        return {}

    return {
        "limit": headers.get("X-Discogs-Ratelimit"),
        "used": headers.get("X-Discogs-Ratelimit-Used"),
        "remaining": headers.get("X-Discogs-Ratelimit-Remaining"),
    }


def _extract_discogs_headers_from_client(api_call):
    client = None
    closure = getattr(api_call, "__closure__", None) or []

    for cell in closure:
        value = getattr(cell, "cell_contents", None)
        if isinstance(value, get_discogs_Client()):
            client = value
            break

    if client is None:
        return {}

    fetcher = getattr(client, "_fetcher", None)
    response = getattr(fetcher, "last_response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return {}

    return {
        "limit": headers.get("X-Discogs-Ratelimit"),
        "used": headers.get("X-Discogs-Ratelimit-Used"),
        "remaining": headers.get("X-Discogs-Ratelimit-Remaining"),
    }


def _apply_discogs_rate_headers(authenticated, scope, headers):
    if not headers:
        return

    limit = _safe_int(headers.get("limit"), 0)
    remaining = _safe_int(headers.get("remaining"), -1)

    if limit > 0:
        try:
            redis_conn.setex(
                discogs_rate_limit_total_key(authenticated, scope),
                DISCOGS_RATE_WINDOW_SECONDS * 2,
                str(limit),
            )
        except Exception:
            pass

    if remaining == 0:
        try:
            redis_conn.setex(
                discogs_rate_limit_block_key(authenticated, scope),
                2,
                "1",
            )
        except Exception:
            pass


def acquire_discogs_rate_limit_slot(authenticated=True, rate_scope="global"):
    """Block until a shared Discogs rate-limit slot is available."""
    while True:
        try:
            slot_result = _try_acquire_discogs_rate_limit_slot(
                authenticated,
                rate_scope,
            )
        except Exception:
            # Redis unavailable: fail open so Discogs calls can still proceed.
            return

        if slot_result["granted"]:
            return

        wait_seconds = max(
            0.25,
            DISCOGS_RATE_WINDOW_SECONDS
            - (time.time() % DISCOGS_RATE_WINDOW_SECONDS)
            + 0.05,
        )
        time.sleep(min(wait_seconds, 5.0))


def call_discogs(api_call, authenticated=True, rate_scope="global"):
    """Run a Discogs API call under a shared rate limiter with basic 429 retry."""
    last_error = None

    for attempt in range(DISCOGS_MAX_RETRIES):
        acquire_discogs_rate_limit_slot(
            authenticated=authenticated,
            rate_scope=rate_scope,
        )
        call_started_at = time.perf_counter()

        try:
            result = api_call()
            _apply_discogs_rate_headers(
                authenticated,
                rate_scope,
                _extract_discogs_headers_from_client(api_call),
            )
            record_discogs_api_call(
                authenticated=authenticated,
                duration_seconds=time.perf_counter() - call_started_at,
                status_code=200,
            )
            return result
        except HTTPError as error:
            status_code = int(getattr(error, "status_code", 500) or 500)
            record_discogs_api_call(
                authenticated=authenticated,
                duration_seconds=time.perf_counter() - call_started_at,
                status_code=status_code,
            )
            _apply_discogs_rate_headers(
                authenticated,
                rate_scope,
                _extract_discogs_headers_from_http_error(error),
            )
            last_error = error
            if status_code != 429:
                raise

            record_discogs_429()

            if attempt == DISCOGS_MAX_RETRIES - 1:
                raise

            time.sleep(min(2**attempt, 8))
        except Exception:
            record_discogs_api_call(
                authenticated=authenticated,
                duration_seconds=time.perf_counter() - call_started_at,
                status_code=500,
            )
            raise

    if last_error is not None:
        raise last_error


class LookupBudget:
    """Track and cap Discogs API calls consumed by one album lookup."""

    def __init__(self, max_calls):
        self.max_calls = max(1, int(max_calls))
        self.calls_used = 0

    def consume(self):
        if self.calls_used >= self.max_calls:
            return False

        self.calls_used += 1
        return True


def iter_discogs_paginated_items(
    paginated,
    authenticated=True,
    max_pages=1,
    budget=None,
    rate_scope="global",
):
    """Iterate a Discogs paginated list while rate-limiting each page fetch."""
    max_pages = max(1, int(max_pages))

    if max_pages == 1:
        if budget and not budget.consume():
            return

        page_items = call_discogs(
            lambda: paginated.page(1),
            authenticated=authenticated,
            rate_scope=rate_scope,
        )
        for item in page_items:
            yield item
        return

    if budget and not budget.consume():
        return

    total_pages = call_discogs(
        lambda: paginated.pages,
        authenticated=authenticated,
        rate_scope=rate_scope,
    )

    for page_index in range(1, min(total_pages, max_pages) + 1):
        if budget and not budget.consume():
            return

        page_items = call_discogs(
            lambda page_index=page_index: paginated.page(page_index),
            authenticated=authenticated,
            rate_scope=rate_scope,
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


def compact_identity_text(value):
    """Normalize album identity strings and remove spaces for canonical keys."""
    return normalize_text(value).replace(" ", "")


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


def is_cd_release_result(result):
    """Return True when Discogs search metadata indicates a CD format release."""
    raw_formats = []

    direct_format = getattr(result, "format", None)
    if direct_format:
        raw_formats.append(direct_format)

    direct_formats = getattr(result, "formats", None)
    if direct_formats:
        raw_formats.extend(direct_formats)

    data = getattr(result, "data", None)
    if isinstance(data, dict):
        data_format = data.get("format")
        if data_format:
            raw_formats.append(data_format)

    normalized_formats = []
    for item in raw_formats:
        if isinstance(item, str):
            normalized_formats.append(item.lower())
        elif isinstance(item, (list, tuple, set)):
            normalized_formats.extend(str(value).lower() for value in item if value)

    return any("cd" in value for value in normalized_formats)


def iter_release_candidates(
    client,
    artist,
    title,
    authenticated=True,
    budget=None,
    rate_scope="global",
):
    """Yield unique Discogs release candidates from multiple query strategies."""
    primary_artist = primary_artist_name(artist)
    queries = [
        {
            "type": "release",
            "artist": artist,
            "release_title": title,
            "format": "CD",
        },
        {
            "type": "release",
            "artist": primary_artist,
            "release_title": title,
            "format": "CD",
        },
        {"type": "release", "q": f"{artist} {title}", "format": "CD"},
        {"type": "release", "q": f"{primary_artist} {title}", "format": "CD"},
        {"type": "release", "q": title, "artist": artist, "format": "CD"},
    ][: max(1, DISCOGS_LOOKUP_MAX_QUERY_STRATEGIES)]

    seen_release_ids = set()
    last_search_error = None

    for query in queries:
        if budget and not budget.consume():
            break

        try:
            search_results = call_discogs(
                lambda query=query: client.search(**query),
                authenticated=authenticated,
                rate_scope=rate_scope,
            )
        except Exception as error:
            last_search_error = error
            continue

        for index, result in enumerate(
            iter_discogs_paginated_items(
                search_results,
                authenticated=authenticated,
                max_pages=DISCOGS_LOOKUP_MAX_PAGES_PER_QUERY,
                budget=budget,
                rate_scope=rate_scope,
            )
        ):
            if index >= 10:
                break

            release_id = getattr(result, "id", None)
            if not release_id or release_id in seen_release_ids:
                continue

            if not is_cd_release_result(result):
                continue

            seen_release_ids.add(release_id)
            yield result

    if last_search_error is not None:
        raise last_search_error


def find_best_release_match(
    client,
    artist,
    title,
    authenticated=True,
    rate_scope="global",
):
    """Find the best matching Discogs release for a scanned album entry."""
    best_match = None
    budget = LookupBudget(DISCOGS_LOOKUP_MAX_CALLS_PER_ALBUM)

    for result in iter_release_candidates(
        client,
        artist,
        title,
        authenticated=authenticated,
        budget=budget,
        rate_scope=rate_scope,
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

            should_accept_early = (
                best_match["exact_title"]
                and best_match["artist_score"] >= 0.65
                and best_match["combined_score"] >= DISCOGS_LOOKUP_EARLY_ACCEPT_SCORE
            )
            if should_accept_early:
                break

    if not best_match:
        return {
            "status": "invalid",
            "message": "No Discogs release match found",
        }

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
    """Add a release without requiring Discogs to return a JSON body."""
    url = (
        f"{client._base_url}/users/{username}/collection/"
        f"folders/{folder_id}/releases/{release_id}"
    )

    def post_release():
        headers = {
            "Accept-Encoding": "gzip",
            "User-Agent": client.user_agent,
        }
        content, status_code = client._fetcher.fetch(
            client,
            "POST",
            url,
            headers=headers,
        )
        if 200 <= status_code < 300:
            return None

        try:
            error_body = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            error_body = {}
        message = (
            error_body.get("message")
            if isinstance(error_body, dict)
            else None
        )
        raise HTTPError(message or "Discogs rejected the collection update", status_code)

    return call_discogs(post_release, authenticated=True)


def get_collection_folder(collection_folders, folder_id):
    """Return the selected Discogs collection folder object if it exists."""
    for folder in collection_folders:
        if folder.id == folder_id:
            return folder
    return None


def serialize_album_identity_key(album_key):
    """Serialize an album identity tuple for cache and durable lookup keys."""
    artist_key, title_key = album_key
    return f"{artist_key}::{title_key}"


def _upsert_albums_from_collection_cache(rows_by_key):
    """Mirror unique cached collection entries into the albums lookup table."""
    if not rows_by_key:
        return

    release_ids = []
    for row in rows_by_key.values():
        release_id = row.get("discogs_release_id")
        if release_id is not None:
            release_ids.append(int(release_id))

    existing_rows = []
    existing_rows_by_release = {}
    if release_ids:
        try:
            response = (
                supabase.table("albums")
                .select("artist, album, normalized_key, discogs_release_id")
                .in_("discogs_release_id", sorted(set(release_ids)))
                .execute()
            )
            existing_rows = getattr(response, "data", None) or []
            existing_rows_by_release = {
                int(row["discogs_release_id"]): row
                for row in existing_rows
                if row.get("discogs_release_id") is not None
            }
        except Exception as error:
            print(f"Failed to read existing albums for collection mirror: {error}")

    desired_keys_by_release = {}
    resolved_rows_by_key = {}
    for row in rows_by_key.values():
        release_id = row.get("discogs_release_id")
        existing_row = None
        if release_id is not None:
            normalized_release_id = int(release_id)
            desired_keys_by_release[normalized_release_id] = row.get("normalized_key")
            existing_row = existing_rows_by_release.get(normalized_release_id)

        if existing_row:
            resolved_row = {
                "artist": existing_row.get("artist") or row.get("artist"),
                "album": existing_row.get("album") or row.get("album"),
                "normalized_key": row.get("normalized_key"),
                "discogs_release_id": int(release_id),
                "updated_at": row.get("updated_at") or utc_timestamp(),
            }
        else:
            resolved_row = row

        resolved_rows_by_key[resolved_row["normalized_key"]] = resolved_row

    try:
        (
            supabase.table("albums")
            .upsert(
                list(resolved_rows_by_key.values()),
                on_conflict="normalized_key",
            )
            .execute()
        )
    except Exception as error:
        print(f"Failed to mirror collection cache into albums table: {error}")
        return

    stale_keys = []
    for existing_row in existing_rows:
        release_id = existing_row.get("discogs_release_id")
        if release_id is None:
            continue

        desired_key = desired_keys_by_release.get(int(release_id))
        existing_key = existing_row.get("normalized_key")
        if desired_key and existing_key and existing_key != desired_key:
            stale_keys.append(existing_key)

    unique_stale_keys = sorted(set(stale_keys))
    for offset in range(0, len(unique_stale_keys), 500):
        try:
            (
                supabase.table("albums")
                .delete()
                .in_("normalized_key", unique_stale_keys[offset : offset + 500])
                .execute()
            )
        except Exception as error:
            print(f"Failed to delete stale albums keys: {error}")


def _mirror_albums_from_durable_collection_cache(discogs_username, folder_id):
    """Hydrate albums table from durable collection cache rows."""
    try:
        response = (
            supabase.table("discogs_collection_cache")
            .select("album_key, release_id, last_seen_at")
            .eq("discogs_username", discogs_username)
            .eq("folder_id", int(folder_id))
            .limit(5000)
            .execute()
        )
    except Exception as error:
        print(f"Failed to read durable collection cache for albums mirror: {error}")
        return

    rows = getattr(response, "data", None) or []
    album_rows_by_key = {}
    for row in rows:
        album_key = str(row.get("album_key") or "").strip()
        release_id = row.get("release_id")
        if not album_key or "::" not in album_key or release_id is None:
            continue

        artist_key, title_key = album_key.split("::", 1)
        album_rows_by_key[album_key] = {
            "artist": artist_key,
            "album": title_key,
            "normalized_key": album_key,
            "discogs_release_id": int(release_id),
            "updated_at": row.get("last_seen_at") or utc_timestamp(),
        }

    _upsert_albums_from_collection_cache(album_rows_by_key)


def refresh_collection_cache_from_discogs(client, discogs_username, folder):
    """Refresh Supabase collection cache from current Discogs folder state."""
    folder_id = int(folder.id)
    durable_rows_by_release = {}
    album_rows_by_key = {}

    # Fetch fresh collection from Discogs
    for item in iter_discogs_paginated_items(
        folder.releases,
        authenticated=True,
        max_pages=DISCOGS_COLLECTION_WARM_MAX_PAGES,
    ):
        release = getattr(item, "release", None) or item
        release_id = getattr(release, "id", None)
        if release_id is None:
            continue

        release_title = getattr(release, "title", "")
        release_artists = getattr(release, "artists", None) or []
        release_artist_name = ""
        if release_artists:
            release_artist_name = getattr(release_artists[0], "name", "") or ""

        album_key = album_identity_key(release_artist_name, release_title)
        serialized_album_key = serialize_album_identity_key(album_key)
        durable_rows_by_release[int(release_id)] = {
            "discogs_username": discogs_username,
            "folder_id": folder_id,
            "release_id": int(release_id),
            "album_key": serialized_album_key,
            "last_seen_at": utc_timestamp(),
        }
        album_rows_by_key[serialized_album_key] = {
            "artist": release_artist_name or album_key[0],
            "album": release_title or album_key[1],
            "normalized_key": serialized_album_key,
            "discogs_release_id": int(release_id),
            "updated_at": utc_timestamp(),
        }

    # Persist to Supabase only (no Redis)
    durable_rows = list(durable_rows_by_release.values())
    if durable_rows:
        try:
            (
                supabase.table("discogs_collection_cache")
                .upsert(
                    durable_rows,
                    on_conflict="discogs_username,folder_id,release_id",
                )
                .execute()
            )
        except Exception as error:
            print(f"Failed to refresh collection cache: {error}")

    # Mirror to albums lookup table
    _upsert_albums_from_collection_cache(album_rows_by_key)
    return set(durable_rows_by_release), set(album_rows_by_key)


def ensure_collection_membership_cache_warm(client, discogs_username, folder):
    """Refresh collection cache from Discogs for the selected folder.

    This updates Supabase with the latest collection state when the user
    selects a folder for import, ensuring duplicate checks are always current.
    """
    try:
        return refresh_collection_cache_from_discogs(client, discogs_username, folder)
    except Exception as error:
        # Non-fatal: duplicate detection falls back to API response
        print(f"Collection cache refresh failed: {error}")
        return None


def sync_collection_membership_cache(
    discogs_username,
    folder_id,
    entries_to_cache,
    entries_to_mirror,
):
    """Batch collection membership writes and their album-table mirrors."""
    if not entries_to_cache and not entries_to_mirror:
        return

    normalized_cache_entries = {
        int(release_id): album_key
        for release_id, album_key in entries_to_cache.items()
    }
    normalized_mirror_entries = [
        (int(release_id), album_key)
        for release_id, album_key in entries_to_mirror
    ]
    timestamp = utc_timestamp()

    if normalized_cache_entries:
        collection_rows = [
            {
                "discogs_username": discogs_username,
                "folder_id": int(folder_id),
                "release_id": release_id,
                "album_key": serialize_album_identity_key(album_key),
                "last_seen_at": timestamp,
            }
            for release_id, album_key in normalized_cache_entries.items()
        ]
        try:
            (
                supabase.table("discogs_collection_cache")
                .upsert(
                    collection_rows,
                    on_conflict="discogs_username,folder_id,release_id",
                )
                .execute()
            )
        except Exception as error:
            print(f"Failed to update collection cache: {error}")

    album_rows_by_key = {}
    album_entries = [
        *normalized_mirror_entries,
        *normalized_cache_entries.items(),
    ]
    for release_id, album_key in album_entries:
        serialized_album_key = serialize_album_identity_key(album_key)
        album_rows_by_key[serialized_album_key] = {
            "artist": album_key[0],
            "album": album_key[1],
            "normalized_key": serialized_album_key,
            "discogs_release_id": release_id,
            "updated_at": timestamp,
        }

    _upsert_albums_from_collection_cache(album_rows_by_key)


def load_collection_cache_membership(discogs_username, folder_id):
    """Load one folder's cached membership into in-memory sets for import checks."""
    normalized_folder_id = int(folder_id)

    try:
        response = (
            supabase.table("discogs_collection_cache")
            .select("release_id, album_key")
            .eq("discogs_username", discogs_username)
            .eq("folder_id", normalized_folder_id)
            .limit(5000)
            .execute()
        )
        rows = getattr(response, "data", None) or []
    except Exception as error:
        print(f"Failed to load collection cache membership: {error}")
        return set(), set()

    release_ids = set()
    album_keys = set()
    for row in rows:
        release_id = row.get("release_id")
        album_key = str(row.get("album_key") or "").strip()

        if release_id is not None:
            try:
                release_ids.add(int(release_id))
            except (TypeError, ValueError):
                pass

        if album_key:
            album_keys.add(album_key)

    return release_ids, album_keys


def is_release_in_collection_cache(discogs_username, folder_id, release_id):
    """Return True when release is already in the collection (queried from Supabase)."""
    normalized_release_id = int(release_id)

    try:
        response = (
            supabase.table("discogs_collection_cache")
            .select("release_id")
            .eq("discogs_username", discogs_username)
            .eq("folder_id", int(folder_id))
            .eq("release_id", normalized_release_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
    except Exception as error:
        print(f"Failed to check release in collection cache: {error}")
        return False

    return bool(rows)


def is_album_in_collection_cache(discogs_username, folder_id, album_key):
    """Return True when album is already in the collection (queried from Supabase)."""
    serialized_album_key = serialize_album_identity_key(album_key)

    try:
        response = (
            supabase.table("discogs_collection_cache")
            .select("album_key")
            .eq("discogs_username", discogs_username)
            .eq("folder_id", int(folder_id))
            .eq("album_key", serialized_album_key)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
    except Exception as error:
        print(f"Failed to check album in collection cache: {error}")
        return False

    return bool(rows)


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
    """Build a stable fingerprint for import idempotency.

    Prefer Discogs release IDs so inline artist/title edits do not bypass
    idempotency checks and trigger duplicate imports.
    """
    normalized_entries = []
    for entry in entries:
        raw_release_id = str(entry.get("release_id", "")).strip()
        try:
            normalized_release_id = str(int(raw_release_id)) if raw_release_id else ""
        except (TypeError, ValueError):
            normalized_release_id = ""

        normalized_entries.append(
            {
                "id": str(entry.get("id", "")).strip(),
                "release_id": normalized_release_id,
            }
        )

    normalized_entries.sort(
        key=lambda item: (
            item["release_id"],
            item["id"],
        )
    )

    payload = {
        "folder_id": int(folder_id),
        "entries": normalized_entries,
    }
    encoded_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded_payload.encode("utf-8")).hexdigest()


def album_identity_key(artist, title):
    """Build a normalized no-space key for a logical album identity."""
    return (
        compact_identity_text(primary_artist_name(artist)),
        compact_identity_text(strip_version_suffix(title)),
    )


def album_lookup_normalized_key(artist, title):
    """Serialize the album identity key for Redis and Postgres lookups."""
    normalized_artist, normalized_title = album_identity_key(artist, title)
    return f"{normalized_artist}::{normalized_title}"


def album_lookup_pending_key(normalized_key):
    return f"discogs:lookup:{ALBUM_LOOKUP_CACHE_VERSION}:album:pending:{normalized_key}"


def album_lookup_result_key(normalized_key):
    return f"discogs:lookup:{ALBUM_LOOKUP_CACHE_VERSION}:album:result:v3:{normalized_key}"


def pending_lookup_index_key():
    return f"discogs:lookup:{ALBUM_LOOKUP_CACHE_VERSION}:album:pending:index"


def _track_pending_lookup_key(pending_key):
    expires_at = time.time() + ALBUM_LOOKUP_PENDING_TTL_SECONDS
    redis_conn.zadd(pending_lookup_index_key(), {pending_key: expires_at})


def _untrack_pending_lookup_key(pending_key):
    redis_conn.zrem(pending_lookup_index_key(), pending_key)


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
    try:
        cached_result = redis_conn.get(album_lookup_result_key(normalized_key))
        if not cached_result:
            return None
        if isinstance(cached_result, bytes):
            cached_result = cached_result.decode("utf-8")
        result = json.loads(cached_result)
        return (
            result
            if isinstance(result, dict) and result.get("status") == "invalid"
            else None
        )
    except Exception:
        return None


def write_cached_lookup_result(normalized_key, result, ttl_seconds=None):
    cacheable_result = {
        "status": result.get("status"),
        "message": result.get("message"),
        "release_id": result.get("release_id"),
        "matched_artist": result.get("matched_artist"),
        "matched_title": result.get("matched_title"),
    }

    try:
        if cacheable_result.get("status") == "valid":
            redis_conn.delete(album_lookup_result_key(normalized_key))
        elif ttl_seconds and cacheable_result.get("status") == "invalid":
            redis_conn.setex(
                album_lookup_result_key(normalized_key),
                int(ttl_seconds),
                json.dumps(cacheable_result),
            )
    except Exception:
        pass

    try:
        pending_key = album_lookup_pending_key(normalized_key)
        redis_conn.delete(pending_key)
        _untrack_pending_lookup_key(pending_key)
    except Exception:
        # Redis unavailable: still return the computed result to the caller.
        pass

    return cacheable_result


def fetch_lookup_row_from_postgres(normalized_key):
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


def prefetch_release_lookup_states(entries):
    """Batch-load durable, negative-cache, and pending state for validation entries."""
    normalized_keys = sorted(
        {
            album_lookup_normalized_key(entry["artist"], entry["title"])
            for entry in entries
            if entry.get("artist") and entry.get("title")
        }
    )
    if not normalized_keys:
        return {}

    rows_by_key = {}
    database_read_succeeded = False
    try:
        response = (
            supabase.table("albums")
            .select("artist, album, normalized_key, discogs_release_id")
            .in_("normalized_key", normalized_keys)
            .execute()
        )
        rows_by_key = {
            row["normalized_key"]: row
            for row in (getattr(response, "data", None) or [])
        }
        database_read_succeeded = True
    except Exception as error:
        print(f"Failed to batch-read album lookup states: {error}")

    result_cache_keys = [album_lookup_result_key(key) for key in normalized_keys]
    pending_keys = [album_lookup_pending_key(key) for key in normalized_keys]
    redis_read_succeeded = False
    cached_results = [None] * len(normalized_keys)
    pending_values = [None] * len(normalized_keys)
    try:
        lookup_values = redis_conn.mget(result_cache_keys + pending_keys)
        cached_results = lookup_values[: len(normalized_keys)]
        pending_values = lookup_values[len(normalized_keys) :]
        redis_read_succeeded = True
    except Exception:
        pass

    states_by_key = {}
    for index, normalized_key in enumerate(normalized_keys):
        cached_result = cached_results[index]
        if isinstance(cached_result, bytes):
            cached_result = cached_result.decode("utf-8")
        try:
            cached_result = json.loads(cached_result) if cached_result else None
        except (json.JSONDecodeError, TypeError):
            cached_result = None

        states_by_key[normalized_key] = {
            "row": rows_by_key.get(normalized_key),
            "cached_result": (
                cached_result
                if isinstance(cached_result, dict)
                and cached_result.get("status") == "invalid"
                else None
            ),
            "pending": bool(pending_values[index]),
            "database_read_succeeded": database_read_succeeded,
            "redis_read_succeeded": redis_read_succeeded,
        }

    return states_by_key


def get_lookup_statuses(entries):
    """Read lookup results and pending markers in batches without calling Discogs."""
    keys_by_entry_id = {
        entry.get("id"): album_lookup_normalized_key(entry["artist"], entry["title"])
        for entry in entries
    }
    normalized_keys = sorted(set(keys_by_entry_id.values()))
    rows_by_key = {}
    database_read_succeeded = False

    try:
        response = (
            supabase.table("albums")
            .select("artist, album, normalized_key, discogs_release_id")
            .in_("normalized_key", normalized_keys)
            .execute()
        )
        rows_by_key = {
            row["normalized_key"]: row
            for row in (getattr(response, "data", None) or [])
        }
        database_read_succeeded = True
    except Exception as error:
        print(f"Failed to read lookup statuses from Supabase: {error}")

    result_cache_keys = [album_lookup_result_key(key) for key in normalized_keys]
    pending_keys = [album_lookup_pending_key(key) for key in normalized_keys]
    try:
        lookup_values = redis_conn.mget(result_cache_keys + pending_keys)
        cached_results = lookup_values[: len(normalized_keys)]
        pending_values = lookup_values[len(normalized_keys) :]
    except Exception:
        cached_results = [None] * len(normalized_keys)
        pending_values = [None] * len(normalized_keys)

    cached_by_key = {}
    pending_by_key = {}
    for key, cached_result, pending_value in zip(
        normalized_keys, cached_results, pending_values
    ):
        if cached_result:
            try:
                if isinstance(cached_result, bytes):
                    cached_result = cached_result.decode("utf-8")
                parsed_result = json.loads(cached_result)
                if isinstance(parsed_result, dict):
                    cached_by_key[key] = parsed_result
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                pass
        pending_by_key[key] = bool(pending_value)

    validations = []
    retry_ids = []
    for entry in entries:
        entry_id = entry.get("id")
        normalized_key = keys_by_entry_id[entry_id]
        row = rows_by_key.get(normalized_key)
        cached_result = cached_by_key.get(normalized_key)

        if row:
            result = build_lookup_result_from_row(
                row,
                entry.get("artist", ""),
                entry.get("title", ""),
            )
        elif cached_result:
            result = cached_result
        elif pending_by_key.get(normalized_key):
            result = build_pending_lookup_result()
        elif not database_read_succeeded:
            result = build_pending_lookup_result("Waiting for lookup status")
        else:
            retry_ids.append(entry_id)
            continue

        validations.append({"id": entry_id, **result})

    return {"validations": validations, "retry_ids": retry_ids}


def persist_lookup_result(normalized_key, requested_artist, requested_title, match):
    release_id = match.get("release_id") if match.get("status") == "valid" else None
    stored_artist = (
        match.get("matched_artist") if release_id is not None else requested_artist
    ) or requested_artist
    stored_album = (
        match.get("matched_title") if release_id is not None else requested_title
    ) or requested_title

    if release_id is None:
        try:
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


def enqueue_album_lookup_job(
    artist,
    title,
    normalized_key,
    auth_session_id=None,
):
    pending_key = album_lookup_pending_key(normalized_key)
    acquired = redis_conn.set(
        pending_key,
        "queued",
        nx=True,
        ex=ALBUM_LOOKUP_PENDING_TTL_SECONDS,
    )
    if not acquired:
        return None

    try:
        _track_pending_lookup_key(pending_key)
    except Exception:
        pass

    try:
        if auth_session_id:
            job = lookup_queue.enqueue(
                run_album_lookup_job_authenticated,
                artist,
                title,
                normalized_key,
            auth_session_id,
                job_timeout=DISCOGS_LOOKUP_JOB_TIMEOUT_SECONDS,
                ttl=DISCOGS_LOOKUP_MAX_JOB_AGE_SECONDS,
                result_ttl=0,
                failure_ttl=ALBUM_LOOKUP_PENDING_TTL_SECONDS,
            )
        else:
            job = lookup_queue.enqueue(
                DISCOGS_LOOKUP_JOB_FUNC,
                artist,
                title,
                normalized_key,
                job_timeout=DISCOGS_LOOKUP_JOB_TIMEOUT_SECONDS,
                ttl=DISCOGS_LOOKUP_MAX_JOB_AGE_SECONDS,
                result_ttl=0,
                failure_ttl=ALBUM_LOOKUP_PENDING_TTL_SECONDS,
            )
    except Exception:
        redis_conn.delete(pending_key)
        _untrack_pending_lookup_key(pending_key)
        raise

    redis_conn.setex(pending_key, ALBUM_LOOKUP_PENDING_TTL_SECONDS, job.id)
    return job.id


def build_lookup_request_context():
    """Build per-request lookup context so queue/worker checks are not repeated per entry."""
    try:
        queue_stats = get_lookup_queue_stats()
    except Exception:
        queue_stats = None

    worker_available = (
        queue_stats.get("workers_online", 0) > 0
        if queue_stats is not None
        else has_lookup_worker_available()
    )
    queue_saturated = False
    if worker_available:
        queue_saturated = is_lookup_queue_saturated(queue_stats)

    auth_session_id = None
    try:
        auth_session_id = session.get("auth_session_id")
    except RuntimeError:
        pass

    breaker_open, breaker_reason = get_lookup_breaker_state()

    return {
        "breaker_open": breaker_open,
        "breaker_reason": breaker_reason,
        "worker_available": worker_available,
        "queue_saturated": queue_saturated,
        "auth_session_id": auth_session_id,
    }


def has_lookup_worker_available():
    """Return True when at least one worker is listening to the lookup queue."""
    try:
        workers = Worker.all(connection=lookup_queue.connection, queue=lookup_queue)
        return len(workers) > 0
    except Exception:
        return False


def count_lookup_pending_markers():
    """Count Redis pending markers used to deduplicate lookup jobs."""
    try:
        now = time.time()
        index_key = pending_lookup_index_key()
        redis_conn.zremrangebyscore(index_key, 0, now)
        return redis_conn.zcard(index_key)
    except Exception:
        return 0


def _seconds_since(timestamp, now_utc):
    if not timestamp:
        return None

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return max(0.0, (now_utc - timestamp).total_seconds())


def _drop_stale_lookup_jobs(max_age_seconds):
    """Remove stale queued/started jobs so they fail explicitly instead of lingering."""
    global _last_stale_job_sweep_at

    now = time.time()
    with _stale_job_sweep_lock:
        if now - _last_stale_job_sweep_at < _STALE_JOB_SWEEP_INTERVAL_SECONDS:
            return 0
        _last_stale_job_sweep_at = now

    now_utc = datetime.now(timezone.utc)
    removed = 0

    try:
        for job_id in lookup_queue.job_ids:
            job = lookup_queue.fetch_job(job_id)
            if not job:
                continue

            age_seconds = _seconds_since(getattr(job, "enqueued_at", None), now_utc)
            if age_seconds is None or age_seconds <= max_age_seconds:
                continue

            try:
                job.cancel()
                job.delete()
                removed += 1
            except Exception:
                continue
    except Exception:
        return removed

    try:
        started_registry = StartedJobRegistry(queue=lookup_queue)
        for job_id in started_registry.get_job_ids():
            job = lookup_queue.fetch_job(job_id)
            if not job:
                continue

            age_seconds = _seconds_since(getattr(job, "started_at", None), now_utc)
            if age_seconds is None or age_seconds <= max_age_seconds:
                continue

            try:
                job.cancel()
                job.delete()
                removed += 1
            except Exception:
                continue
    except Exception:
        return removed

    return removed


def _collect_lookup_queue_stats_uncached():
    max_job_age_seconds = max(60, int(DISCOGS_LOOKUP_MAX_JOB_AGE_SECONDS))
    stale_jobs_dropped = _drop_stale_lookup_jobs(max_job_age_seconds)

    workers = Worker.all(connection=lookup_queue.connection, queue=lookup_queue)
    started_registry = StartedJobRegistry(queue=lookup_queue)
    failed_registry = FailedJobRegistry(queue=lookup_queue)
    finished_registry = FinishedJobRegistry(queue=lookup_queue)
    deferred_registry = DeferredJobRegistry(queue=lookup_queue)

    now_utc = datetime.now(timezone.utc)
    oldest_queued_job_age_seconds = 0.0
    for job_id in lookup_queue.job_ids:
        job = lookup_queue.fetch_job(job_id)
        if not job:
            continue

        age_seconds = _seconds_since(getattr(job, "enqueued_at", None), now_utc)
        if age_seconds is None:
            continue
        oldest_queued_job_age_seconds = max(oldest_queued_job_age_seconds, age_seconds)

    lookup_breaker_open, lookup_breaker_reason = get_lookup_breaker_state()

    return {
        "queue_name": lookup_queue.name,
        "workers_online": len(workers),
        "queued_jobs": lookup_queue.count,
        "started_jobs": len(started_registry),
        "failed_jobs": len(failed_registry),
        "finished_jobs": len(finished_registry),
        "deferred_jobs": len(deferred_registry),
        "pending_markers": count_lookup_pending_markers(),
        "oldest_queued_job_age_seconds": oldest_queued_job_age_seconds,
        "max_job_age_seconds": max_job_age_seconds,
        "stale_jobs_dropped": stale_jobs_dropped,
        "sync_fallback_active": len(workers) == 0,
        "lookup_breaker_open": lookup_breaker_open,
        "lookup_breaker_reason": lookup_breaker_reason,
        "timestamp": utc_timestamp(),
    }


def get_lookup_queue_stats():
    """Collect queue and worker telemetry for the validation pipeline."""
    now = time.time()
    with _lookup_stats_cache_lock:
        cached_value = _lookup_stats_cache.get("value")
        if cached_value and now < float(_lookup_stats_cache.get("expires_at", 0.0)):
            return dict(cached_value)

    stats = _collect_lookup_queue_stats_uncached()
    with _lookup_stats_cache_lock:
        _lookup_stats_cache["value"] = stats
        _lookup_stats_cache["expires_at"] = now + _LOOKUP_STATS_CACHE_TTL_SECONDS

    return dict(stats)


def is_lookup_queue_saturated(stats=None):
    try:
        stats = stats or get_lookup_queue_stats()
    except Exception:
        return False

    if stats["queued_jobs"] >= DISCOGS_LOOKUP_MAX_QUEUE_DEPTH:
        open_lookup_breaker("queue_depth")
        return True

    if stats["started_jobs"] >= DISCOGS_LOOKUP_MAX_STARTED_JOBS:
        open_lookup_breaker("started_jobs")
        return True

    return False


def run_sync_lookup_with_timeout(artist, title, normalized_key):
    """Execute sync fallback in a worker thread so request path has a hard timeout."""
    auth_session_id = None
    try:
        auth_session_id = session.get("auth_session_id")
    except RuntimeError:
        # No request context (for example tests/background calls), so fallback to public lookup.
        pass

    if auth_session_id:
        future = _sync_lookup_executor.submit(
            run_album_lookup_job_authenticated,
            artist,
            title,
            normalized_key,
            auth_session_id,
        )
    else:
        future = _sync_lookup_executor.submit(
            run_album_lookup_job, artist, title, normalized_key
        )

    try:
        timeout_seconds = max(0.5, float(DISCOGS_SYNC_LOOKUP_TIMEOUT_SECONDS))
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as error:
        future.cancel()
        raise TimeoutError(
            f"Synchronous lookup timed out after {timeout_seconds:.1f}s"
        ) from error


def try_run_sync_lookup_with_capacity(artist, title, normalized_key):
    """Run sync lookup only when an in-flight slot is available."""
    acquired = _sync_lookup_slots.acquire(blocking=False)
    if not acquired:
        raise RuntimeError("sync_lookup_capacity_reached")

    try:
        return run_sync_lookup_with_timeout(artist, title, normalized_key)
    finally:
        _sync_lookup_slots.release()


def resolve_release_match(artist, title, enqueue_if_missing=True, lookup_context=None):
    """Resolve an album validation from Supabase, then sync lookup/queue fallback.

    When enqueue_if_missing is False, this function still attempts sync lookup,
    but will not enqueue a worker job on cache misses.
    """
    normalized_key = album_lookup_normalized_key(artist, title)
    context = lookup_context or build_lookup_request_context()
    prefetched_state = context.get("prefetched_lookup_states", {}).get(
        normalized_key
    )

    persisted_row = (
        prefetched_state.get("row")
        if prefetched_state and prefetched_state.get("database_read_succeeded")
        else fetch_lookup_row_from_postgres(normalized_key)
    )
    if persisted_row:
        if prefetched_state:
            return build_lookup_result_from_row(persisted_row, artist, title)
        return write_cached_lookup_result(
            normalized_key,
            build_lookup_result_from_row(persisted_row, artist, title),
        )

    cached_result = (
        prefetched_state.get("cached_result")
        if prefetched_state and prefetched_state.get("redis_read_succeeded")
        else read_cached_lookup_result(normalized_key)
    )
    if cached_result:
        return cached_result

    if prefetched_state and prefetched_state.get("redis_read_succeeded"):
        if prefetched_state.get("pending"):
            return build_pending_lookup_result()
    else:
        try:
            if redis_conn.get(album_lookup_pending_key(normalized_key)):
                return build_pending_lookup_result()
        except Exception:
            pass

    if context.get("breaker_open"):
        return build_degraded_lookup_result()

    worker_available = bool(context.get("worker_available"))
    queue_saturated = bool(context.get("queue_saturated"))
    auth_session_id = context.get("auth_session_id")

    if enqueue_if_missing and worker_available:
        if queue_saturated:
            return build_degraded_lookup_result()

        try:
            enqueue_album_lookup_job(
                artist,
                title,
                normalized_key,
                auth_session_id=auth_session_id,
            )
        except Exception:
            record_sync_lookup_failure()
            open_lookup_breaker("queue_enqueue_failed")
            context["breaker_open"] = True
            return build_degraded_lookup_result(
                "Lookup queue unavailable. Please retry shortly."
            )

        return build_pending_lookup_result()

    if DISCOGS_SYNC_LOOKUP_ENABLED:
        try:
            return try_run_sync_lookup_with_capacity(artist, title, normalized_key)
        except RuntimeError as error:
            if str(error) != "sync_lookup_capacity_reached":
                record_sync_lookup_failure()
                context["breaker_open"], context["breaker_reason"] = (
                    get_lookup_breaker_state()
                )
        except Exception:
            record_sync_lookup_failure()
            context["breaker_open"], context["breaker_reason"] = (
                get_lookup_breaker_state()
            )

    if context.get("breaker_open"):
        return build_degraded_lookup_result()

    if not enqueue_if_missing:
        return build_pending_lookup_result("Validation has not completed yet")

    if not DISCOGS_SYNC_LOOKUP_ENABLED:
        open_lookup_breaker("sync_lookup_disabled")
        return build_degraded_lookup_result()

    return build_degraded_lookup_result()


def run_album_lookup_job(artist, title, normalized_key=None):
    """Worker entrypoint for Discogs album lookups on cache misses."""
    lookup_key = normalized_key or album_lookup_normalized_key(artist, title)

    try:
        client = get_public_discogs_client()
        match = find_best_release_match(
            client,
            artist,
            title,
            authenticated=False,
            rate_scope="global",
        )
        return persist_lookup_result(lookup_key, artist, title, match)
    except Exception as error:
        pending_key = album_lookup_pending_key(lookup_key)
        redis_conn.delete(pending_key)
        _untrack_pending_lookup_key(pending_key)
        print(f"Discogs lookup job failed for {artist} - {title}: {error}")
        raise


def run_album_lookup_job_authenticated(
    artist,
    title,
    normalized_key,
    auth_session_id,
    legacy_access_token_secret=None,
):
    """Look up an album using its auth session or credentials from an old queued job."""
    lookup_key = normalized_key or album_lookup_normalized_key(artist, title)

    try:
        if legacy_access_token_secret is not None:
            access_token = auth_session_id
            access_token_secret = legacy_access_token_secret
        else:
            access_token, access_token_secret = get_discogs_auth_tokens_for_session(
                auth_session_id
            )
        if not access_token or not access_token_secret:
            raise ValueError("Discogs auth session is unavailable")

        client = create_discogs_oauth_client()
        client.set_token(access_token, access_token_secret)
        rate_scope = get_discogs_rate_bucket_scope(
            authenticated=True,
            access_token=access_token,
        )
        match = find_best_release_match(
            client,
            artist,
            title,
            authenticated=True,
            rate_scope=rate_scope,
        )
        return persist_lookup_result(lookup_key, artist, title, match)
    except Exception as error:
        pending_key = album_lookup_pending_key(lookup_key)
        redis_conn.delete(pending_key)
        _untrack_pending_lookup_key(pending_key)
        print(f"Authenticated sync lookup failed for {artist} - {title}: {error}")
        raise
