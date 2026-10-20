import os
import sys
import time

import redis
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError, ResponseError, TimeoutError
from redis.retry import Retry
from rq import Queue, Worker

from config import (
    DISCOGS_LOOKUP_QUEUE,
    REDIS_HEALTH_CHECK_INTERVAL,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_SOCKET_KEEPALIVE,
    REDIS_URL,
    REDIS_WORKER_MAX_CONNECTIONS,
    RQ_WORKER_DEFAULT_TTL,
    RQ_WORKER_JOB_MONITORING_INTERVAL,
    RQ_WORKER_MAINTENANCE_INTERVAL,
)

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def build_redis_connection():
    # Configure retry policy using 'base' parameter for ExponentialBackoff
    retry_policy = Retry(
        ExponentialBackoff(base=1, cap=10),
        retries=5,
        supported_errors=(RedisConnectionError, TimeoutError, ResponseError),
    )

    pool_kwargs = {
        "socket_keepalive": REDIS_SOCKET_KEEPALIVE,
        "health_check_interval": REDIS_HEALTH_CHECK_INTERVAL or 15,
        "retry": retry_policy,
        "retry_on_timeout": True,
        "max_connections": REDIS_WORKER_MAX_CONNECTIONS,
        "socket_timeout": 30,
    }

    if REDIS_URL:
        pool = redis.ConnectionPool.from_url(
            REDIS_URL,
            decode_responses=False,
            **pool_kwargs,
        )
    else:
        pool = redis.ConnectionPool(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=False,
            **pool_kwargs,
        )

    return redis.Redis(connection_pool=pool)


if __name__ == "__main__":
    queue_name = DISCOGS_LOOKUP_QUEUE

    while True:
        try:
            connection = build_redis_connection()
            queue = Queue(queue_name, connection=connection)

            worker = Worker(
                [queue],
                connection=connection,
                default_worker_ttl=RQ_WORKER_DEFAULT_TTL,
                maintenance_interval=min(RQ_WORKER_MAINTENANCE_INTERVAL, 30),
                job_monitoring_interval=RQ_WORKER_JOB_MONITORING_INTERVAL,
            )

            # Blocks and processes incoming jobs
            worker.work(logging_level="INFO")

        except (ResponseError, RedisConnectionError, TimeoutError) as e:
            print(f"Redis connection dropped ({e}). Reconnecting in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"Unexpected error in worker loop ({e}). Restarting worker in 5 seconds...")
            time.sleep(5)