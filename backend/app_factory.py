from flask import Flask, session
from flask_cors import CORS

from config import CORS_ORIGINS, FLASK_SECRET_KEY
from routes.auth_routes import auth_bp
from routes.data_routes import data_bp
from routes.discogs_routes import discogs_bp


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

    app.register_blueprint(auth_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(discogs_bp)

    return app
