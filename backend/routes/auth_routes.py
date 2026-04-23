import time

from discogs_client.exceptions import HTTPError
from flask import Blueprint, jsonify, request, session

from config import BASE_URL
from extensions import redis_conn
from services.discogs_service import (
    call_discogs,
    create_discogs_oauth_client,
    get_discogs_auth_session_status,
    persist_discogs_auth_tokens,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _get_oauth_pending_state():
    pending = session.get("oauth_pending")
    if isinstance(pending, dict):
        return pending
    return {}


@auth_bp.route("/request_token", methods=["GET"])
def get_request_token():
    """Create an OAuth request token and return Discogs authorize URL."""
    try:
        d = create_discogs_oauth_client()
        request_token, request_token_secret, url = call_discogs(
            lambda: d.get_authorize_url(f"{BASE_URL}/auth/callback"),
            authenticated=False,
        )

        try:
            redis_conn.hset(
                request_token,
                mapping={
                    "request_token_secret": request_token_secret,
                    "oauth_verifier": "",
                    "created_at": time.time(),
                },
            )
            redis_conn.expire(request_token, 600)
        except Exception:
            pending = _get_oauth_pending_state()
            pending[request_token] = {
                "request_token_secret": request_token_secret,
                "oauth_verifier": "",
                "created_at": time.time(),
            }
            session["oauth_pending"] = pending

        session["request_token"] = request_token

        return jsonify(
            {
                "authorize_url": url,
                "oauth_token": request_token,
            }
        )
    except HTTPError as e:
        return jsonify({"error": str(e)}), 500
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/callback", methods=["GET"])
def callback():
    oauth_token = request.args.get("oauth_token")
    oauth_verifier = request.args.get("oauth_verifier")
    if oauth_token and oauth_verifier:
        updated_in_redis = False
        try:
            if redis_conn.hexists(oauth_token, "request_token_secret"):
                redis_conn.hset(oauth_token, "oauth_verifier", oauth_verifier)
                updated_in_redis = True
        except Exception:
            updated_in_redis = False

        if not updated_in_redis:
            pending = _get_oauth_pending_state()
            token_data = pending.get(oauth_token)
            if token_data:
                token_data["oauth_verifier"] = oauth_verifier
                pending[oauth_token] = token_data
                session["oauth_pending"] = pending

    # Do not expose oauth_token in the browser response; the server-side session/Redis state is enough.
    html = """
<!doctype html>
<html>
    <head>
        <meta charset=\"utf-8\" />
        <title>Authorization Complete</title>
    </head>
    <body>
        <script>
            if (window.opener && !window.opener.closed) {
                window.opener.postMessage({ type: "discogs_oauth_complete" }, "*");
            }
            window.close();
        </script>
        <p>Authorization complete. You can close this window.</p>
    </body>
</html>
"""
    return (
        html,
        200,
        {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
    )


@auth_bp.route("/access_token", methods=["GET"])
def exchange_access_token():
    oauth_token = request.args.get("oauth_token") or session.get("request_token")
    token_data = {}
    if oauth_token:
        try:
            request_token_secret, oauth_verifier = redis_conn.hmget(
                oauth_token,
                ["request_token_secret", "oauth_verifier"],
            )
            if request_token_secret or oauth_verifier:
                token_data = {
                    "request_token_secret": request_token_secret or "",
                    "oauth_verifier": oauth_verifier or "",
                }
            else:
                token_data = {}
        except Exception:
            token_data = {}

        if not token_data:
            token_data = _get_oauth_pending_state().get(oauth_token, {})

    if not token_data:
        return {"error": "Missing or invalid oauth_token"}, 400

    oauth_token_secret = token_data.get("request_token_secret")
    oauth_verifier = token_data.get("oauth_verifier")

    if not oauth_verifier:
        return {"error": "Authorization not completed yet"}, 409

    try:
        d = create_discogs_oauth_client()

        d.set_token(oauth_token, oauth_token_secret)
        access_token, access_token_secret = call_discogs(
            lambda: d.get_access_token(oauth_verifier),
            authenticated=False,
        )
        d.set_token(access_token, access_token_secret)
        identity = call_discogs(d.identity, authenticated=True)

        persist_discogs_auth_tokens(
            access_token,
            access_token_secret,
            getattr(identity, "username", None),
        )

        try:
            redis_conn.delete(oauth_token)
        except Exception:
            pass

        pending = _get_oauth_pending_state()
        if oauth_token in pending:
            pending.pop(oauth_token, None)
            session["oauth_pending"] = pending

        session.pop("request_token_secret", None)

        return jsonify(
            {
                "authorized": True,
                "discogs_username": getattr(identity, "username", None),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/session-source", methods=["GET"])
def auth_session_source():
    """Return non-sensitive auth session source details for migration checks."""
    status = get_discogs_auth_session_status()
    return jsonify(status), 200
