import worker
from config import RQ_WORKER_DEFAULT_TTL
from worker import build_redis_connection, build_worker


def test_worker_redis_socket_timeout_exceeds_blocking_dequeue_wait():
    connection = build_redis_connection()
    socket_timeout = connection.connection_pool.connection_kwargs["socket_timeout"]

    assert socket_timeout > RQ_WORKER_DEFAULT_TTL - 15


def test_worker_uses_configured_maintenance_interval(monkeypatch):
    worker_options = {}
    monkeypatch.setattr(worker, "RQ_WORKER_MAINTENANCE_INTERVAL", 123)
    monkeypatch.setattr(worker, "Queue", lambda name, connection: name)
    monkeypatch.setattr(
        worker,
        "Worker",
        lambda queues, **kwargs: worker_options.update(kwargs),
    )

    build_worker(None)

    assert worker_options["maintenance_interval"] == 123
