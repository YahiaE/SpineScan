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
_is_warm = False
_warm_threshold_seconds = 30  # If scheduler has pinged us recently, we're "warm"


def initialize_startup_tracker():
    """Record the application startup time."""
    global _app_startup_time

    with _startup_state_lock:
        _app_startup_time = time.time()
        logger.info("Startup tracker initialized")


def mark_warm():
    """Mark the application as 'warm' (scheduler has successfully pinged us)."""
    global _is_warm

    with _startup_state_lock:
        _is_warm = True
        elapsed = time.time() - _app_startup_time
        logger.info(f"Application marked as warm after {elapsed:.2f} seconds")


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
    global _app_startup_time, _is_warm

    with _startup_state_lock:
        if _is_warm:
            return False  # Scheduler has warmed us up

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


def is_application_warm():
    """Check if the application has been marked as warm."""
    global _is_warm

    with _startup_state_lock:
        return _is_warm
