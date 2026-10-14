"""
COLD-START RESILIENCE GUIDE

This document describes the backend implementation and frontend integration
for handling Render free-tier cold starts gracefully.
"""

# ARCHITECTURE OVERVIEW

Three layers of defense against cold-start issues:

1. **Scheduler (Pinger)** - Keeps instance warm via periodic health checks
   - Pings /healthz every 13 minutes (before Render's 15-min spindown)
   - Marks app as "warm" when successful
   - Prevents most cold starts in normal conditions

2. **Lazy Loading** - Reduces cold-start impact if spindown occurs
   - Gemini client (OCR): Imported only on first image process request
   - Discogs client: Imported only on first album lookup
   - Benefits: ~1-2 sec faster cold boot, less memory on startup

3. **Cold-Start Awareness** - Client-side UX signals for slow requests
   - Response headers indicate if request is slow/during boot
   - Frontend shows "waking server" message if needed
   - User expectations are set properly


# RESPONSE HEADERS

The backend adds these headers when a request is slow or during cold-start:

Header                  | Value              | Meaning
----------------------- | ------------------ | ------------------------------------------------
X-Cold-Start           | "true"             | Request happened during cold-start period
X-Request-Duration     | "5.23s"            | How long the request took (in seconds)
X-Slow-Request         | "true"             | Request took >3 seconds (added if cold-start=true)
X-Warning              | "Server is waking up..." | User-facing message about slow boot


# FRONTEND INTEGRATION EXAMPLE

```typescript
// React hook to detect cold starts
async function fetchWithColdStartAwareness(url: string) {
  const startTime = performance.now();
  
  try {
    const response = await fetch(url);
    
    // Check for cold-start signals
    const isColdStart = response.headers.get('X-Cold-Start') === 'true';
    const duration = response.headers.get('X-Request-Duration');
    const warning = response.headers.get('X-Warning');
    
    if (isColdStart && duration && parseFloat(duration) > 3) {
      // Show user-friendly message
      console.warn(`⏳ Server is waking up (${duration})`);
      showNotification({
        title: "Server Starting",
        message: warning || "First request may take up to 30 seconds. Please wait...",
        type: "info",
        duration: 5000,
      });
    }
    
    return response;
  } catch (error) {
    // Network error during cold-start
    console.error("Request failed during cold-start:", error);
    throw error;
  }
}
```


# ASYNC PROCESSING PATHWAY (RECOMMENDED NEXT STEP)

Current flow: Request -> OCR (slow) -> Response
Recommended: Request (fast) -> Queue job -> Poll for result

Benefits:
- User gets immediate feedback ("processing...")
- Browser doesn't timeout on slow requests
- Better UX for heavy operations

Implementation steps:
1. Create async OCR endpoint (return job_id immediately)
2. Create polling endpoint to check job status
3. Frontend submits image, polls for result
4. Show spinner/progress while processing

Example flow:
POST /process/image -> { job_id: "xyz" } (instant)
GET /process/image/xyz -> { status: "processing" } (poll)
GET /process/image/xyz -> { status: "completed", albums: [...] } (ready)


# CONFIGURATION

Environment variables (in your .env or deployment settings):

Variable                           | Default  | Purpose
---------------------------------- | -------- | --------------------------------------------------
DISCOGS_SYNC_LOOKUP_TIMEOUT_SECONDS | 30      | Timeout for album lookups


# TESTING COLD-STARTS LOCALLY

```bash
# Terminal 1: Start the app
python backend/main.py

# Terminal 2: Monitor logs (watch for "Startup tracker initialized")
tail -f app.log | grep -i "startup\|warm"

# Terminal 3: Make a request immediately after startup
time curl http://localhost:5000/healthz -v

# You should see X-Cold-Start: true in first request headers
```


# MONITORING

Check logs for:
- "Startup tracker initialized" - App bootup complete
- "Application marked as warm after X seconds" - Scheduler successfully pinged us
- "Health check ping successful" - Scheduler running normally
- "X-Cold-Start: true" response headers - Cold-start detected in request

In production, monitor:
1. Request latency (should be <1s normally, >3s during cold-start)
2. Scheduler success rate (should be ~100%)
3. User experience metrics (time-to-interaction)


# FALLBACK BEHAVIOR

If scheduler fails or instance spins down anyway:
1. Request comes in (cold-start)
2. Heavy modules lazy-load (adds 1-3 seconds)
3. Response includes X-Cold-Start, X-Request-Duration, X-Warning headers
4. Frontend shows notification to user
5. User understands the delay is temporary

This graceful degradation ensures the app remains usable even
if the scheduler is disabled or Render policy changes.
