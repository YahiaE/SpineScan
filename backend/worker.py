import os

import redis
from rq import Queue, Worker


def build_redis_connection():
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
