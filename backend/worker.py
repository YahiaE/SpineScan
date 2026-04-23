import os
import sys

import redis
from rq import Queue, Worker

from config import (
    DISCOGS_LOOKUP_QUEUE,
    REDIS_HEALTH_CHECK_INTERVAL,
    REDIS_HOST,
    REDIS_WORKER_MAX_CONNECTIONS,
    REDIS_PORT,
    REDIS_RETRY_ON_TIMEOUT,
    REDIS_SOCKET_KEEPALIVE,
    REDIS_URL,
    RQ_WORKER_DEFAULT_TTL,
    RQ_WORKER_JOB_MONITORING_INTERVAL,
    RQ_WORKER_MAINTENANCE_INTERVAL,
)


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def build_redis_connection():
    redis_url = REDIS_URL
    pool_kwargs = {
        "socket_keepalive": REDIS_SOCKET_KEEPALIVE,
        "health_check_interval": REDIS_HEALTH_CHECK_INTERVAL,
        "retry_on_timeout": REDIS_RETRY_ON_TIMEOUT,
        "max_connections": REDIS_WORKER_MAX_CONNECTIONS,
    }

    if redis_url:
        pool = redis.ConnectionPool.from_url(
            redis_url,
            decode_responses=False,
            **pool_kwargs,
        )
        return redis.Redis(connection_pool=pool)

    pool = redis.ConnectionPool(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=False,
        **pool_kwargs,
    )
    return redis.Redis(connection_pool=pool)


if __name__ == "__main__":
    queue_name = DISCOGS_LOOKUP_QUEUE
    connection = build_redis_connection()
    worker = Worker(
        [Queue(queue_name, connection=connection)],
        connection=connection,
        default_worker_ttl=RQ_WORKER_DEFAULT_TTL,
        maintenance_interval=RQ_WORKER_MAINTENANCE_INTERVAL,
        job_monitoring_interval=RQ_WORKER_JOB_MONITORING_INTERVAL,
    )
    worker.work()
