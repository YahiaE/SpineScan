import discogs_client
from flask import Flask, session, redirect, request
import os
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
        consumer_key=os.getenv("CONSUMER_KEY"),  
        consumer_secret=os.getenv("CONSUMER_SECRET") 
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
    oauth_verifier = request.args.get("oauth_verifier") # The verifier code returned by Discogs after user authorization.
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
    # print("User logged in:", user.username)
    return f"Logged in as {user.username}. You can now close this window."


if __name__ == "__main__":
    app.run(debug=True)  # Run the application in debug mode