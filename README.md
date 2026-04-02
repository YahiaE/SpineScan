# SpineScan

SpineScan is a CD collection assistant that turns shelf photos into structured albums and helps import them into Discogs.

## Workflow

SpineScan runs as a staged pipeline so users can review and correct results before writing to Discogs.

1. Capture and upload
- A user captures CD shelf/spine images in the frontend.
- The backend stores captures in Supabase Storage and tracks signed capture metadata for ownership verification.

2. OCR and text extraction
- The backend processes the latest capture through OCR/image-processing functions.
- Raw OCR output is normalized into candidate Artist - Album pairs.

3. Validation and matching
- Each candidate is validated against Discogs release search.
- Lookup resolution is cache-first:
	- Redis for fast recent hits.
	- Supabase table fallback for persisted valid matches.
	- Background queue job for misses.
- Matching applies normalization, similarity scoring, and quality gates before marking valid/invalid.

4. User review
- The frontend shows validated, pending, and invalid entries.
- Users can review and fix entries before import.

5. Import to Discogs
- Valid entries are imported into the selected Discogs collection folder.
- Import path includes idempotency/duplicate guards to avoid repeat adds.

## Architecture

SpineScan uses a split frontend/backend architecture with async workers for resilient metadata lookup.

- Frontend
	- React + Vite application for capture, review, and import flows.
	- Calls backend API with authenticated session cookies.

- Backend API
	- Flask app composed via an app factory and route blueprints.
	- Auth routes manage Discogs OAuth handshake and token exchange.
	- Data routes handle capture upload, OCR processing, and album extraction.
	- Discogs routes handle folder listing, validation, and import.

- Services layer
	- Discogs service encapsulates search, rate limiting, matching, and queue/cache orchestration.
	- Storage service encapsulates Supabase Storage upload/download/delete and capture signature verification.

- Data and queue components
	- Redis: hot cache, rate-limit buckets, pending markers, idempotency keys.
	- RQ workers: async Discogs lookup jobs for cache misses.
	- Supabase Postgres: persisted album lookup data and capture manifests.
	- Supabase Storage: uploaded capture images.

## Repository layout

- [frontend](frontend): React app.
- [backend](backend): Flask API, services, routes, worker.
- [backend/sql/captures.sql](backend/sql/captures.sql): capture manifest table migration.

The project includes a React frontend and a Flask backend with Redis, RQ workers, Supabase, and Discogs OAuth.
