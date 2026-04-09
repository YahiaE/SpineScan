import time

from flask import Flask, g, request, session
from flask_cors import CORS

from config import CORS_ORIGINS, FLASK_SECRET_KEY
from routes.auth_routes import auth_bp
from routes.data_routes import data_bp
from routes.discogs_routes import discogs_bp
from routes.ops_routes import ops_bp
from services.monitoring_service import record_http_request


def create_app():
    app = Flask(__name__)
    app.secret_key = FLASK_SECRET_KEY

    CORS(
        app,
        supports_credentials=True,
        origins=CORS_ORIGINS,
    )

    app.config.update(
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=86400,
    )

    @app.before_request
    def before_request():
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

        return response

    app.register_blueprint(auth_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(discogs_bp)
    app.register_blueprint(ops_bp)

    return app
