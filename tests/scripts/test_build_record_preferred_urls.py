import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_record_preferred_urls import normalize_public_url, build_display_label


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
