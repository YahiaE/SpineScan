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
