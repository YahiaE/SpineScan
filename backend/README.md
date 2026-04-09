# SpineScan

SpineScan uses OCR and music metadata APIs to identify physical CDs from spine or cover photos and import them into a Discogs collection.

## Backend architecture

The backend is organized as a small Flask app with an app factory, route
blueprints, and service modules:

- `main.py`
	Thin entrypoint used for local startup. It creates the app and keeps
	`run_album_lookup_job` importable for RQ workers.
- `app_factory.py`
	Builds the Flask app instance, applies CORS/session config, and registers
	blueprints.
- `config.py`
	Centralized environment settings and defaults.
- `extensions.py`
	Shared clients and connections (Supabase, Redis, RQ queue).
- `routes/auth_routes.py`
	Discogs OAuth flow routes (`/auth/*`).
- `routes/data_routes.py`
	Image upload/scan/process routes and `/data/albums`.
- `routes/discogs_routes.py`
	Validation/import/folder routes and worker status (`/discogs/*`).
- `services/discogs_service.py`
	Discogs API client logic, rate limiting, matching/scoring, Redis/Supabase
	lookup pipeline, and import helpers.
- `services/storage_service.py`
	Supabase Storage bucket upload/download/delete helpers and temp-file OCR
	bridge.
- `worker.py`
	RQ worker process for the `discogs-lookups` queue.

Request flow in short:

1. Route receives request and validates payload/auth.
2. Route calls service layer for business logic.
3. Services use shared clients from `extensions.py`.
4. Responses are returned by route handlers.

## Discogs lookup cache flow

Album validation now uses a cache-first flow to reduce Discogs API traffic:

1. Normalize the artist and album into a stable lookup key.
2. Check Redis for a cached validation result.
3. Check the `albums` Postgres table in Supabase.
4. Queue a Discogs lookup job on a miss instead of calling Discogs in the request.
5. Let the worker perform the rate-limited Discogs search.
6. Persist the result back to Supabase and Redis.

Start the API and worker separately during development:

```powershell
python main.py
python worker.py
```

## Discogs lookup tuning

Lookup misses can fan out into multiple Discogs calls. The backend now supports
budget and early-exit controls to keep throughput predictable under shared
rate limits.

Set these environment variables in backend env when needed:

- `DISCOGS_LOOKUP_MAX_CALLS_PER_ALBUM` (default: `6`)
	Hard cap for Discogs calls used by one album lookup.
- `DISCOGS_LOOKUP_MAX_QUERY_STRATEGIES` (default: `3`)
	Maximum query templates tried per lookup.
- `DISCOGS_LOOKUP_MAX_PAGES_PER_QUERY` (default: `1`)
	Maximum pages fetched for each query strategy.
- `DISCOGS_LOOKUP_EARLY_ACCEPT_SCORE` (default: `0.90`)
	Accept a strong exact-title candidate early and stop searching.

Recommended starting values for production load:

```env
DISCOGS_LOOKUP_MAX_CALLS_PER_ALBUM=5
DISCOGS_LOOKUP_MAX_QUERY_STRATEGIES=2
DISCOGS_LOOKUP_MAX_PAGES_PER_QUERY=1
DISCOGS_LOOKUP_EARLY_ACCEPT_SCORE=0.90
```

## Capture ownership verification

Image captures are stored in Supabase Storage and linked to a signed manifest
row in Postgres. The backend verifies this signature before OCR runs.

Setup steps:

1. Run the capture table SQL in Supabase SQL editor:

```sql
-- file: backend/sql/captures.sql
```

2. Set capture signature secret in backend env:

```env
CAPTURE_SIGNATURE_SECRET=replace-with-strong-random-secret
```

Behavior summary:

- Upload creates a bucket object and inserts a `captures` row with:
	`user_scope`, `object_key`, `checksum_sha256`, `signature`, `status`.
- Scan/process endpoints verify that the capture belongs to the current user
	scope and that signature matches before processing.
- After successful process, capture status is updated to `processed` or
	`deleted` depending on `DELETE_CAPTURE_AFTER_PROCESS`.

## Monitoring setup

The backend now exposes operations endpoints for uptime checks and metrics:

- `GET /healthz`
	Liveness probe. Returns `200` when the process is running.
- `GET /readyz`
	Readiness probe. Returns `200` only when Redis and Supabase checks pass,
	otherwise returns `503` with check details.
- `GET /metrics`
	Prometheus-compatible metrics output (`text/plain; version=0.0.4`).

Key metrics exported:

- `spinescan_http_requests_total`
- `spinescan_http_errors_5xx_total`
- `spinescan_http_request_duration_seconds_p95`
- `spinescan_discogs_api_calls_total`
- `spinescan_discogs_api_429_total`
- `spinescan_discogs_api_latency_p95_seconds`
- `spinescan_lookup_workers_online`
- `spinescan_lookup_queue_depth`
- `spinescan_lookup_started_jobs`
- `spinescan_lookup_breaker_open`

Prometheus scrape example:

```yaml
scrape_configs:
  - job_name: "spinescan-backend"
    metrics_path: /metrics
    static_configs:
      - targets: ["192.168.1.146:5000"]
```

Recommended initial alerts:

- backend down for 2 minutes (`/healthz` failing)
- readiness degraded for 2 minutes (`/readyz` returns `503`)
- HTTP 5xx spike
- p95 request latency spike
- lookup workers online equals `0` for 5 minutes
- lookup queue depth above threshold for 10 minutes
- Discogs 429 spike or lookup breaker open for 10 minutes

## Frontend runtime monitoring

Frontend runtime errors can be captured with Sentry. Configure in frontend env:

```env
VITE_SENTRY_DSN=https://examplePublicKey@o0.ingest.sentry.io/0
VITE_SENTRY_TRACES_SAMPLE_RATE=0.1
VITE_RELEASE=spinescan@local
```

When `VITE_SENTRY_DSN` is unset, Sentry initialization is skipped.
