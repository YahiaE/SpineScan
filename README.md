# SpineScan

SpineScan is a CD collection assistant that turns shelf photos into structured albums and helps import them into Discogs.

## Workflow

<img width="3155" height="525" alt="mermaid-diagram" src="https://github.com/user-attachments/assets/ec63a61e-8855-4ed0-8db1-aac9c14a4dde" />

SpineScan runs as a staged pipeline so users can review and correct results before writing to Discogs.

1. Discogs auth
- The frontend starts the OAuth handshake with `GET /api/auth/request_token`.
- The backend stores request-token scratch state in Redis and durable user auth in the Flask session after token exchange.

2. Capture and upload
- The user captures a photo in the React app and uploads it to `POST /api/data/upload`.
- The backend stores the bytes in Supabase Storage and inserts a signed `captures` manifest row for ownership verification.

3. OCR and parsing
- `GET /api/process/latest` resolves the latest signed capture, verifies ownership, downloads it from Supabase Storage, and runs Gemini-based OCR.
- The frontend parses OCR output into `Artist - Album` entries and initializes each with pending validation state.

4. Validation and matching
- Each candidate is validated through `POST /api/discogs/validate`.
- Lookup resolution is durable-cache-first:
	- Supabase `albums` table for durable shared matches.
	- Redis is used for pending markers and queue/rate-limit coordination, not hot album result cache.
	- RQ background job for cache misses when workers are online.
	- Synchronous fallback lookup when workers are offline and sync fallback is enabled.
- Matching applies normalization, similarity scoring, rate limiting, queue saturation checks, and a breaker before marking valid, invalid, or pending.

5. Review and import
- The frontend shows editable entries, loads Discogs collection folders, and only allows fully valid albums to proceed.
- `POST /api/discogs/import` applies import idempotency, folder warm-up, and duplicate detection by both release ID and logical album identity before adding releases.

6. Cleanup and history
- Uploaded capture images are finalized and deleted once processing is no longer needed.
- Import results are persisted in the Supabase `imports` table and surfaced in Home and History, with local in-memory history kept as a fallback.

## Architecture

SpineScan uses a split frontend/backend architecture with async workers, Redis caches, and Supabase persistence.

- Frontend
	- React + Vite application for capture, review, and import flows.
	- Calls backend API with authenticated session cookies via `apiFetch`.
	- Keeps transient workflow state in a single React context store.

- Backend API
	- Flask app composed via an app factory and route blueprints.
	- Auth routes manage Discogs OAuth handshake and token exchange.
	- Data routes handle capture upload, OCR processing, and album extraction.
	- Discogs routes handle import history, folder listing, validation, and import.

- Services layer
	- Discogs service encapsulates search, rate limiting, matching, and queue/cache orchestration.
	- Storage service encapsulates Supabase Storage upload/download/delete and capture signature verification.
	- Import history service persists and reads durable import summaries.

- Data and queue components
	- Redis (Upstash-compatible): transient rate-limit buckets, pending lookup markers, and lookup circuit-breaker flags (no collection state).
	- RQ workers: async Discogs lookup jobs for cache misses.
	- Supabase Postgres: persisted capture manifests, collection membership cache (per-user per-folder), album lookup data, and import history.
	- Supabase Storage: uploaded capture images.

## Repository layout

- [frontend](frontend): React app.
- [backend](backend): Flask API, services, routes, worker.
- [backend/sql/captures.sql](backend/sql/captures.sql): capture manifest table migration.
- [backend/sql/discogs_collection_cache.sql](backend/sql/discogs_collection_cache.sql): durable per-folder Discogs membership cache.
- [backend/sql/imports.sql](backend/sql/imports.sql): durable import history table.

The project includes a React frontend and a Flask backend with Redis, RQ workers, Supabase, and Discogs OAuth.

## Frontend validation polling

The frontend polls the backend to check validation status after submitting albums for review. The polling strategy uses **adaptive exponential backoff with jitter**:

- Starts at 1 second interval
- Multiplies interval by 1.5x per attempt (exponential backoff)
- Capped at 10 seconds maximum
- Adds 10% random jitter to prevent thundering herd when multiple clients poll simultaneously
- Maximum 20 attempts (~50-80 seconds total timeout)

This approach reduces unnecessary backend and Redis load while maintaining responsive UX for typical validation times (usually 2-10 seconds per batch).

### Known limitations

**Polling is request-based, not event-driven.** Current implementation relies on frontend polling rather than server-sent events (SSE) or WebSocket. Under high concurrent load (many simultaneous users validating), this creates predictable but unnecessary backend activity. 

**Future improvements:**
- Implement Server-Sent Events (SSE) for push-based validation status updates
- Add WebSocket alternative for full-duplex communication
- These would eliminate polling overhead entirely and provide real-time feedback

For single-user or low-concurrency scenarios, current polling is sufficient and avoids operational complexity of managing persistent connections.




