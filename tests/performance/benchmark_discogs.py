#!/usr/bin/env python3
"""Measure live Discogs validation latency through SpineScan's Flask route."""

import argparse
import math
import os
import secrets
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
DEFAULT_ALBUMS = (
    ("Radiohead", "OK Computer"),
    ("Nirvana", "Nevermind"),
)
REQUIRED_ENV = (
    "CONSUMER_KEY",
    "CONSUMER_SECRET",
    "DISCOGS_BENCHMARK_ACCESS_TOKEN",
    "DISCOGS_BENCHMARK_ACCESS_TOKEN_SECRET",
    "DISCOGS_BENCHMARK_USERNAME",
    "SUPABASE_URL",
    "SUPABASE_SECRET_KEY",
)


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def render_summary(samples, errors, failures, worker_count, api_calls, api_429s):
    phases = ("cache-miss", "cache-hit")
    lines = [
        "## SpineScan live Discogs lookup benchmark",
        "",
        "Path: Flask `POST /discogs/validate`; cache misses use synchronous "
        "fallback (RQ workers online: {}). Discogs calls: {}; HTTP 429s: {}."
        .format(worker_count, api_calls, api_429s),
        "",
        "| Path | Samples | Min (ms) | p50 (ms) | p95 (ms) | Max (ms) | Errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for phase in phases:
        values = samples[phase]
        if values:
            row = (
                f"| {phase} | {len(values)} | {min(values):.2f} | "
                f"{percentile(values, 0.50):.2f} | "
                f"{percentile(values, 0.95):.2f} | {max(values):.2f} | "
                f"{errors[phase]} |"
            )
        else:
            row = f"| {phase} | 0 | n/a | n/a | n/a | n/a | {errors[phase]} |"
        lines.append(row)

    lines.extend(["", f"Setup, rate-limit, or cleanup failures: {len(failures)}"])
    if failures:
        lines.extend(["", "### Errors"])
        lines.extend(f"- {failure.replace('|', '/').replace(chr(10), ' ')}" for failure in failures)
    lines.extend(
        [
            "",
            "The cold samples must resolve to valid Discogs releases. Cache-hit "
            "samples must use the durable Supabase `albums` row and make no "
            "additional Discogs API calls. Only Flask route latency is measured; "
            "there is no network hop to a deployed API.",
            "",
        ]
    )
    return "\n".join(lines)


def write_summary(summary):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary_file:
            summary_file.write(summary)
    print(summary)


def validate_request(client, artist, title, entry_id):
    started = time.perf_counter()
    response = client.post(
        "/discogs/validate",
        json={"entries": [{"id": entry_id, "artist": artist, "title": title}]},
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    payload = response.get_json(silent=True)
    if response.status_code != 200:
        return elapsed_ms, None, f"HTTP {response.status_code}"
    validations = (payload or {}).get("validations")
    if not isinstance(validations, list) or len(validations) != 1:
        return elapsed_ms, None, "validation response did not contain exactly one result"
    result = validations[0]
    if result.get("status") != "valid" or not result.get("release_id"):
        return elapsed_ms, result, (
            "expected a valid Discogs match, received "
            f"{result.get('status', 'no status')}"
        )
    return elapsed_ms, result, None


def reset_probe_state(
    supabase,
    redis_conn,
    normalized_key,
    expected_release_id,
    cleanup_keys,
    pending_index_key,
):
    rows = (
        supabase.table("albums")
        .select("discogs_release_id")
        .eq("normalized_key", normalized_key)
        .execute()
    )
    existing_rows = getattr(rows, "data", None) or []
    if len(existing_rows) != 1 or int(
        existing_rows[0].get("discogs_release_id") or 0
    ) != expected_release_id:
        raise RuntimeError(
            f"Probe {normalized_key} changed unexpectedly; refusing to reset it"
        )

    supabase.table("albums").delete().eq(
        "normalized_key", normalized_key
    ).eq("discogs_release_id", expected_release_id).execute()

    remaining_rows = (
        supabase.table("albums")
        .select("normalized_key")
        .eq("normalized_key", normalized_key)
        .execute()
    )
    if getattr(remaining_rows, "data", None):
        raise RuntimeError(f"Could not clear the previous probe row for {normalized_key}")

    pending_key, result_key = (
        cleanup_keys[0](normalized_key),
        cleanup_keys[1](normalized_key),
    )
    redis_conn.delete(pending_key, result_key)
    redis_conn.zrem(pending_index_key, pending_key)
    if redis_conn.exists(pending_key, result_key):
        raise RuntimeError(f"Could not clear Redis lookup state for {normalized_key}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--miss-iterations",
        type=int,
        default=4,
        help="Cold cache-miss requests per album (1-4; default: 4)",
    )
    parser.add_argument(
        "--hit-iterations",
        type=int,
        default=10,
        help="Warm cache-hit requests per album (1-10; default: 10)",
    )
    args = parser.parse_args()

    samples = {"cache-miss": [], "cache-hit": []}
    errors = {"cache-miss": 0, "cache-hit": 0}
    failures = []
    worker_count = "unknown"
    api_calls = 0
    api_429s = 0
    exit_code = 1
    safe_keys = []
    auth_session_id = None
    redis_conn = None
    supabase = None
    cleanup_keys = None
    pending_index_key = None
    safe_to_cleanup = False
    get_discogs_call_metrics = None
    calls_before = None

    if not 1 <= args.miss_iterations <= 4:
        failures.append("--miss-iterations must be between 1 and 4")
    if not 1 <= args.hit_iterations <= 10:
        failures.append("--hit-iterations must be between 1 and 10")
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        failures.append("Missing required environment values: " + ", ".join(missing))
    if os.environ.get("SPINESCAN_BENCHMARK_ALLOW_DATABASE_WRITES") != (
        "dedicated-benchmark-project"
    ):
        failures.append(
            "Set SPINESCAN_BENCHMARK_ALLOW_DATABASE_WRITES to "
            "'dedicated-benchmark-project' only for a dedicated Supabase project"
        )
    if os.environ.get("UPSTASH_REDIS_URL"):
        failures.append("UPSTASH_REDIS_URL must be unset; this run requires local Redis")
    if os.environ.get("REDIS_URL", "redis://localhost:6379/0") not in {
        "redis://localhost:6379/0",
        "redis://127.0.0.1:6379/0",
    }:
        failures.append("REDIS_URL must point to the ephemeral local Redis service")

    if not failures:
        os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_urlsafe(32))
        os.environ["REDIS_URL"] = "redis://localhost:6379/0"
        os.environ["DISCOGS_SYNC_LOOKUP_ENABLED"] = "true"
        os.environ["DISCOGS_LOOKUP_MAX_CALLS_PER_ALBUM"] = "3"
        os.environ["DISCOGS_LOOKUP_MAX_QUERY_STRATEGIES"] = "2"
        os.environ["DISCOGS_LOOKUP_MAX_PAGES_PER_QUERY"] = "1"
        os.environ["DISCOGS_MAX_RETRIES"] = "2"
        sys.path.insert(0, str(BACKEND_DIR))

        try:
            from flask import session as flask_session
            from app_factory import create_app
            from extensions import redis_conn as backend_redis, supabase as backend_supabase
            from services.discogs_service import (
                album_lookup_normalized_key,
                album_lookup_pending_key,
                album_lookup_result_key,
                get_discogs_call_metrics,
                get_discogs_client,
                get_discogs_identity,
                get_lookup_breaker_state,
                get_lookup_queue_stats,
                pending_lookup_index_key,
                persist_discogs_auth_tokens,
            )

            redis_conn = backend_redis
            supabase = backend_supabase
            cleanup_keys = (
                album_lookup_pending_key,
                album_lookup_result_key,
            )
            pending_index_key = pending_lookup_index_key()

            if not redis_conn.ping():
                raise RuntimeError("The ephemeral Redis service did not respond to PING")

            keys_by_album = {
                album_lookup_normalized_key(artist, title): (artist, title)
                for artist, title in DEFAULT_ALBUMS
            }
            if len(keys_by_album) != len(DEFAULT_ALBUMS):
                raise RuntimeError("Benchmark album names must normalize to distinct keys")
            safe_keys = list(keys_by_album)

            existing_rows = (
                supabase.table("albums")
                .select("normalized_key")
                .in_("normalized_key", safe_keys)
                .execute()
            )
            if getattr(existing_rows, "data", None):
                existing = ", ".join(
                    row.get("normalized_key", "unknown") for row in existing_rows.data
                )
                raise RuntimeError(
                    "Probe albums already exist in Supabase; refusing to overwrite "
                    f"or clean pre-existing rows: {existing}"
                )

            for key in safe_keys:
                pending_key, result_key = cleanup_keys[0](key), cleanup_keys[1](key)
                if redis_conn.exists(pending_key, result_key):
                    raise RuntimeError(
                        f"Probe {key} has existing Redis lookup state; refusing to overwrite it"
                    )

            breaker_open, breaker_reason = get_lookup_breaker_state()
            if breaker_open:
                raise RuntimeError(
                    f"Lookup breaker is already open ({breaker_reason}); refusing benchmark"
                )
            safe_to_cleanup = True

            app = create_app()
            app.config.update(TESTING=True)
            with app.test_client() as client:
                with app.test_request_context():
                    try:
                        persist_discogs_auth_tokens(
                            os.environ["DISCOGS_BENCHMARK_ACCESS_TOKEN"],
                            os.environ["DISCOGS_BENCHMARK_ACCESS_TOKEN_SECRET"],
                            os.environ["DISCOGS_BENCHMARK_USERNAME"],
                        )
                    finally:
                        auth_session_id = flask_session.get("auth_session_id")
                    if not auth_session_id:
                        raise RuntimeError("Could not establish the benchmark auth session")
                    calls_before = get_discogs_call_metrics()
                    identity = get_discogs_identity(get_discogs_client())
                    actual_username = str(getattr(identity, "username", "")).casefold()
                    expected_username = os.environ[
                        "DISCOGS_BENCHMARK_USERNAME"
                    ].casefold()
                    if actual_username != expected_username:
                        raise RuntimeError(
                            "Discogs access token username does not match "
                            "DISCOGS_BENCHMARK_USERNAME"
                        )
                    client_session_data = dict(flask_session)
                with client.session_transaction() as client_session:
                    client_session.update(client_session_data)

                queue_stats = get_lookup_queue_stats()
                worker_count = int(queue_stats.get("workers_online", -1))
                if worker_count != 0:
                    raise RuntimeError(
                        "Expected zero RQ workers for the sync-fallback benchmark; "
                        f"found {worker_count}"
                    )

                cold_results = {}
                stop_cold_samples = False
                for miss_index in range(1, args.miss_iterations + 1):
                    for album_index, (artist, title) in enumerate(
                        DEFAULT_ALBUMS, start=1
                    ):
                        key = album_lookup_normalized_key(artist, title)
                        before_metrics = get_discogs_call_metrics()
                        elapsed, result, error = validate_request(
                            client,
                            artist,
                            title,
                            f"cold-{miss_index}-{album_index}",
                        )
                        samples["cache-miss"].append(elapsed)
                        after = get_discogs_call_metrics()
                        if (
                            after["rate_limited_429_total"]
                            > before_metrics["rate_limited_429_total"]
                        ):
                            errors["cache-miss"] += 1
                            failures.append(
                                f"cache-miss {artist} / {title}: Discogs returned HTTP 429; stopping live requests"
                            )
                            stop_cold_samples = True
                            break
                        if error:
                            errors["cache-miss"] += 1
                            failures.append(f"cache-miss {artist} / {title}: {error}")
                            stop_cold_samples = True
                            break
                        if after["calls_total"] <= before_metrics["calls_total"]:
                            errors["cache-miss"] += 1
                            failures.append(
                                f"cache-miss {artist} / {title}: no live Discogs API call was recorded"
                            )
                            stop_cold_samples = True
                            break
                        cold_results[key] = result

                        if miss_index < args.miss_iterations:
                            reset_probe_state(
                                supabase,
                                redis_conn,
                                key,
                                int(result["release_id"]),
                                cleanup_keys,
                                pending_index_key,
                            )
                    if stop_cold_samples:
                        break

                api_calls = get_discogs_call_metrics()["calls_total"] - calls_before["calls_total"]
                api_429s = (
                    get_discogs_call_metrics()["rate_limited_429_total"]
                    - calls_before["rate_limited_429_total"]
                )

                if len(cold_results) == len(DEFAULT_ALBUMS) and not failures:
                    persisted_rows = (
                        supabase.table("albums")
                        .select("normalized_key, discogs_release_id")
                        .in_("normalized_key", list(cold_results))
                        .execute()
                    )
                    persisted_by_key = {
                        row["normalized_key"]: row
                        for row in (getattr(persisted_rows, "data", None) or [])
                    }
                    stop_hit_samples = False
                    for key, cold_result in cold_results.items():
                        if stop_hit_samples:
                            break
                        row = persisted_by_key.get(key)
                        if (
                            not row
                            or int(row.get("discogs_release_id") or 0)
                            != int(cold_result["release_id"])
                        ):
                            errors["cache-hit"] += 1
                            failures.append(
                                f"cache-hit {key}: cold result was not persisted to the durable albums table"
                            )
                            continue

                        artist, title = keys_by_album[key]
                        for hit_index in range(1, args.hit_iterations + 1):
                            before_metrics = get_discogs_call_metrics()
                            elapsed, hit_result, error = validate_request(
                                client,
                                artist,
                                title,
                                f"hit-{key}-{hit_index}",
                            )
                            samples["cache-hit"].append(elapsed)
                            after = get_discogs_call_metrics()
                            if (
                                after["rate_limited_429_total"]
                                > before_metrics["rate_limited_429_total"]
                            ):
                                error = (
                                    "Discogs returned HTTP 429 during a cache hit; "
                                    "stopping live requests"
                                )
                                stop_hit_samples = True
                            if (
                                not error
                                and int(hit_result["release_id"])
                                != int(cold_result["release_id"])
                            ):
                                error = "cache hit returned a different release ID"
                            if (
                                not error
                                and after["calls_total"] != before_metrics["calls_total"]
                            ):
                                error = (
                                    "cache hit unexpectedly called Discogs; "
                                    "stopping warm-hit requests"
                                )
                                stop_hit_samples = True
                            if error:
                                errors["cache-hit"] += 1
                                failures.append(f"cache-hit {artist} / {title}: {error}")
                                if stop_hit_samples:
                                    break
                        if stop_hit_samples:
                            break
        except Exception as error:
            failures.append(f"Benchmark setup/run failed: {error}")
        finally:
            if get_discogs_call_metrics is not None and calls_before is not None:
                try:
                    final_metrics = get_discogs_call_metrics()
                    api_calls = final_metrics["calls_total"] - calls_before["calls_total"]
                    api_429s = (
                        final_metrics["rate_limited_429_total"]
                        - calls_before["rate_limited_429_total"]
                    )
                except Exception as error:
                    failures.append(f"Could not read Discogs API metrics: {error}")
            cleanup_errors = []
            if supabase is not None and safe_to_cleanup:
                for key in safe_keys:
                    try:
                        supabase.table("albums").delete().eq(
                            "normalized_key", key
                        ).execute()
                    except Exception as error:
                        cleanup_errors.append(
                            f"Supabase cleanup failed for probe {key}: {error}"
                        )
            if redis_conn is not None and cleanup_keys is not None and safe_to_cleanup:
                for key in safe_keys:
                    try:
                        redis_conn.delete(
                            cleanup_keys[0](key),
                            cleanup_keys[1](key),
                        )
                        redis_conn.zrem(pending_index_key, cleanup_keys[0](key))
                    except Exception as error:
                        cleanup_errors.append(
                            f"Redis lookup cleanup failed for probe {key}: {error}"
                        )
                if auth_session_id:
                    try:
                        redis_conn.delete(
                            f"discogs:auth-session:v1:{auth_session_id}"
                        )
                    except Exception as error:
                        cleanup_errors.append(
                            f"Redis auth-session cleanup failed: {error}"
                        )
            failures.extend(cleanup_errors)

    summary = render_summary(
        samples,
        errors,
        failures,
        worker_count,
        api_calls,
        api_429s,
    )
    write_summary(summary)
    if not failures and len(samples["cache-miss"]) == (
        len(DEFAULT_ALBUMS) * args.miss_iterations
    ) and (
        len(samples["cache-hit"]) == len(DEFAULT_ALBUMS) * args.hit_iterations
    ):
        exit_code = 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
