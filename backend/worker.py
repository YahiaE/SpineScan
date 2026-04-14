import os
import sys

import redis
from rq import Queue, Worker


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def build_redis_connection():
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return redis.from_url(redis_url, decode_responses=True)

    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        decode_responses=True,
    )


if __name__ == "__main__":
    queue_name = os.getenv("DISCOGS_LOOKUP_QUEUE", "discogs-lookups")
    connection = build_redis_connection()
    worker = Worker([Queue(queue_name, connection=connection)], connection=connection)
    worker.work()
