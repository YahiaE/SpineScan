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
3. Check the `albums` Postgres table in Supabase (durable lookup cache).
4. Queue a Discogs lookup job on a miss instead of calling Discogs in the request.
5. Let the worker perform the rate-limited Discogs search.
6. Persist the result back to Supabase and clear Redis pending markers.

Start the API and worker separately during development:

```powershell
python main.py
python worker.py
```

## Collection membership cache flow

Before importing albums, the backend refreshes the collection cache from Discogs:

1. **User selects import folder**
   - Backend calls `refresh_collection_cache_from_discogs()` to fetch latest Discogs state
   - Releases and album keys are persisted directly to Supabase `discogs_collection_cache` table
   - Albums are mirrored to `albums` lookup table for fast duplicate detection

2. **Import duplicate checks** (via Supabase only, no Redis involved)
   - `is_release_in_collection_cache()` queries Supabase for release ID membership
   - `is_album_in_collection_cache()` queries Supabase for album key membership
   - When duplicate detected, entry is skipped with "already exists" message

3. **After successful add or duplicate detection**
   - `cache_collection_membership_entry()` updates Supabase immediately
   - Albums lookup table is also updated for consistency
   - No Redis caching layer

**Benefits of Supabase-only design:**
- **Accuracy**: Collection state is always current across sessions and instances
- **Memory efficient**: Redis is freed from collection membership sets
- **Consistency**: Single source of truth (Supabase), no marker tracking
- **Scalability**: Can be queried from multiple workers without coordination
- **Durability**: Collection membership persists indefinitely, not subject to TTL

## Discogs lookup tuning

Lookup misses can fan out into multiple Discogs calls. The backend now supports
budget and early-exit controls to keep throughput predictable under shared
rate limits.

Set these environment variables in backend env when needed:

- `DISCOGS_LOOKUP_MAX_CALLS_PER_ALBUM` (default: `6`)
	Hard cap for Discogs calls used by one album lookup.
- `DISCOGS_LOOKUP_BATCH_SIZE` (default: `4`)
	Maximum cache-miss albums grouped into one RQ job. Keep batches bounded so a slow lookup does not hold many entries behind it.
- `DISCOGS_LOOKUP_MAX_QUERY_STRATEGIES` (default: `3`)
	Maximum query templates tried per lookup.
- `DISCOGS_LOOKUP_MAX_PAGES_PER_QUERY` (default: `1`)
	Maximum pages fetched for each query strategy.
- `DISCOGS_LOOKUP_EARLY_ACCEPT_SCORE` (default: `0.90`)
	Accept a strong exact-title candidate early and stop searching.

Recommended starting values for production load:

```env
DISCOGS_LOOKUP_MAX_CALLS_PER_ALBUM=5
DISCOGS_LOOKUP_BATCH_SIZE=4
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

## Production env checklist

For Render or any production deployment, set these backend env vars explicitly:

```env
CORS_ORIGINS=https://your-frontend-origin.example
CSRF_ORIGIN_ENFORCEMENT=true
CSRF_TRUSTED_ORIGINS=https://your-frontend-origin.example
REDIS_URL=redis://<your-redis-host>:6379
OPS_API_KEY=replace-with-strong-random-secret
CAPTURE_SIGNATURE_SECRET=replace-with-different-strong-random-secret
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=None
DISCOGS_SYNC_LOOKUP_ENABLED=false
DISCOGS_LOOKUP_MAX_QUEUE_DEPTH=50
DISCOGS_LOOKUP_MAX_STARTED_JOBS=10
VALIDATE_MAX_ENTRIES=20
VALIDATE_SYNC_BUDGET=3
IMPORT_MAX_ENTRIES=20
VALIDATE_REQUESTS_PER_WINDOW=12
IMPORT_REQUESTS_PER_WINDOW=6
```

Notes:

- `CORS_ORIGINS` is now read from env and supports comma-separated values.
- `CSRF_TRUSTED_ORIGINS` is also comma-separated and should usually match your frontend origin list.
- `REDIS_URL` takes precedence over `REDIS_HOST` and `REDIS_PORT`.
- Keep `SESSION_COOKIE_SECURE=true` in production.
- Use `SESSION_COOKIE_SAMESITE=None` when frontend/backend are on different domains (for example Vercel + Render).
- `DISCOGS_SYNC_LOOKUP_ENABLED=false` keeps expensive lookups off the web request path.
- `VALIDATE_SYNC_BUDGET` runs only the first N entries in-request, then overflows remaining entries to the worker queue.
- Lower queue/start limits are intentional for one Fly worker and one Render web service.
- `VALIDATE_MAX_ENTRIES` and `IMPORT_MAX_ENTRIES` cap per-request batch size.
- `VALIDATE_REQUESTS_PER_WINDOW` and `IMPORT_REQUESTS_PER_WINDOW` cap per-user request volume inside a 60-second window.
