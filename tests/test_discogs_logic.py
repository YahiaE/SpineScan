from services.discogs_service import (
    album_identity_key,
    build_import_request_fingerprint,
    is_cd_release_result,
    is_various_lookup,
    normalize_text,
    parse_release_result,
    primary_artist_name,
    score_candidate,
    strip_version_suffix,
)


def test_normalize_text_removes_diacritics_and_punctuation():
    assert normalize_text("  Björk: Debút  ") == "bjork debut"


def test_primary_artist_name_returns_first_featured_artist():
    assert primary_artist_name("Daft Punk feat. Pharrell") == "Daft Punk"


def test_strip_version_suffix_removes_deluxe_marker():
    assert strip_version_suffix("Album Title (Deluxe Edition)") == "album title"


def test_album_identity_key_normalizes_featured_artist_and_version():
    assert album_identity_key(
        "Daft Punk feat. Pharrell",
        "Discovery (Deluxe Edition)",
    ) == ("daftpunk", "discovery")


def test_parse_release_result_splits_artist_from_discogs_title():
    class Release:
        title = "Radiohead - OK Computer"
        artists = None

    assert parse_release_result(Release()) == ("Radiohead", "OK Computer")


def test_is_cd_release_result_accepts_cd_in_format_list():
    class Release:
        formats = ["CD", "Album"]

    assert is_cd_release_result(Release())


def test_is_cd_release_result_rejects_vinyl_only_metadata():
    class Release:
        formats = ["Vinyl", "LP"]

    assert not is_cd_release_result(Release())


def test_various_lookup_is_true_for_blank_or_various_artist():
    assert is_various_lookup("")
    assert is_various_lookup("Various Artists")
    assert not is_various_lookup("Radiohead")


def test_score_candidate_rewards_exact_normalized_album_match():
    exact = score_candidate("Daft Punk", "Discovery", "Daft Punk", "Discovery")
    near = score_candidate("Daft Punk", "Discovery", "Other Artist", "Other Album")

    assert exact["combined_score"] > near["combined_score"]
    assert exact["exact_artist"]
    assert exact["exact_title"]


def test_import_fingerprint_changes_with_release_id_not_artist_typo():
    baseline = [{"id": "1", "artist": "A", "title": "B", "release_id": "123"}]
    edited_artist = [{"id": "1", "artist": "Changed", "title": "B", "release_id": "123"}]
    changed_release = [{"id": "1", "artist": "A", "title": "B", "release_id": "456"}]

    assert build_import_request_fingerprint(
        1, baseline
    ) == build_import_request_fingerprint(1, edited_artist)
    assert build_import_request_fingerprint(
        1, baseline
    ) != build_import_request_fingerprint(1, changed_release)
