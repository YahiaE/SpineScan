## System Map

SpineScan is a split React + Flask app with a staged pipeline.

1. The frontend handles navigation, camera capture, review, confirmation, import progress, and history in `frontend/src/app/routes.tsx`, `frontend/src/app/store.tsx`, and the pages under `frontend/src/app/pages`.
2. The backend is a Flask app assembled in `backend/app_factory.py` and started from `backend/main.py`.
3. Discogs OAuth and collection writes are handled by `backend/routes/auth_routes.py` and `backend/routes/discogs_routes.py`.
4. Capture upload, manifest tracking, OCR processing, and cleanup are handled by `backend/routes/data_routes.py` plus `backend/services/storage_service.py`.
5. Redis is used for hot caches, rate limiting, import idempotency, and lookup queue coordination through `backend/extensions.py` and `backend/services/discogs_service.py`.
6. Supabase is used in two ways: Storage for raw captures, and Postgres tables for durable capture metadata, durable collection-cache rows, and durable import history. The repo-tracked schemas are `backend/sql/captures.sql`, `backend/sql/discogs_collection_cache.sql`, and `backend/sql/imports.sql`.
7. Background Discogs lookup jobs run through RQ workers started from `backend/worker.py`.

## Frontend Runtime Flow

1. Vite boots the React app from `frontend/src/main.tsx`, and dev requests to `/api` are proxied to Flask by `frontend/vite.config.ts`.
2. The app is wrapped in a single context provider in `frontend/src/app/App.tsx` and `frontend/src/app/store.tsx`. That store holds transient app state:
	- `isConnected`
	- `scannedAlbums`
	- `capturedImage`
	- `collectionFolders`
	- `selectedCollectionId`
	- `lastImportSummary`
	- in-memory `scanHistory`
3. The route graph in `frontend/src/app/routes.tsx` is:
	- `/` Welcome
	- `/home`
	- `/scan`
	- `/processing`
	- `/review`
	- `/confirm`
	- `/importing`
	- `/success`
	- `/history`
4. The shell layout in `frontend/src/app/components/ui/Layout.tsx` provides the shared header and back-button logic. Navigating back from `/review`, `/confirm`, or `/importing` also does best-effort capture cleanup before returning home.
5. `apiFetch` in `frontend/src/app/apiClient.ts` always sends `credentials: "include"` so the browser carries the Flask session cookie. It can also attach a Supabase bearer token if one exists in `localStorage`, but the primary live flow uses the Flask session.

## End-to-End User Workflow

### 1. Welcome and Discogs OAuth

1. The user lands on `Welcome.tsx`.
2. Clicking Connect Discogs Account calls `GET /api/auth/request_token`.
3. `backend/routes/auth_routes.py` creates a Discogs OAuth client, rate-limits the request with `call_discogs`, gets a request token and authorization URL, stores the request token metadata in Redis, and also stores the request token in the Flask session.
4. The frontend opens Discogs in a popup.
5. Discogs redirects back to `/auth/callback`, which writes the `oauth_verifier` into Redis keyed by the request token.
6. When the user clicks I've Authorized, the frontend polls `GET /api/auth/access_token?oauth_token=...` with retry-on-`409` behavior.
7. The backend exchanges the request token for an access token, fetches Discogs identity, and stores these values in the Flask session:
	- `access_token`
	- `access_token_secret`
	- `discogs_username`
8. On success the frontend marks the app connected in memory and navigates to `/home`.

### 2. Home and Session State

1. `Home.tsx` is the dashboard entry point.
2. The frontend still keeps a local in-memory `scanHistory` list in `store.tsx`.
3. The current UI prefers durable import history from `GET /api/discogs/import-history` and falls back to the in-memory history only if the backend history is empty or unavailable.
4. Restarting the frontend clears the local fallback history, but durable import history remains available when backend persistence succeeded.

### 3. Camera Capture

1. `Scan.tsx` requests camera access with `getUserMedia`.
2. The user captures a frame, which is drawn to a canvas and converted into a JPEG blob.
3. On Use Photo, the frontend uploads the blob to `POST /api/data/upload` as multipart form data.
4. `backend/routes/data_routes.py`:
	- requires a valid Discogs-authenticated Flask session
	- derives a stable `user_scope` using `backend/services/storage_service.py`
	- builds a deterministic object key from scope, timestamp, and content hash
	- computes a checksum
	- signs ownership metadata with HMAC
	- uploads bytes to Supabase Storage
	- verifies the uploaded bytes by downloading them back and re-checking the checksum
	- inserts a row into the `captures` table with status `uploaded`
5. The frontend stores the returned bucket path in `capturedImage` and navigates to `/processing`.

### 4. OCR Processing

1. `Processing.tsx` calls `GET /api/process/latest?path=...`.
2. `backend/routes/data_routes.py`:
	- resolves the most relevant capture from the manifest, with support for both username-based and token-based capture scope seeds
	- verifies the capture signature before reading bytes
	- downloads the image from Supabase Storage
	- writes it to a temp file
	- invokes `process_image_main`
3. The active OCR implementation is `backend/ocr_functions/process_image.py`. It currently reads the image bytes and sends them to Gemini, prompting for verified `Artist - Album` lines.
4. `backend/ocr_functions/preprocessing.py` exists, but it is not part of the current live request path.
5. If OCR returns usable text, the frontend parses lines containing `" - "`, rejects obvious prose lines, and initializes each album with `validation.status = "pending"`.
6. If OCR returns no text or no parseable `Artist - Album` lines:
	- the frontend calls `POST /api/data/capture/finalize`
	- the backend deletes the capture from Storage and removes its manifest rows
	- the frontend shows an error state
	- clicking Try again clears `capturedImage` before routing back to `/scan`
7. If processing succeeds, the frontend navigates to `/review`.

### 5. Review and Validation

1. `Review.tsx` loads the user's Discogs collection folders with `GET /api/discogs/collection-folders`.
2. `backend/routes/discogs_routes.py` creates an authenticated Discogs client from the Flask session and fetches the user's folders.
3. The user can:
	- edit artist/title text
	- remove bad rows
	- manually add missing rows
	- select the target Discogs folder
4. Validation is triggered with `POST /api/discogs/validate`.
5. For each entry, the backend calls `resolve_release_match` from `backend/services/discogs_service.py`.
6. `resolve_release_match` is a cache-first pipeline:
	- check Redis for a cached validation result
	- if missing, check Supabase `albums` for a durable cached match
	- if a lookup is already pending and a worker is online, return `pending`
	- if missing and a worker is available, enqueue an RQ job and return `pending`
	- if missing and no worker is available, do a synchronous fallback lookup when enabled
	- if the lookup breaker is open or the queue is saturated, return a degraded pending response instead of hammering Discogs
7. The frontend writes returned validation data back into `scannedAlbums`, including:
	- `valid` / `invalid` / `pending`
	- `releaseId`
	- matched artist/title
	- explanation message
8. Review also has a background revalidation loop: if some entries stay pending and already have a validation message, it retries after a short delay.

### 6. Discogs Lookup Internals

1. Text normalization and matching are in `backend/services/discogs_service.py`.
2. The service normalizes artist/title aggressively:
	- removes accents
	- lowercases
	- strips punctuation noise
	- collapses whitespace
	- strips common version suffixes from titles
	- derives canonical album keys with no spaces
3. A logical album identity is built with `album_identity_key`, which is used both for validation cache keys and duplicate detection.
4. A Redis-backed token-bucket limiter wraps all Discogs API calls through `call_discogs`.
5. Paginated Discogs reads go through `iter_discogs_paginated_items` so each page fetch consumes rate-limit budget.
6. The worker entrypoint `run_album_lookup_job` executes a public Discogs lookup and persists the result.
7. Persisted validation results are stored in the shared `albums` table:
	- valid results are upserted with normalized key and release ID
	- invalid results are not kept as durable rows; instead the durable row is deleted and Redis gets a shorter-lived invalid cache entry
8. This means validation speeds up over time across users because album matches become shared durable cache entries.

### 7. Confirm and Import

1. `Confirm.tsx` is a UX checkpoint.
2. Only fully valid albums are eligible for import.
3. Clicking confirm routes to `/importing`.

### 8. Import Execution

1. `Importing.tsx` starts exactly once using a ref guard to prevent duplicate `POST /discogs/import` calls from React effect re-runs.
2. Before the Discogs import starts, it sends a best-effort `POST /api/data/capture/finalize` to delete the uploaded image and then clears `capturedImage` locally.
3. The actual import request is `POST /api/discogs/import` with:
	- target `folder_id`
	- each album's `artist`
	- `title`
	- validated `release_id`
4. `backend/routes/discogs_routes.py` protects this route with two idempotency layers:
	- a Redis result cache keyed by a stable import fingerprint
	- a Redis lock keyed by the same fingerprint
5. If an identical import is already running, a second request waits briefly for the cached result, then returns `409` if still in progress.
6. Once inside the import loop, the backend first warms the selected folder's collection-membership cache with `ensure_collection_membership_cache_warm`.
7. That warm step:
	- fetches up to `DISCOGS_COLLECTION_WARM_MAX_PAGES` from the Discogs folder
	- writes release IDs and album keys into Redis sets
	- persists durable rows into `discogs_collection_cache`
	- mirrors those rows into the shared `albums` table
8. Each candidate import entry then goes through duplicate guards in this order:
	- resolve missing `release_id` if needed
	- reject invalid or unresolved entries
	- skip if the release ID already exists in the current batch
	- skip if the release ID already exists in the cached Discogs folder membership
	- skip if the logical album key already exists in the current batch
	- skip if the logical album key already exists in the cached folder membership
	- otherwise call Discogs to add the release
9. If Discogs itself reports a duplicate error, the backend treats it as `skipped` and writes the membership cache so future imports can bypass the API call.
10. Every successful add or duplicate discovery is written through to:
	- Redis collection cache
	- durable `discogs_collection_cache`
	- shared `albums` mirror
11. The API returns `added_count`, `skipped_count`, `failed_count`, and per-entry results.
12. The backend also persists a durable import-history row in the `imports` table when the request completes.

### 9. Success and History

1. `Importing.tsx` stores the summary in `lastImportSummary`.
2. It also appends a local history entry to the in-memory store as a fallback view model.
3. If all entries succeed or skip cleanly, the UI auto-navigates to `/success`.
4. `Success.tsx` reads `lastImportSummary` and shows the final added and skipped totals.
5. Scan more CDs resets scanned albums and routes back to `/scan`.
6. Back to Home resets the selected folder and summary and routes to `/home`.
7. `History.tsx` now prefers the backend `imports` table through `GET /api/discogs/import-history`, and falls back to the local in-memory history only when durable history is absent.

## Backend Parts by Responsibility

### Application bootstrap

- `backend/main.py`: starts Flask and exposes `run_album_lookup_job` for RQ import resolution.
- `backend/app_factory.py`: sets CORS, session-cookie policy, request timing hooks, and registers blueprints.

### Shared infrastructure

- `backend/config.py`: all env-based configuration for Redis, Supabase, Discogs rate limits, queue names, TTLs, and capture behavior.
- `backend/extensions.py`: singleton Redis client, RQ queue, and Supabase client.

### Auth

- `backend/routes/auth_routes.py`: Discogs OAuth request token, callback, and access-token exchange.
- Current truth: the primary auth model is Discogs OAuth stored in the Flask session. Optional Supabase-linked credential support exists in the client helper path, but the live frontend flow still operates through Discogs session cookies.

### Capture storage

- `backend/services/storage_service.py`: deterministic scope generation, object-key generation, checksum and signature creation, Supabase Storage upload, download, delete, manifest reads, and temp-file wrapping.

### OCR

- `backend/ocr_functions/process_image.py`: Gemini-based OCR extraction and formatting prompt.
- `backend/ocr_functions/preprocessing.py`: OpenCV preprocessing helper, currently separate from the active request path.

### Discogs orchestration

- `backend/services/discogs_service.py`: authenticated and public Discogs clients, global rate limiting, normalization logic, queue stats, background lookup orchestration, collection cache warmup, albums mirror, import fingerprinting, duplicate detection, and validation resolution.
- `backend/routes/discogs_routes.py`: import history, collection folder listing, worker status, validation endpoint, and import endpoint.

### Persistence and history

- `backend/services/import_history_service.py`: durable import-history reads and writes backed by the `imports` table.

## Persistence Model

### Supabase Storage

- Stores uploaded capture images in the bucket named by `SUPABASE_UPLOAD_BUCKET`.
- Objects are deleted on import finalization and on OCR failure cleanup.

### Supabase Postgres

- `captures` table from `backend/sql/captures.sql`:
  - one row per uploaded image
  - stores `user_scope`, object key, checksum, signature, status, and timestamps
- `discogs_collection_cache` table from `backend/sql/discogs_collection_cache.sql`:
  - durable per-user, per-folder membership rows
  - keyed by `(discogs_username, folder_id, release_id)`
  - also stores `album_key` and `last_seen_at`
- `imports` table from `backend/sql/imports.sql`:
  - durable per-user import history
  - stores folder metadata, outcome counts, and per-entry results JSON
- `albums` table:
  - used as a durable shared lookup cache for normalized album keys and Discogs release IDs
  - populated by validation results and mirrored collection membership
  - intentionally kept durable because it reduces future Discogs API calls for all users

### Redis

- request-token handshake scratch space for Discogs OAuth
- global Discogs rate-limit buckets
- hot album validation cache
- pending lookup markers to avoid duplicate worker jobs
- RQ queue backing store
- collection membership Redis sets per `(discogs_username, folder_id)`
- import idempotency lock and result cache
- lookup breaker state used to degrade gracefully under Discogs pressure

### RQ worker

- The worker from `backend/worker.py` consumes queued album lookups.
- If no worker is online, validation can fall back to synchronous Discogs lookup instead of stalling permanently.

## Important Behavioral Details

1. The primary API session model is Flask-session-based Discogs auth, not Supabase-auth-based user identity.
2. The frontend still keeps local `scanHistory`, but the current Home and History pages prefer durable backend import history when it exists.
3. The active OCR step uses Gemini directly, not local OCR or OpenCV preprocessing.
4. The app's strongest API-efficiency features are:
	- Redis lookup cache
	- durable `albums` cache
	- durable `discogs_collection_cache`
	- folder warm-up before import
	- shared Discogs rate limiter
	- worker queue with sync fallback when workers are unavailable
5. The app's strongest safety features are:
	- signed capture ownership verification
	- finalize cleanup for uploaded images
	- import fingerprinting and Redis lock
	- duplicate detection by both exact release ID and logical album identity
6. The most important non-obvious distinction is:
	- `discogs_collection_cache` is per-user, per-folder duplicate state
	- `albums` is global lookup-acceleration state