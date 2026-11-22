import pytest

import routes.discogs_routes as discogs_routes


def test_validate_rejects_missing_entries_before_external_calls(client):
    response = client.post("/discogs/validate", json={})

    assert response.status_code == 400
    assert "Missing 'entries'" in response.get_json()["error"]


def test_validate_rejects_invalid_title_without_discogs_lookup(client, monkeypatch):
    monkeypatch.setattr(
        discogs_routes, "_consume_user_rate_slot", lambda *_args: True
    )
    monkeypatch.setattr(discogs_routes, "get_discogs_client", lambda: object())
    monkeypatch.setattr(
        discogs_routes,
        "build_lookup_request_context",
        lambda: {"auth_session_id": None, "lookup_jobs_to_enqueue": {}},
    )
    monkeypatch.setattr(
        discogs_routes, "prefetch_release_lookup_states", lambda _entries: {}
    )
    monkeypatch.setattr(
        discogs_routes,
        "resolve_release_match",
        lambda *_args, **_kwargs: pytest.fail("invalid entries must not resolve"),
    )

    response = client.post(
        "/discogs/validate",
        json={"entries": [{"id": "1", "artist": "Artist", "title": "  "}]},
    )

    assert response.status_code == 200
    assert response.get_json()["validations"][0]["status"] == "invalid"
