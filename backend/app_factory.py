import logging
import os
import time

from flask import Flask, g, redirect, request, session
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge

from config import (
    CORS_ORIGINS,
    CSRF_ORIGIN_ENFORCEMENT,
    CSRF_TRUSTED_ORIGINS,
    FLASK_SECRET_KEY,
    MAX_UPLOAD_BYTES,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
)
from routes.auth_routes import auth_bp
from routes.data_routes import data_bp
from routes.discogs_routes import discogs_bp
from routes.ops_routes import ops_bp
from services.monitoring_service import record_http_request
from services.scheduler_service import init_scheduler, stop_scheduler
from services.startup_tracker import initialize_startup_tracker, is_cold_start


logger = logging.getLogger(__name__)


def _configure_logging():
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=getattr(
                logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO
            ),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    logging.getLogger().setLevel(
        getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    )
    logger.setLevel(logging.INFO)


def create_app():
    _configure_logging()

    app = Flask(__name__)
    app.secret_key = FLASK_SECRET_KEY

    @app.get("/api/auth/callback")
    def auth_callback_compat():
        query = request.query_string.decode("utf-8")
        target = "/auth/callback"
        if query:
            target = f"{target}?{query}"
        return redirect(target, code=302)

    # Initialize startup tracker early to monitor cold starts
    initialize_startup_tracker()

    CORS(
        app,
        supports_credentials=True,
        origins=CORS_ORIGINS,
    )

    app.config.update(
        SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=SESSION_COOKIE_SAMESITE,
        PERMANENT_SESSION_LIFETIME=86400,
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    )

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_error):
        return {
            "error": "Uploaded file is too large",
            "max_upload_bytes": MAX_UPLOAD_BYTES,
        }, 413

    @app.before_request
    def before_request():
        if request.path.startswith("/auth/") or request.path.startswith("/api/auth/"):
            logger.info("incoming request %s %s", request.method, request.path)

        if CSRF_ORIGIN_ENFORCEMENT and request.method in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            trusted_origins = set(CORS_ORIGINS) | set(CSRF_TRUSTED_ORIGINS)
            request_origin = request.headers.get("Origin") or ""
            if request_origin and request_origin not in trusted_origins:
                return {"error": "Blocked by origin policy"}, 403

        session.permanent = True
        g.request_started_at = time.perf_counter()

    @app.after_request
    def after_request(response):
        started_at = getattr(g, "request_started_at", None)
        if started_at is not None:
            duration = time.perf_counter() - started_at
            record_http_request(
                method=request.method,
                path=request.path,
                status_code=response.status_code,
                duration_seconds=duration,
            )

            if (
                request.path.startswith("/auth/")
                or request.path.startswith("/api/auth/")
                or response.status_code >= 400
            ):
                logger.info(
                    "request complete %s %s -> %s in %.3fs",
                    request.method,
                    request.path,
                    response.status_code,
                    duration,
                )

            # Add cold-start indicators for client UX awareness
            if is_cold_start(duration):
                response.headers["X-Cold-Start"] = "true"
                response.headers["X-Request-Duration"] = f"{duration:.2f}s"
                if duration > 3:
                    response.headers["X-Slow-Request"] = "true"
                    response.headers["X-Warning"] = (
                        "Server is waking up. First request may take up to 30 seconds."
                    )

        return response

    app.register_blueprint(auth_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(discogs_bp)
    app.register_blueprint(ops_bp)

    # Initialize scheduler for periodic health checks (to prevent Render free-tier spindown)
    try:
        init_scheduler(app)

        # Register shutdown hook to gracefully stop scheduler
        @app.teardown_appcontext
        def shutdown_scheduler(_exception=None):
            stop_scheduler()
    except Exception as error:
        logger.warning(
            f"Failed to initialize scheduler: {error}. App will still run without periodic health checks."
        )

    return app
