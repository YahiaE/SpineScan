"""Flask backend for Discogs OAuth and collection enrichment using OCR.

This module provides:
- OAuth callback/token exchange endpoints for mobile deep-link auth flow.
- Helpers to normalize collection keys and deduplicate entries.
- Utilities to merge OCR-detected albums into a user's Discogs collection.

Environment variables used:
- FLASK_SECRET_KEY
- CONSUMER_KEY
- CONSUMER_SECRET
"""

import os
import re
import time
import json
import tempfile
import redis
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv()  # Must run before any project imports that read env vars

import discogs_client
from discogs_client.exceptions import HTTPError
from flask import Flask, session, redirect, request
from flask_cors import CORS
from ocr_functions.reader import main as ocr_main

app = Flask(__name__)

CORS(
    app,
    supports_credentials=True,
    origins=["http://localhost:5173", "http://192.168.1.146:5173"],
)

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY"
)  # Set a secret key for the Flask session, used for signing cookies and protecting session data.


@app.route("/auth/request_token", methods=["GET"])
def get_request_token():
    """Create an OAuth request token and return Discogs authorize URL.

    Also stores `request_token` and `request_token_secret` in session so the
    access-token exchange step can complete later.
    """
    try:
        d = discogs_client.Client(
            "my_user_agent/1.0",
            consumer_key=os.getenv("CONSUMER_KEY"),
            consumer_secret=os.getenv("CONSUMER_SECRET"),
        )
        request_token, request_token_secret, url = d.get_authorize_url(
            "http://192.168.1.146:5000/auth/callback"
        )

        print(request_token, request_token_secret, url)

        r.hset(
            request_token,
            mapping={
                "request_token_secret": request_token_secret,
                "oauth_verifier": "",
                "created_at": time.time(),
            },
        )

        session["request_token"] = request_token
        session["request_token_secret"] = request_token_secret

        return {
            "authorize_url": url,
            "oauth_token": request_token,
            "oauth_token_secret": request_token_secret,
        }
    except HTTPError as e:
        return {"error": str(e)}, 500


@app.route("/auth/callback", methods=["GET"])
def callback():
    oauth_token = request.args.get("oauth_token")
    oauth_verifier = request.args.get("oauth_verifier")
    if r.hgetall(oauth_token):
        r.hset(oauth_token, "oauth_verifier", oauth_verifier)

    return {"ok": True, "oauth_token": oauth_token}


@app.route("/auth/access_token", methods=["GET"])
def exchange_access_token():
    oauth_token = request.args.get("oauth_token") or session.get("request_token")
    token_data = r.hgetall(oauth_token) if oauth_token else {}

    if not token_data:
        return {"error": "Missing or invalid oauth_token"}, 400

    oauth_token_secret = token_data.get("request_token_secret")
    oauth_verifier = token_data.get("oauth_verifier")

    if not oauth_verifier:
        return {"error": "Authorization not completed yet"}, 409

    print(oauth_token, oauth_token_secret)

    try:
        d = discogs_client.Client(
            "my_user_agent/1.0",
            consumer_key=os.getenv("CONSUMER_KEY"),
            consumer_secret=os.getenv("CONSUMER_SECRET"),
        )

        d.set_token(oauth_token, oauth_token_secret)
        access_token, access_token_secret = d.get_access_token(oauth_verifier)

        session["access_token"] = access_token
        session["access_token_secret"] = access_token_secret

        r.delete(oauth_token)

        print(access_token, access_token_secret)
        print(d.identity())

        return {
            "access_token": access_token,
            "access_token_secret": access_token_secret,
        }
    except Exception as e:
        return {"error": str(e)}, 500


ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


@app.route("/data/upload", methods=["POST"])
def upload_image():
    if "file" not in request.files:
        return {"error": "No file field in request"}, 400

    file = request.files["file"]

    if file.mimetype not in ALLOWED_MIME:
        return {"error": "Unsupported file type"}, 415

    suffix = ".jpg" if file.mimetype == "image/jpeg" else ".png"
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix, dir=os.path.join(os.path.dirname(__file__), "data")
    )
    try:
        file.save(tmp.name)
    except Exception as e:
        os.unlink(tmp.name)
        return {"error": str(e)}, 500

    return {"path": tmp.name}


@app.route("/data/scan", methods=["POST"])
def scan_image():
    body = request.get_json(silent=True)
    if not body or "path" not in body:
        return {"error": "Missing 'path' in request body"}, 400

    path = body["path"]

    if not os.path.isfile(path):
        return {"error": "File not found"}, 404

    try:
        albums = ocr_main(path)
        return {"albums": albums}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/data/albums", methods=["GET"])
def get_albums():
    d = discogs_client.Client(
        "my_user_agent/1.0",
        consumer_key=os.getenv("CONSUMER_KEY"),
        consumer_secret=os.getenv("CONSUMER_SECRET"),
    )

    access_token = session.get("access_token")
    access_token_secret = session.get("access_token_secret")
    d.set_token(access_token, access_token_secret)

    user = d.identity()

    albums = []
    for album in user.collection_folders[0].releases:
        albums.append(
            {"name": album.release.artists[0].name, "title": album.release.title}
        )

    return json.dumps(albums, indent=4)


if __name__ == "__main__":
    """Run local Flask app for development."""
    import os

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
