import time

from discogs_client.exceptions import HTTPError
from flask import Blueprint, jsonify, request, session

from extensions import redis_conn
from services.discogs_service import call_discogs, create_discogs_oauth_client

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/request_token", methods=["GET"])
def get_request_token():
    """Create an OAuth request token and return Discogs authorize URL."""
    try:
        d = create_discogs_oauth_client()
        request_token, request_token_secret, url = call_discogs(
            lambda: d.get_authorize_url("http://192.168.1.146:5000/auth/callback"),
            authenticated=False,
        )

        redis_conn.hset(
            request_token,
            mapping={
                "request_token_secret": request_token_secret,
                "oauth_verifier": "",
                "created_at": time.time(),
            },
        )

        session["request_token"] = request_token
        session["request_token_secret"] = request_token_secret

        return jsonify(
            {
                "authorize_url": url,
                "oauth_token": request_token,
                "oauth_token_secret": request_token_secret,
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
    if redis_conn.hgetall(oauth_token):
        redis_conn.hset(oauth_token, "oauth_verifier", oauth_verifier)

    return jsonify({"ok": True, "oauth_token": oauth_token})


@auth_bp.route("/access_token", methods=["GET"])
def exchange_access_token():
    oauth_token = request.args.get("oauth_token") or session.get("request_token")
    token_data = redis_conn.hgetall(oauth_token) if oauth_token else {}

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

        session["access_token"] = access_token
        session["access_token_secret"] = access_token_secret
        session["discogs_username"] = getattr(identity, "username", None)

        redis_conn.delete(oauth_token)

        return jsonify(
            {
                "access_token": access_token,
                "access_token_secret": access_token_secret,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
