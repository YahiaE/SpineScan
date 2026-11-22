from ocr_functions.process_image import AlbumEntry, SpineScanResult, main


def test_main_returns_empty_when_all_gemini_tiers_return_no_items(
    tmp_path, monkeypatch
):
    image_path = tmp_path / "capture.jpg"
    image_path.write_bytes(b"fake image")
    monkeypatch.setattr(
        "ocr_functions.process_image.get_gemini_client", lambda: object()
    )
    monkeypatch.setattr(
        "ocr_functions.process_image.execute_scan", lambda *args: None
    )

    assert main(str(image_path)) == ""


def test_main_uses_fallback_model_when_first_tier_is_empty(tmp_path, monkeypatch):
    image_path = tmp_path / "capture.jpg"
    image_path.write_bytes(b"fake image")
    calls = []

    def fake_execute_scan(client, image_bytes, prompt, model_name):
        calls.append(model_name)
        if model_name == "gemini-3.5-flash-lite":
            return SpineScanResult(items=[])
        return SpineScanResult(
            items=[AlbumEntry(artist="Radiohead", album="OK Computer")]
        )

    monkeypatch.setattr(
        "ocr_functions.process_image.get_gemini_client", lambda: object()
    )
    monkeypatch.setattr(
        "ocr_functions.process_image.execute_scan", fake_execute_scan
    )

    assert main(str(image_path)) == "Radiohead - OK Computer"
    assert calls == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]


def test_main_uses_stable_fallback_when_latest_flash_returns_no_items(
    tmp_path, monkeypatch
):
    image_path = tmp_path / "capture.jpg"
    image_path.write_bytes(b"fake image")
    calls = []

    def fake_execute_scan(client, image_bytes, prompt, model_name):
        calls.append(model_name)
        if model_name == "gemini-3.6-flash":
            return SpineScanResult(
                items=[AlbumEntry(artist="Radiohead", album="OK Computer")]
            )
        return None

    monkeypatch.setattr(
        "ocr_functions.process_image.get_gemini_client", lambda: object()
    )
    monkeypatch.setattr(
        "ocr_functions.process_image.execute_scan", fake_execute_scan
    )

    assert main(str(image_path)) == "Radiohead - OK Computer"
    assert calls == [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
    ]


def test_main_filters_blank_items_and_formats_valid_items(tmp_path, monkeypatch):
    image_path = tmp_path / "capture.jpg"
    image_path.write_bytes(b"fake image")

    monkeypatch.setattr(
        "ocr_functions.process_image.get_gemini_client", lambda: object()
    )
    monkeypatch.setattr(
        "ocr_functions.process_image.execute_scan",
        lambda *args: SpineScanResult(
            items=[
                AlbumEntry(artist="Radiohead", album="OK Computer"),
                AlbumEntry(artist="", album="Missing Artist"),
            ]
        ),
    )

    assert main(str(image_path)) == "Radiohead - OK Computer"


def test_execute_scan_retries_one_transient_503(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from google.genai.errors import APIError

    from ocr_functions import process_image

    parsed = SpineScanResult(
        items=[AlbumEntry(artist="Radiohead", album="OK Computer")]
    )
    generate_content = Mock(
        side_effect=[
            APIError(
                503,
                {
                    "error": {
                        "code": 503,
                        "message": "Temporary overload",
                        "status": "UNAVAILABLE",
                    }
                },
            ),
            SimpleNamespace(parsed=parsed),
        ]
    )
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    )
    sleep = Mock()
    monkeypatch.setattr(process_image.time, "sleep", sleep)

    assert (
        process_image.execute_scan(client, b"image", "prompt", "test-model")
        == parsed
    )
    assert generate_content.call_count == 2
    sleep.assert_called_once_with(1)
