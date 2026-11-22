import os
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"


def load_configured_redis_url(redis_url, upstash_redis_url):
    env = os.environ.copy()
    env.update(
        {
            "FLASK_SECRET_KEY": "test-only-flask-secret",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "test-only-supabase-secret",
        }
    )
    env.pop("REDIS_URL", None)
    env.pop("UPSTASH_REDIS_URL", None)
    if redis_url is not None:
        env["REDIS_URL"] = redis_url
    if upstash_redis_url is not None:
        env["UPSTASH_REDIS_URL"] = upstash_redis_url

    completed = subprocess.run(
        [sys.executable, "-c", "import config; print(config.REDIS_URL or '')"],
        check=True,
        capture_output=True,
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
    )
    return completed.stdout.strip()


def test_config_prefers_redis_url_over_upstash_fallback():
    assert load_configured_redis_url(
        "redis://new-redis.internal:6379/0",
        "rediss://old-upstash.example:6379",
    ) == "redis://new-redis.internal:6379/0"


def test_config_uses_upstash_url_when_redis_url_is_unset():
    assert load_configured_redis_url(
        None,
        "rediss://old-upstash.example:6379",
    ) == "rediss://old-upstash.example:6379"
