# SpineScan

SpineScan uses OCR and music metadata APIs to identify physical CDs from spine or cover photos and import them into a Discogs collection.

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
