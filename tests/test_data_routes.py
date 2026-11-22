import routes.data_routes as data_routes


def test_upload_requires_authenticated_user(client, monkeypatch):
    monkeypatch.setattr(data_routes, "get_discogs_access_token", lambda: None)

    response = client.post(
        "/data/upload",
        data={"file": (b"image", "capture.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": "User not authenticated"}


def test_upload_rejects_missing_file_for_authenticated_user(client, monkeypatch):
    monkeypatch.setattr(
        data_routes, "get_discogs_access_token", lambda: "access-token"
    )

    response = client.post("/data/upload", data={}, content_type="multipart/form-data")

    assert response.status_code == 400
    assert response.get_json() == {"error": "No file field in request"}


def test_upload_rejects_empty_file(client, monkeypatch):
    monkeypatch.setattr(
        data_routes, "get_discogs_access_token", lambda: "access-token"
    )

    response = client.post(
        "/data/upload",
        data={"file": (b"", "empty.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Uploaded file is empty"}
