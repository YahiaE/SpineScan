import routes.auth_routes as auth_routes


def test_callback_returns_no_store_html_without_exposing_oauth_token(
    client, monkeypatch
):
    class RedisClient:
        def hexists(self, *_args):
            return True

        def hset(self, *_args, **_kwargs):
            return 1

    monkeypatch.setattr(auth_routes, "redis_conn", RedisClient())

    response = client.get(
        "/auth/callback",
        query_string={"oauth_token": "token", "oauth_verifier": "verifier"},
    )

    assert response.status_code == 200
    assert "Authorization Complete" in response.get_data(as_text=True)
    assert response.headers["Cache-Control"] == "no-store"


def test_request_token_requires_discogs_oauth_when_unauthorized(
    client, monkeypatch
):
    class OAuthClient:
        def get_authorize_url(self, _callback):
            return "request-token", "request-secret", "https://discogs.example/auth"

    class RedisClient:
        def hset(self, *_args, **_kwargs):
            raise ConnectionError("redis unavailable")

        def expire(self, *_args):
            return True

    monkeypatch.setattr(
        auth_routes, "create_discogs_oauth_client", lambda: OAuthClient()
    )
    monkeypatch.setattr(
        auth_routes,
        "call_discogs",
        lambda callback, authenticated: callback(),
    )
    monkeypatch.setattr(auth_routes, "redis_conn", RedisClient())

    response = client.get("/auth/request_token")

    assert response.status_code == 200
    assert response.get_json()["authorize_url"] == "https://discogs.example/auth"
