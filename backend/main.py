import discogs_client
from discogs_client.exceptions import HTTPError
from flask import Flask, session, redirect, request
from ocr_functions.preprocessing import preprocess_image
from ocr_functions.reader import main as ocr_main
import os
import re
import time
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv("FLASK_SECRET_KEY")  # Set a secret key for the Flask session, used for signing cookies and protecting session data.
# print("Secret key:", app.secret_key)

@app.route("/auth/request_token", methods=["GET"])
def get_request_token_mobile():
    try:
        d = discogs_client.Client(
            'my_user_agent/1.0',
            consumer_key=os.getenv("CONSUMER_KEY"),
            consumer_secret=os.getenv("CONSUMER_SECRET")
        )
        request_token, request_token_secret, url = d.get_authorize_url(os.getenv("HOST") + "/callback") 
        session["request_token"] = request_token
        session["request_token_secret"] = request_token_secret

        return {
            "oauth_token": request_token,
            "oauth_token_secret": request_token_secret,
            "authorize_url": url
        }
    except HTTPError as e:
        return {"error": str(e)}, 500

@app.route("/auth/access_token", methods=["POST"])
def exchange_access_token_mobile():
    data = request.get_json()
    oauth_verifier = data.get("oauth_verifier")
    oauth_token = data.get("oauth_token")
    oauth_token_secret = data.get("oauth_token_secret")

    if not oauth_verifier or not oauth_token or not oauth_token_secret:
        return {"error": "Missing data"}, 400

    try:
        d = discogs_client.Client(
            'my_user_agent/1.0',
            consumer_key=os.getenv("CONSUMER_KEY"),
            consumer_secret=os.getenv("CONSUMER_SECRET")
        )

        d.set_token(oauth_token, oauth_token_secret)
        access_token, access_token_secret = d.get_access_token(oauth_verifier)

        session["access_token"] = access_token
        session["access_token_secret"] = access_token_secret

        return {
            "access_token": access_token,
            "access_token_secret": access_token_secret
        }
    except Exception as e:
        return {"error": str(e)}, 500

# removes all non-alphanumeric characters and converts to lowercase
# makes it easier to compare and search for albums if ocr results have different formatting
def normalize_key(text): 
    return re.sub(r'\W+', '', text).lower() # Res - How I Do => reshowido

def add_ocr_results_to_collection(collection, release_ids, d):
    albums_from_ocr = ocr_main()
    search_cache = {}
    normalized_collection = {normalize_key(entry) for entry in collection}

    for album in albums_from_ocr:
        normalized_album = normalize_key(album)

        if normalized_album in normalized_collection:
            continue  # Already in collection, skip

        # Try to get from cache
        if normalized_album in search_cache:
            release = search_cache[normalized_album]
        else:
            result = d.search(album, type="release").page(0)
            release = result[0] if result else None
            search_cache[normalized_album] = release  # Cache it even if None
            time.sleep(0.5)  # Respect API rate limits

        # If a valid release was found
        if release:
            artist = release.artists[0].name if release.artists else "Unknown Artist"
            title = release.title
            entry = f"{artist} - {title}"
            norm_entry = normalize_key(entry)

        # If the normalized entry is not already in the collection
        if norm_entry not in normalized_collection:
            collection.add(entry)
            release_ids.add(release.id)
            normalized_collection.add(norm_entry)


    print("OCR results: ", albums_from_ocr)
    print("User's collection after adding OCR results: ", collection, f"{len(collection)} items")
    print("Release IDs from user's collection after: ", release_ids, f"{len(release_ids)} items")

    return collection, release_ids

def get_collection(user,d):
    collection = set() # User's entire collection
    release_ids = set()  # Set to store unique release IDs from the collection

    for item in user.collection_folders[0].releases:
        release = d.release(item.id)  # Only one API call per item
        artist = release.artists[0].name if release.artists else "Unknown Artist"
        title = release.title
        collection.add(f"{artist} - {title}")
        release_ids.add(release.id)  # Collect release IDs to avoid duplicates
        time.sleep(0.5)  # Pause to avoid hitting the API rate limit

    print("User's collection before adding OCR results: ", collection, f"{len(collection)} items")
    print("Release IDs from user's collection before: ", release_ids, f"{len(release_ids)} items")
    return collection, release_ids

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)  # Run the application in debug mode