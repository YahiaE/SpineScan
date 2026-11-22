from ocr_functions.process_image import AlbumEntry, SpineScanResult, main


def test_main_returns_empty_when_both_gemini_tiers_return_no_items(
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
        if model_name == "gemini-2.5-flash-lite":
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
    assert calls == ["gemini-2.5-flash-lite", "gemini-3.8-flash"]


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
