import redis
from rq import Queue
from supabase import Client, create_client

from config import (
    DISCOGS_LOOKUP_QUEUE,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_URL,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

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
