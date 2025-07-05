import discogs_client
import os
from dotenv import load_dotenv
load_dotenv()

# consumer_key, consumer_secret: crendentials to identify that your application to registered and allowed to use Discogs API. 
d = discogs_client.Client(
    'my_user_agent/1.0',
    consumer_key=os.getenv('CONSUMER_KEY'),
    consumer_secret=os.getenv('CONSUMER_SECRET')
)

# request_token, request_secret: temporary tokens that represents your application's request to access the user's Discogs account.
# signs the request with your application's credentials to prove that the request came from your app
# returns a request token and secret.  
request_token, request_secret, url = d.get_authorize_url()

# The user must visit the URL to authorize the application to access their account. 
print("Click on this url to authorize the application:", url)
verifier = input("Paste the OAuth verifier from the redirected url here: ") # This is the code you get after authorizing the app on Discogs.
access_token, access_token_secret =  d.get_access_token(verifier) # credientials to access and modify uithe user's account.

user = d.identity() 
print(user.username, "is now authenticated with Discogs.")