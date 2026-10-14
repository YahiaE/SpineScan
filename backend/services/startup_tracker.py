"""
Startup tracker for detecting cold starts and monitoring warm state.
Used to provide appropriate UX signals to clients.
"""

import logging
import time
from threading import Lock


logger = logging.getLogger(__name__)

_startup_state_lock = Lock()
_app_startup_time = None
_warm_threshold_seconds = 30


def initialize_startup_tracker():
    """Record the application startup time."""
    global _app_startup_time

    with _startup_state_lock:
        _app_startup_time = time.time()
        logger.info("Startup tracker initialized")


def is_cold_start(request_time_seconds):
    """
    Determine if this request is during a potential cold-start.

    Returns True if:
    - The app started less than `_warm_threshold_seconds` ago, OR
    - The request is taking longer than expected (>3-5 seconds)

    Args:
        request_time_seconds: Elapsed time for the current request (in seconds)

    Returns:
        bool: True if likely cold-start, False otherwise
    """
    global _app_startup_time

    with _startup_state_lock:
        if _app_startup_time is None:
            return True  # Startup not tracked yet (shouldn't happen)

        elapsed_since_startup = time.time() - _app_startup_time

        # Still in the warm-up window
        if elapsed_since_startup < _warm_threshold_seconds:
            return True

        # Request is taking suspiciously long (typical cold start takes 3-5s)
        if request_time_seconds > 5:
            return True

    return False


def get_startup_elapsed_seconds():
    """Get seconds elapsed since application startup."""
    global _app_startup_time

    with _startup_state_lock:
        if _app_startup_time is None:
            return 0
        return time.time() - _app_startup_time



