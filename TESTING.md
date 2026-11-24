# Testing SpineScan

## Backend

Create a virtual environment, then install runtime and test dependencies:

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-test.txt
```

Set the minimum fake environment values before running pytest. The test
configuration supplies these defaults automatically, and no real service call
is made:

```text
SUPABASE_URL=https://example.supabase.co
SUPABASE_SECRET_KEY=test-only-supabase-secret
FLASK_SECRET_KEY=test-only-flask-secret
REDIS_URL=redis://127.0.0.1:6379
CAPTURE_SIGNATURE_SECRET=test-only-capture-secret
DISCOGS_SYNC_LOOKUP_ENABLED=false
GEMINI_API_KEY=test-only-gemini-key
```

Run the suite and coverage report:

```powershell
pytest --cov=backend --cov-report=term-missing
```

To exercise Redis integration locally, run Redis on port 6379.

## Frontend

```powershell
cd frontend
npm ci
npm run build
```

There is currently no frontend unit-test runner or test script.

## Docker

Build both deployable images locally:

```powershell
docker build -f Dockerfile.api -t spinescan-api .
docker build -f Dockerfile.worker -t spinescan-worker .
```

## Live Discogs lookup benchmark

The manually dispatched **Live Discogs benchmark** workflow measures the real
`POST /discogs/validate` Flask route. It sends live Discogs searches and uses
the application's synchronous cache-miss fallback (the workflow starts no RQ
worker). Cache-hit samples read the durable Supabase `albums` table and are
checked to make no Discogs API calls. The benchmark does not import releases or
write to a Discogs collection.

The workflow makes four cold lookup requests for each probe album and ten
warm-hit requests for each album (eight misses and twenty hits; twenty-eight
validation requests total). Between cold samples, it verifies that the durable
row still matches the previous result, then clears only that probe's row and
Redis lookup markers before measuring another miss. It also checks that probe
keys and Redis lookup state are absent before starting. Each cold lookup is
capped at three Discogs calls, two query strategies, one page per strategy, and
two attempts per API call. Including one authenticated identity request, the
theoretical maximum is 50 requests (48 lookup attempts plus up to two identity
attempts), leaving 10 requests under the 60-request limit. Other account
activity also uses this budget, and the workflow stops on the first HTTP 429.
It reports min, p50, p95, max, and error counts for cache misses and hits to
the GitHub Actions step summary.

### One-time setup

1. Create a dedicated Discogs test account and a Discogs application for it.
   Complete OAuth authorization once outside CI to obtain the account's
   access-token pair. CI does not perform browser login or store the account
   password.
2. Create a **dedicated, non-production Supabase project** with the same
   `albums` table/schema used by the backend. The workflow needs its project URL
   and service-role key because live cache misses write lookup results. Run
   [`backend/sql/albums.sql`](./backend/sql/albums.sql) in the Supabase SQL
   Editor to create the table and indexes. The service-role key bypasses RLS;
   no client-facing policies are needed.
3. Add these repository Actions secrets:
   - `DISCOGS_CONSUMER_KEY`
   - `DISCOGS_CONSUMER_SECRET`
   - `DISCOGS_BENCHMARK_ACCESS_TOKEN`
   - `DISCOGS_BENCHMARK_ACCESS_TOKEN_SECRET`
   - `DISCOGS_BENCHMARK_USERNAME`
   - `SPINE_SCAN_BENCHMARK_SUPABASE_URL`
   - `SPINE_SCAN_BENCHMARK_SUPABASE_SECRET_KEY`
4. Add the repository Actions variable
   `SPINE_SCAN_BENCHMARK_DATABASE_CONFIRMATION` with the exact value
   `dedicated-benchmark-project`. This is a deliberate write-safety guard; do
   not set it for a production/shared database.
5. Dispatch the workflow from the `main` branch. It runs only on manual
   dispatch, is serialized, and uses a fresh Actions Redis service. It never
   runs on pushes or pull requests.

The fixed probes are `Radiohead / OK Computer` and `Nirvana / Nevermind`. The
runner checks that neither has a pre-existing durable cache row nor Redis
lookup state and aborts rather than overwriting pre-existing data. Rows and
lookup markers for these exact keys and the temporary auth-session record are
removed in cleanup. A cleanup failure fails the job and must be resolved
before rerunning. Use this workflow only with its dedicated Supabase project;
the explicit confirmation value cannot establish that a database is actually
isolated.

The measurements are in-process Flask route latency, not deployed-host HTTP
latency. They include route/cache work and the live synchronous Discogs lookup
on misses; they do not measure RQ queue wait or worker runtime. Results depend
on external Discogs/network conditions. Reauthorize or replace the token
secrets if the dummy account's authorization is revoked.
