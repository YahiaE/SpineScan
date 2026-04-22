import redis
from rq import Queue
from supabase import Client, create_client

from config import (
    DISCOGS_LOOKUP_QUEUE,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_URL,
    SUPABASE_SECRET_KEY,
    SUPABASE_URL,
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

if REDIS_URL:
    redis_conn = redis.from_url(REDIS_URL, decode_responses=True)
    rq_redis_conn = redis.from_url(REDIS_URL, decode_responses=False)
else:
    redis_conn = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    rq_redis_conn = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=False,
    )

lookup_queue = Queue(DISCOGS_LOOKUP_QUEUE, connection=rq_redis_conn)

# Safety assertion: rq_redis_conn must never have decode_responses=True or RQ
# binary pickle payloads will be corrupted at runtime.
_rq_pool_kwargs = rq_redis_conn.connection_pool.connection_kwargs
assert not _rq_pool_kwargs.get("decode_responses", False), (
    "rq_redis_conn must have decode_responses=False for RQ binary job payloads. "
    "Check REDIS_URL and extension initialisation."
)
