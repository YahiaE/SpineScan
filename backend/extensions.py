import redis
from rq import Queue
from supabase import Client, create_client

from config import (
    DISCOGS_LOOKUP_QUEUE,
    REDIS_HOST,
    REDIS_PORT,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

redis_conn = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
lookup_queue = Queue(DISCOGS_LOOKUP_QUEUE, connection=redis_conn)
