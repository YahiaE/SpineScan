import math
import time
from collections import deque
from threading import Lock


_request_lock = Lock()
_request_started_at = time.time()
_request_total = 0
_request_error_total = 0
_request_latencies = deque(maxlen=5000)
_request_route_counts = {}


def _quantile(values, quantile):
    if not values:
        return 0.0

    sorted_values = sorted(values)
    index = int(math.ceil(quantile * len(sorted_values))) - 1
    index = max(0, min(index, len(sorted_values) - 1))
    return float(sorted_values[index])


def record_http_request(method, path, status_code, duration_seconds):
    global _request_total, _request_error_total

    status_class = f"{int(status_code) // 100}xx"
    route_key = f"{method.upper()} {path} {status_class}"

    with _request_lock:
        _request_total += 1
        if int(status_code) >= 500:
            _request_error_total += 1

        _request_latencies.append(float(duration_seconds))
        _request_route_counts[route_key] = _request_route_counts.get(route_key, 0) + 1


def get_http_metrics_snapshot():
    with _request_lock:
        latencies = list(_request_latencies)
        total = _request_total
        errors = _request_error_total
        route_counts = dict(_request_route_counts)

    avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
    p50_latency = _quantile(latencies, 0.50)
    p95_latency = _quantile(latencies, 0.95)

    uptime_seconds = max(0.0, time.time() - _request_started_at)

    return {
        "uptime_seconds": uptime_seconds,
        "requests_total": total,
        "errors_5xx_total": errors,
        "error_rate_5xx": (errors / total) if total else 0.0,
        "latency_avg_seconds": avg_latency,
        "latency_p50_seconds": p50_latency,
        "latency_p95_seconds": p95_latency,
        "route_counts": route_counts,
    }
