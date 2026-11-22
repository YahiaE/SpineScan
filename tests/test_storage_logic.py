from PIL import Image
from io import BytesIO

from services.storage_service import (
    build_capture_checksum,
    build_capture_object_key,
    build_capture_signature,
    build_capture_user_scope,
    compress_upload_image,
    verify_capture_signature,
)


def test_capture_scope_prefers_lowercase_discogs_username():
    scope = build_capture_user_scope("token-value", "  MixedCaseUser  ")

    assert len(scope) == 24
    assert scope == build_capture_user_scope("different-token", "mixedcaseuser")


def test_capture_scope_uses_token_when_username_is_missing():
    assert build_capture_user_scope("token-value") == build_capture_user_scope(
        "token-value", None
    )


def test_capture_object_key_contains_scope_checksum_and_suffix(monkeypatch):
    monkeypatch.setattr("services.storage_service.time.time", lambda: 1234.567)

    key = build_capture_object_key("scope", b"image bytes", ".png")

    assert key.startswith("scope/")
    assert key.endswith(".png")


def test_capture_signature_is_valid_for_unchanged_manifest():
    checksum = build_capture_checksum(b"capture")

    signature = build_capture_signature("scope", "scope/image.jpg", checksum)

    assert verify_capture_signature(
        "scope", "scope/image.jpg", checksum, signature
    )


def test_capture_signature_rejects_changed_object_key():
    checksum = build_capture_checksum(b"capture")
    signature = build_capture_signature("scope", "scope/original.jpg", checksum)

    assert not verify_capture_signature(
        "scope", "scope/changed.jpg", checksum, signature
    )


def test_compress_upload_image_returns_jpeg_for_png_input():
    image_buffer = BytesIO()
    Image.new("RGBA", (400, 300), (255, 0, 0, 128)).save(
        image_buffer, format="PNG"
    )

    compressed, content_type, suffix = compress_upload_image(image_buffer.getvalue())

    assert content_type == "image/jpeg"
    assert suffix == ".jpg"
    assert Image.open(BytesIO(compressed)).format == "JPEG"
