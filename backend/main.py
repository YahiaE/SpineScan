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

import discogs_client
from discogs_client.exceptions import HTTPError
from flask import Flask, session, redirect, request
from ocr_functions.reader import main as ocr_main
import os
import re
import time
import json
import redis
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

OAUTH_PENDING = {}
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

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
            "http://10.107.210.61:5000/auth/callback"
        )

        r.hset(request_token, mapping = {
            "request_token_secret": request_token_secret,
            "oauth_verifier": None,
            "created_at": time.time(),
        } )
        

        session["request_token"] = request_token
        session["request_token_secret"] = request_token_secret

        print(request_token, request_token_secret, url)
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
        r.hgetall(oauth_token)["oauth_verifier"] = oauth_verifier

    return {"ok": True, "oauth_token": oauth_token}


@app.route("/auth/access_token", methods=["GET"])
def exchange_access_token():
    oauth_token = session.get("request_token")
    oauth_token_secret = session.get("request_token_secret")
    print(oauth_token, oauth_token_secret)

    if not r.hgetall(oauth_token):
        return {"error": "Missing data"}, 400

    try:
        d = discogs_client.Client(
            "my_user_agent/1.0",
            consumer_key=os.getenv("CONSUMER_KEY"),
            consumer_secret=os.getenv("CONSUMER_SECRET"),
        )

        d.set_token(oauth_token, oauth_token_secret)
        access_token, access_token_secret = d.get_access_token(
           r.hgetall(oauth_token)["oauth_verifier"]
        )

        

        session["access_token"] = access_token
        session["access_token_secret"] = access_token_secret
        print(access_token, access_token_secret)
        print(d.identity())

        return {
            "access_token": access_token,
            "access_token_secret": access_token_secret,
        }
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
        albums.append({"name": album.release.artists[0].name, "title": album.release.title})

        
    
    return json.dumps(albums,indent=4)



if __name__ == "__main__":
    """Run local Flask app for development."""
    import os

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
