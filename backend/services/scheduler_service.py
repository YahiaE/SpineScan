"""
Scheduler service for periodic application tasks.
Primarily used to keep Render free-tier instances alive by pinging the health endpoint.
"""

import logging
import os
from datetime import datetime
from typing import Optional

import requests

from services.startup_tracker import mark_warm


logger = logging.getLogger(__name__)

_scheduler: Optional["BackgroundScheduler"] = None
_apscheduler_available = False

# Try to import APScheduler; it may not be available during early deployment stages
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    _apscheduler_available = True
except ImportError:
    BackgroundScheduler = None
    IntervalTrigger = None
    logger.warning(
        "APScheduler not installed. Scheduler will be disabled. "
        "Install 'APScheduler' to enable periodic health checks."
    )


def _ping_health_endpoint():
    """
    Ping the application's health endpoint to prevent instance spindown on Render free tier.
    Render spins down free instances after 15 minutes of inactivity.
    """
    try:
        # Determine the target URL from environment or fallback to localhost
        app_url = os.getenv("APP_URL", "http://localhost:5000")
        health_url = f"{app_url}/healthz"

        response = requests.get(health_url, timeout=5)

        if response.status_code == 200:
            mark_warm()  # Mark app as warm after successful ping
            logger.debug(
                f"[{datetime.now().isoformat()}] Health check ping successful: {health_url}"
            )
        else:
            logger.warning(
                f"[{datetime.now().isoformat()}] Health check ping returned status {response.status_code}: {health_url}"
            )
    except requests.RequestException as error:
        logger.error(
            f"[{datetime.now().isoformat()}] Health check ping failed: {error}",
            exc_info=False,
        )
    except Exception as error:
        logger.error(
            f"[{datetime.now().isoformat()}] Unexpected error during health check: {error}",
            exc_info=True,
        )


def init_scheduler(app=None):
    """
    Initialize the APScheduler scheduler and register jobs.

    Args:
        app: Flask app instance (optional, for logging context)
    """
    global _scheduler

    if not _apscheduler_available:
        logger.warning(
            "APScheduler not available. Skipping scheduler initialization. "
            "Periodic health checks will not run."
        )
        return None

    if _scheduler is not None and _scheduler.running:
        logger.info("Scheduler already initialized and running")
        return _scheduler

    try:
        _scheduler = BackgroundScheduler(daemon=True)

        # Add job to ping health endpoint every 13 minutes
        # (Render spins down after 15 minutes, so 13 is a safe margin)
        ping_interval_minutes = int(os.getenv("HEALTH_CHECK_INTERVAL_MINUTES", "13"))

        _scheduler.add_job(
            _ping_health_endpoint,
            trigger=IntervalTrigger(minutes=ping_interval_minutes),
            id="health_check_ping",
            name="Periodic health check ping to prevent instance spindown",
            replace_existing=True,
            max_instances=1,  # Prevent multiple instances if app is replicated
        )

        _scheduler.start()
        logger.info(
            f"Scheduler initialized: health check ping scheduled every {ping_interval_minutes} minutes"
        )

        return _scheduler
    except Exception as error:
        logger.error(f"Failed to initialize scheduler: {error}", exc_info=True)
        _scheduler = None
        raise


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        try:
            _scheduler.shutdown()
            logger.info("Scheduler stopped")
        except Exception as error:
            logger.error(f"Error stopping scheduler: {error}", exc_info=True)
        finally:
            _scheduler = None


def get_scheduler():
    """Get the current scheduler instance."""
    return _scheduler
