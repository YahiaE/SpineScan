import os
import sys

import redis
from rq import Queue, Worker

from config import (
    REDIS_HEALTH_CHECK_INTERVAL,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_RETRY_ON_TIMEOUT,
    REDIS_SOCKET_KEEPALIVE,
    REDIS_URL,
)


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def build_redis_connection():
    redis_url = REDIS_URL
    common_kwargs = {
        "socket_keepalive": REDIS_SOCKET_KEEPALIVE,
        "health_check_interval": REDIS_HEALTH_CHECK_INTERVAL,
        "retry_on_timeout": REDIS_RETRY_ON_TIMEOUT,
    }

    if redis_url:
        return redis.from_url(
            redis_url,
            decode_responses=False,
            **common_kwargs,
        )

    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=False,
        **common_kwargs,
    )


if __name__ == "__main__":
    queue_name = os.getenv("DISCOGS_LOOKUP_QUEUE", "discogs-lookups")
    connection = build_redis_connection()
    worker = Worker([Queue(queue_name, connection=connection)], connection=connection)
    worker.work()
