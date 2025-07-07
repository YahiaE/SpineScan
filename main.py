import discogs_client
from flask import Flask, session, redirect, request
from ocr.reader import main as ocr_main
from ocr.preprocessing import preprocess_image
import os
import time
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv("FLASK_SECRET_KEY")  # Set a secret key for the Flask session, used for signing cookies and protecting session data.
# print("Secret key:", app.secret_key)

@app.route("/login") # Endpoint to initiate the login process
def login():
    # Creates a Discogs API client instance with your application's credentials.
    d = discogs_client.Client(
        'my_user_agent/1.0',
        consumer_key=os.getenv("CONSUMER_KEY"), # Identifies your app to the Discogs API (like a public app ID).
        consumer_secret=os.getenv("CONSUMER_SECRET") # Authenticates your app (like a password) and proves the request comes from you.
    )
        
    # request_token, request_secret: temporary tokens that represents your application's request to access the user's Discogs account.
    # signs the request with your application's credentials to prove that the request came from your app
    # returns a request token and secret.  
    request_token, request_token_secret, url = d.get_authorize_url('http://127.0.0.1:5000/callback')
    print("Request token:", request_token)
    print("Request token secret:", request_token_secret)

    # Save request token & secret in session (so we can use it later in callback)
    session["request_token"] = request_token
    session["request_token_secret"] = request_token_secret

    return redirect(url) # Redirects the user to the Discogs authorization page.


@app.route("/callback")  # Endpoint to handle the callback from Discogs after user authorization
def callback():
    oauth_verifier = request.args.get("oauth_verifier") # The verifier code returned by Discogs after user authorization. Acts as proof that the user has authorized your application to access their account.
    request_token = session.get("request_token")
    request_token_secret = session.get("request_token_secret")

    print("Verifier:", oauth_verifier)
    print("Request token:", request_token)
    print("Request token secret:", request_token_secret)

    if not oauth_verifier or not request_token or not request_token_secret: # If any of these values are missing, the callback cannot proceed.
        return "Missing tokens / OAuth verifier", 400

    # Recreate a Discogs API client instance with your application's credentials.
    d = discogs_client.Client(
        'my_user_agent/1.0',
        consumer_key=os.getenv("CONSUMER_KEY"),  
        consumer_secret=os.getenv("CONSUMER_SECRET") 
    )

    # We tell the client to use the request token and secret so Discogs knows this is the same app that started the login process. 
    # This helps keep the process safe and correct.
    d.set_token(request_token, request_token_secret) 

    # Now we can get the access token and secret, which are used to make authenticated requests on behalf of the user.
    access_token, access_token_secret = d.get_access_token(oauth_verifier)
    session["access_token"] = access_token
    session["access_token_secret"] = access_token_secret

    print("Access token:", access_token)
    print("Access token secret:", access_token_secret)

    d.set_token(access_token, access_token_secret)
    user = d.identity()


    collection = set()
    release_ids = set()  
    for item in user.collection_folders[0].releases:
        release = d.release(item.id)  # Only one API call per item
        artist = release.artists[0].name if release.artists else "Unknown Artist"
        title = release.title
        collection.add(f"{artist} - {title}")
        release_ids.add(release.id)  # Collect release IDs to avoid duplicates
        time.sleep(0.5)  # Pause to avoid hitting the API rate limit
    print("User's collection before adding OCR results: ", collection, f"{len(collection)} items")
    print("Release IDs from user's collection before: ", release_ids, f"{len(release_ids)} items")

    # OCR ran on sample image
    albums_from_ocr = ocr_main()

    for album in albums_from_ocr:
        inCollection = album in collection
        release = d.search(album, type="release").page(0)[0] if not inCollection else None
        if not inCollection and release:
            artist = release.artists[0].name if release.artists else "Unknown Artist"
            title = release.title
            if f"{artist} - {title}" not in collection:
                collection.add(f"{artist} - {title}")
                release_ids.add(release.id)
        time.sleep(0.5)  # Pause to avoid hitting the API rate limit
    
    print("OCR results: ", albums_from_ocr)
    print("User's collection after adding OCR results: ", collection, f"{len(collection)} items")
    print("Release IDs from user's collection after: ", release_ids, f"{len(release_ids)} items")


 

    return "Completed login and retrieved user collection."


if __name__ == "__main__":
    app.run(debug=True)  # Run the application in debug mode