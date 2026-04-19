import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_record_preferred_urls import (
    _build_jurisdiction_index,
    build_display_label,
    normalize_public_url,
    normalize_public_url_with_registry,
)


def test_https_url_passes_through():
    assert normalize_public_url("https://example.gov/foo.pdf") == "https://example.gov/foo.pdf"


def test_http_url_passes_through():
    assert normalize_public_url("http://example.gov/foo.pdf") == "http://example.gov/foo.pdf"


def test_protocol_relative_promoted_to_https():
    assert normalize_public_url("//example.gov/foo.pdf") == "https://example.gov/foo.pdf"


def test_relative_path_returns_none():
    assert normalize_public_url("/local/file.pdf") is None


def test_empty_returns_none():
    assert normalize_public_url("") is None
    assert normalize_public_url(None) is None


def test_display_label_from_record_type_and_extension():
    assert build_display_label("staff_report", "https://x.gov/doc.pdf") == "Staff report PDF"
    assert build_display_label("minutes", "https://x.gov/mins.html") == "Minutes page"
    assert build_display_label("agenda_packet", "") == "Agenda packet"


# --- Registry fallback tests (Task 6) ---


def test_registry_fallback_uses_source_id_adapter_entry():
    """Record with no source_url but source_id matches a registry adapter entry."""
    registry = {
        "marin-county-bos": {
            "id": "marin-county-bos",
            "adapter": "granicus",
            "url": "https://marin.granicus.com/ViewPublisher.php?view_id=33",
            "jurisdiction_id": "place-marin-county",
        },
    }
    props = {
        "id": "record-marin-bos-archive-page",
        "source_url": None,
        "source_id": "marin-county-bos",
        "record_type": "meeting_archive_page",
    }
    url = normalize_public_url_with_registry(props, registry)
    assert url == "https://marin.granicus.com/ViewPublisher.php?view_id=33"


def test_registry_fallback_uses_sources_yaml_entry_url():
    """Record with no source_url but source_id matches sources.yaml entry_url."""
    registry = {
        "san-rafael-700-irwin-project-page": {
            "source_id": "san-rafael-700-irwin-project-page",
            "entry_url": "https://www.cityofsanrafael.org/planning/700-irwin-st/",
            "jurisdiction_id": "san-rafael",
        },
    }
    props = {
        "id": "record-700-irwin-project-page",
        "source_url": None,
        "source_id": "san-rafael-700-irwin-project-page",
        "record_type": "project_page",
    }
    url = normalize_public_url_with_registry(props, registry)
    assert url == "https://www.cityofsanrafael.org/planning/700-irwin-st/"


def test_registry_fallback_returns_none_when_no_match():
    """source_id has no registry entry — fall through to None."""
    registry = {}
    props = {
        "id": "record-xxx",
        "source_url": None,
        "source_id": "something-unregistered",
    }
    assert normalize_public_url_with_registry(props, registry) is None


def test_registry_fallback_returns_none_when_no_source_id():
    """No source_id at all — nothing to look up."""
    registry = {"marin-county-bos": {"url": "https://marin.granicus.com/x"}}
    props = {"id": "record-orphan", "source_url": None, "source_id": None}
    assert normalize_public_url_with_registry(props, registry) is None


def test_existing_url_wins_over_registry():
    """A real source_url preempts any registry lookup."""
    registry = {
        "marin-county-bos": {"url": "https://marin.granicus.com/x"},
    }
    props = {
        "id": "record-a",
        "source_url": "https://example.gov/doc.pdf",
        "source_id": "marin-county-bos",
    }
    assert normalize_public_url_with_registry(props, registry) == "https://example.gov/doc.pdf"


def test_protocol_relative_normalized_ahead_of_registry():
    """Protocol-relative source_url normalizes to https and beats the registry."""
    registry = {"marin-county-bos": {"url": "https://marin.granicus.com/x"}}
    props = {
        "id": "record-a",
        "source_url": "//example.gov/doc.pdf",
        "source_id": "marin-county-bos",
    }
    assert (
        normalize_public_url_with_registry(props, registry)
        == "https://example.gov/doc.pdf"
    )


def test_registry_fallback_skips_non_http_registry_urls():
    """A registry entry without an http(s) URL is skipped (defensive)."""
    registry = {
        "weird-source": {
            "source_id": "weird-source",
            "entry_url": "ftp://example.gov/x",
        },
    }
    props = {"id": "record-a", "source_url": None, "source_id": "weird-source"}
    assert normalize_public_url_with_registry(props, registry) is None


def test_registry_fallback_prefers_url_then_entry_url():
    """Adapter yamls use 'url'; sources.yaml uses 'entry_url'. Either is acceptable."""
    # url field present
    registry1 = {"s1": {"url": "https://a.gov/"}}
    props1 = {"id": "r1", "source_url": None, "source_id": "s1"}
    assert normalize_public_url_with_registry(props1, registry1) == "https://a.gov/"

    # only entry_url present
    registry2 = {"s2": {"entry_url": "https://b.gov/"}}
    props2 = {"id": "r2", "source_url": None, "source_id": "s2"}
    assert normalize_public_url_with_registry(props2, registry2) == "https://b.gov/"


# --- Jurisdiction fallback tests (Codex round 1 fix 8) ---


def test_jurisdiction_index_built_from_registry():
    registry = {
        "marin-bos": {
            "id": "marin-bos",
            "url": "https://marin.granicus.com/x",
            "jurisdiction_id": "place-marin-county",
        },
        "sausalito-cc": {
            "id": "sausalito-cc",
            "url": "https://sausalito.granicus.com/y",
            "jurisdiction_id": "place-sausalito",
        },
    }
    idx = _build_jurisdiction_index(registry)
    assert idx["place-marin-county"]["url"] == "https://marin.granicus.com/x"
    assert idx["place-sausalito"]["url"] == "https://sausalito.granicus.com/y"


def test_jurisdiction_fallback_used_when_source_id_missing():
    """Record with no source_url AND no source_id, but a linked Place id."""
    registry = {
        "marin-bos": {
            "url": "https://marin.granicus.com/x",
            "jurisdiction_id": "place-marin-county",
        },
    }
    idx = _build_jurisdiction_index(registry)
    props = {
        "id": "record-abc",
        "source_url": None,
        "source_id": None,
        "jurisdiction_id": "place-marin-county",
    }
    assert (
        normalize_public_url_with_registry(props, registry, idx)
        == "https://marin.granicus.com/x"
    )


def test_source_id_wins_over_jurisdiction_fallback():
    """source_id match is preferred even when jurisdiction also resolves."""
    registry = {
        "source-a": {
            "url": "https://specific.example/a",
            "jurisdiction_id": "place-marin-county",
        },
        "source-b": {
            "url": "https://marin.granicus.com/landing",
            "jurisdiction_id": "place-marin-county",
        },
    }
    idx = _build_jurisdiction_index(registry)
    props = {
        "id": "record-a",
        "source_url": None,
        "source_id": "source-a",
        "jurisdiction_id": "place-marin-county",
    }
    assert (
        normalize_public_url_with_registry(props, registry, idx)
        == "https://specific.example/a"
    )


def test_jurisdiction_fallback_returns_none_when_not_indexed():
    registry = {"marin-bos": {"url": "https://x.gov", "jurisdiction_id": "place-marin-county"}}
    idx = _build_jurisdiction_index(registry)
    props = {
        "id": "record-orphan",
        "source_url": None,
        "source_id": None,
        "jurisdiction_id": "place-unknown",
    }
    assert normalize_public_url_with_registry(props, registry, idx) is None


def test_no_jurisdiction_index_means_no_fallback():
    """Callers that don't pass a jurisdiction_index keep the old behavior."""
    registry = {}
    props = {
        "id": "record-x",
        "source_url": None,
        "source_id": None,
        "jurisdiction_id": "place-marin-county",
    }
    assert normalize_public_url_with_registry(props, registry) is None
