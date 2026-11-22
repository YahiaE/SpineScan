import os
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

os.environ.setdefault("FLASK_SECRET_KEY", "test-only-flask-secret")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-only-supabase-secret")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379")
os.environ.setdefault("DISCOGS_SYNC_LOOKUP_ENABLED", "false")
os.environ.setdefault("CAPTURE_SIGNATURE_SECRET", "test-only-capture-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-only-gemini-key")

for path in (str(REPOSITORY_ROOT), str(BACKEND_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture
def app():
    from app_factory import create_app

    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()
