from functools import wraps

from flask import Blueprint, Response, jsonify, request

from config import OPS_API_KEY
from extensions import redis_conn, supabase
from services.discogs_service import get_discogs_call_metrics, get_lookup_queue_stats
from services.monitoring_service import get_http_metrics_snapshot


ops_bp = Blueprint("ops", __name__)


def _prometheus_escape(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def require_ops_api_key(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not OPS_API_KEY:
            return view_func(*args, **kwargs)

        provided_key = request.headers.get("X-Ops-Api-Key")
        if provided_key != OPS_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401

        return view_func(*args, **kwargs)

    return wrapped


@ops_bp.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"}), 200


@ops_bp.route("/readyz", methods=["GET"])
@require_ops_api_key
def readyz():
    checks = {
        "redis": False,
        "supabase": False,
        "lookup_worker_online": False,
    }
    errors = {}

    try:
        checks["redis"] = bool(redis_conn.ping())
    except Exception as error:
        errors["redis"] = str(error)

    try:
        response = supabase.table("captures").select("id").limit(1).execute()
        checks["supabase"] = response is not None
    except Exception as error:
        errors["supabase"] = str(error)

    try:
        queue_stats = get_lookup_queue_stats()
        checks["lookup_worker_online"] = queue_stats.get("workers_online", 0) > 0
    except Exception as error:
        errors["lookup_worker_online"] = str(error)

    is_ready = checks["redis"] and checks["supabase"]
    payload = {
        "status": "ready" if is_ready else "not_ready",
        "checks": checks,
        "errors": errors,
    }
    return jsonify(payload), 200 if is_ready else 503


@ops_bp.route("/metrics", methods=["GET"])
@require_ops_api_key
def metrics():
    http_metrics = get_http_metrics_snapshot()
    discogs_metrics = get_discogs_call_metrics()
    queue_stats = get_lookup_queue_stats()

    lines = []
    lines.append("# HELP spinescan_uptime_seconds Process uptime in seconds")
    lines.append("# TYPE spinescan_uptime_seconds gauge")
    lines.append(f"spinescan_uptime_seconds {http_metrics['uptime_seconds']:.3f}")

    lines.append("# HELP spinescan_http_requests_total Total HTTP requests observed")
    lines.append("# TYPE spinescan_http_requests_total counter")
    lines.append(f"spinescan_http_requests_total {http_metrics['requests_total']}")

    lines.append("# HELP spinescan_http_errors_5xx_total Total HTTP 5xx responses")
    lines.append("# TYPE spinescan_http_errors_5xx_total counter")
    lines.append(f"spinescan_http_errors_5xx_total {http_metrics['errors_5xx_total']}")

    lines.append(
        "# HELP spinescan_http_request_duration_seconds_avg Average request latency"
    )
    lines.append("# TYPE spinescan_http_request_duration_seconds_avg gauge")
    lines.append(
        f"spinescan_http_request_duration_seconds_avg {http_metrics['latency_avg_seconds']:.6f}"
    )

    lines.append(
        "# HELP spinescan_http_request_duration_seconds_p50 P50 request latency"
    )
    lines.append("# TYPE spinescan_http_request_duration_seconds_p50 gauge")
    lines.append(
        f"spinescan_http_request_duration_seconds_p50 {http_metrics['latency_p50_seconds']:.6f}"
    )

    lines.append(
        "# HELP spinescan_http_request_duration_seconds_p95 P95 request latency"
    )
    lines.append("# TYPE spinescan_http_request_duration_seconds_p95 gauge")
    lines.append(
        f"spinescan_http_request_duration_seconds_p95 {http_metrics['latency_p95_seconds']:.6f}"
    )

    lines.append("# HELP spinescan_http_requests_by_route_total HTTP requests by route")
    lines.append("# TYPE spinescan_http_requests_by_route_total counter")
    for route_key, count in sorted(http_metrics["route_counts"].items()):
        method, path, status_class = route_key.split(" ", 2)
        lines.append(
            "spinescan_http_requests_by_route_total"
            f'{{method="{_prometheus_escape(method)}",path="{_prometheus_escape(path)}",'
            f'status_class="{_prometheus_escape(status_class)}"}} {count}'
        )

    lines.append("# HELP spinescan_discogs_api_calls_total Discogs API call attempts")
    lines.append("# TYPE spinescan_discogs_api_calls_total counter")
    lines.append(f"spinescan_discogs_api_calls_total {discogs_metrics['calls_total']}")

    lines.append("# HELP spinescan_discogs_api_429_total Discogs 429 responses")
    lines.append("# TYPE spinescan_discogs_api_429_total counter")
    lines.append(
        f"spinescan_discogs_api_429_total {discogs_metrics['rate_limited_429_total']}"
    )

    lines.append("# HELP spinescan_discogs_api_errors_total Discogs API errors")
    lines.append("# TYPE spinescan_discogs_api_errors_total counter")
    lines.append(
        f"spinescan_discogs_api_errors_total {discogs_metrics['errors_total']}"
    )

    lines.append(
        "# HELP spinescan_discogs_api_latency_p95_seconds Discogs API call latency p95"
    )
    lines.append("# TYPE spinescan_discogs_api_latency_p95_seconds gauge")
    lines.append(
        f"spinescan_discogs_api_latency_p95_seconds {discogs_metrics['latency_p95_seconds']:.6f}"
    )

    lines.append(
        "# HELP spinescan_lookup_workers_online Number of lookup workers online"
    )
    lines.append("# TYPE spinescan_lookup_workers_online gauge")
    lines.append(f"spinescan_lookup_workers_online {queue_stats['workers_online']}")

    lines.append("# HELP spinescan_lookup_queue_depth Lookup queue depth")
    lines.append("# TYPE spinescan_lookup_queue_depth gauge")
    lines.append(f"spinescan_lookup_queue_depth {queue_stats['queued_jobs']}")

    lines.append("# HELP spinescan_lookup_started_jobs Lookup started jobs")
    lines.append("# TYPE spinescan_lookup_started_jobs gauge")
    lines.append(f"spinescan_lookup_started_jobs {queue_stats['started_jobs']}")

    lines.append("# HELP spinescan_lookup_breaker_open Whether lookup breaker is open")
    lines.append("# TYPE spinescan_lookup_breaker_open gauge")
    lines.append(
        f"spinescan_lookup_breaker_open {1 if queue_stats.get('lookup_breaker_open') else 0}"
    )

    body = "\n".join(lines) + "\n"
    return Response(body, mimetype="text/plain; version=0.0.4")
