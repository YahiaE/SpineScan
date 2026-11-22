import routes.ops_routes as ops_routes


def test_healthz_reports_process_is_alive(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_readyz_returns_ready_when_dependencies_are_available(client, monkeypatch):
    class SupabaseResponse:
        data = [{"id": 1}]

    class SupabaseQuery:
        def select(self, _fields):
            return self

        def limit(self, _limit):
            return self

        def execute(self):
            return SupabaseResponse()

    class SupabaseClient:
        def table(self, _name):
            return SupabaseQuery()

    class RedisClient:
        def ping(self):
            return True

    monkeypatch.setattr(ops_routes, "redis_conn", RedisClient())
    monkeypatch.setattr(ops_routes, "supabase", SupabaseClient())
    monkeypatch.setattr(
        ops_routes,
        "get_lookup_queue_stats",
        lambda: {"workers_online": 1},
    )

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"


def test_readyz_returns_service_unavailable_when_dependency_fails(
    client, monkeypatch
):
    class RedisClient:
        def ping(self):
            raise ConnectionError("redis unavailable")

    class SupabaseClient:
        def table(self, _name):
            raise ConnectionError("supabase unavailable")

    monkeypatch.setattr(ops_routes, "redis_conn", RedisClient())
    monkeypatch.setattr(ops_routes, "supabase", SupabaseClient())
    monkeypatch.setattr(
        ops_routes,
        "get_lookup_queue_stats",
        lambda: {"workers_online": 0},
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.get_json()["status"] == "not_ready"


def test_metrics_returns_prometheus_text(client, monkeypatch):
    monkeypatch.setattr(
        ops_routes,
        "get_lookup_queue_stats",
        lambda: {
            "workers_online": 0,
            "queued_jobs": 0,
            "oldest_queued_job_age_seconds": 0,
            "stale_jobs_dropped": 0,
            "started_jobs": 0,
            "lookup_breaker_open": False,
        },
    )
    monkeypatch.setattr(
        ops_routes,
        "get_discogs_call_metrics",
        lambda: {
            "calls_total": 0,
            "rate_limited_429_total": 0,
            "errors_total": 0,
            "latency_p95_seconds": 0,
        },
    )

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "spinescan_http_requests_total" in response.get_data(as_text=True)
