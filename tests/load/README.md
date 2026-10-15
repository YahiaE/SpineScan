# SpineScan Load Test

This Locust scenario exercises upload, OCR, validation, polling, and capture cleanup. It deliberately does not call `/api/discogs/import`, so it will not add releases to a collection.

The flow makes real Supabase Storage, Gemini, Discogs, Redis, and RQ calls. Use a staging deployment, a dedicated Discogs test account (or accounts), and a non-sensitive photo of CD spines. Each virtual user selects a session cookie from the local cookie pool. For a multi-user test, provide one distinct account session per active virtual user; sharing one cookie models one Discogs account and its rate limit, not independent users.

## Setup

From the repository root, install the separate load-test dependencies:

```powershell
python -m venv .venv-load
.venv-load\Scripts\Activate.ps1
pip install -r requirements-load.txt
```

Create `.loadtest/sessions.json` as a JSON array containing raw Flask `session` cookie values. Keep this file private; `.loadtest/` is git-ignored.

```json
[
  "signed-session-cookie-for-test-account-one",
  "signed-session-cookie-for-test-account-two"
]
```

Place a representative JPEG at `tests/load/fixtures/scan.jpg`, or set `SPINESCAN_LOAD_IMAGE` to another local image path. The fixtures directory is git-ignored.

## Run

Point Locust directly at the API, not the Vite frontend. Start with one user and ramp gradually:

```powershell
$env:SPINESCAN_LOAD_TEST_ENABLE = "1"
locust -f tests/load/locustfile.py --host https://YOUR-STAGING-API
```

Open Locust's web UI, then try 1, 5, and 10 users with a conservative spawn rate. Do not enable this against production without explicitly setting `SPINESCAN_LOAD_TEST_ALLOW_PRODUCTION=1`; avoid production load tests unless you have a maintenance window and understand the upstream costs and rate limits.

Optional settings:

- `SPINESCAN_LOAD_SESSIONS_FILE`: session-cookie JSON path; defaults to `.loadtest/sessions.json`.
- `SPINESCAN_LOAD_IMAGE`: JPEG path; defaults to `tests/load/fixtures/scan.jpg`.
- `SPINESCAN_LOAD_MAX_ENTRIES`: cap OCR entries validated per workflow; defaults to 16.
- `SPINESCAN_LOAD_MAX_POLL_ATTEMPTS`: validation-status polls before reporting a workflow failure; defaults to 8.
- `SPINESCAN_LOAD_TEST_ALLOW_PRODUCTION`: explicit second opt-in for the production Fly API hostname.

The test calls OCR and Discogs search, so it consumes Gemini and Discogs quotas. It uploads to Supabase Storage and requests cleanup at the end of each workflow. Review Locust's per-endpoint p95, failure rate, and request rate alongside Fly API CPU/memory, RQ queue depth/oldest-job age, and Discogs 429 metrics.