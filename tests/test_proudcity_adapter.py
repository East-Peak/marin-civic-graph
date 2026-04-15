"""Tests for the ProudCity WordPress adapter."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter
from adapters.proudcity import (
    extract_meeting_urls,
    parse_meeting_date_from_title,
    extract_artifacts_from_detail,
    ProudCityAdapter,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestRegistry:
    def test_proudcity_registered(self):
        cls = get_adapter_class("proudcity")
        assert issubclass(cls, BaseAdapter)


class TestParseMeetingDateFromTitle:
    def test_standard_format(self):
        assert parse_meeting_date_from_title("Town Council Meeting: January 8, 2025") == "2025-01-08"

    def test_dash_separated(self):
        assert parse_meeting_date_from_title("City Council - April 6, 2026") == "2026-04-06"

    def test_no_date_returns_none(self):
        assert parse_meeting_date_from_title("Special Joint Session") is None

    def test_month_day_year(self):
        assert parse_meeting_date_from_title("Planning Commission Meeting: December 15, 2023") == "2023-12-15"


class TestExtractMeetingUrls:
    def test_belvedere_has_meetings(self):
        html = (FIXTURES / "wordpress-belvedere.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://www.cityofbelvedere.org")
        assert len(meetings) > 0

    def test_meeting_entry_has_url_and_title(self):
        html = (FIXTURES / "wordpress-belvedere.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://www.cityofbelvedere.org")
        if meetings:
            m = meetings[0]
            assert "url" in m
            assert "title" in m
            assert "/meetings/" in m["url"]

    def test_fairfax_fixture_returns_list(self):
        html = (FIXTURES / "wordpress-fairfax.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://townoffairfaxca.gov")
        # The main /meetings/ page may show upcoming /event/ links — either way, a list
        assert isinstance(meetings, list)

    def test_no_duplicate_urls(self):
        html = (FIXTURES / "wordpress-belvedere.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://www.cityofbelvedere.org")
        urls = [m["url"] for m in meetings]
        assert len(urls) == len(set(urls))

    def test_date_extracted_from_title(self):
        html = (FIXTURES / "wordpress-belvedere.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://www.cityofbelvedere.org")
        dated = [m for m in meetings if m["date"]]
        assert len(dated) > 0


class TestExtractArtifactsFromDetail:
    def test_extracts_gcs_pdf_urls(self):
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        assert isinstance(artifacts, dict)
        # Should find at least one available artifact
        has_any = any(a.get("available") for a in artifacts.values())
        assert has_any

    def test_artifact_format(self):
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        for art in artifacts.values():
            assert "available" in art
            assert "url" in art

    def test_gcs_url_pattern(self):
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        for art in artifacts.values():
            if art["available"] and art["url"]:
                assert (
                    "storage.googleapis.com" in art["url"]
                    or "proudcity" in art["url"]
                    or art["url"].startswith("http")
                )

    def test_known_tabs_present(self):
        """Tab sections present in fixture are correctly detected."""
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        # The fixture has tab-agenda-packet with a PDF
        assert "packet" in artifacts
        assert artifacts["packet"]["available"] is True


class TestProudCityAdapterCapture:
    def _make_adapter(self, source_id, list_html, detail_htmls, tmp_path, archive_pages=None):
        config = {
            "id": source_id,
            "adapter": "proudcity",
            "url": "https://example.gov/meetings/",
            "jurisdiction_id": "place-test",
            "institution_id": f"org-{source_id}",
            "backfill_from": "2019-01-01",
        }
        if archive_pages:
            config["archive_pages"] = archive_pages
        adapter = ProudCityAdapter(config, tmp_path)
        adapter._request_delay = 0
        # Mock: list page returns list_html, detail pages return from dict
        adapter._fetch_page = lambda url: detail_htmls.get(url, list_html)
        return adapter

    def test_capture_returns_dict(self, tmp_path):
        list_html = '''
        <table>
        <tr><td><a href="/meetings/test-meeting-january-5-2025/">Test Meeting: January 5, 2025</a></td></tr>
        </table>
        '''
        detail_html = '''
        <div id="tab-agenda">
            <a href="https://storage.googleapis.com/proudcity/testca/uploads/2025/01/agenda.pdf">Agenda</a>
        </div>
        '''
        adapter = self._make_adapter("test-city", list_html,
            {"https://example.gov/meetings/test-meeting-january-5-2025/": detail_html}, tmp_path)
        result = adapter.capture()
        assert isinstance(result, dict)
        assert result["adapter"] == "proudcity"

    def test_capture_has_required_fields(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Meeting: March 1, 2025</a></td></tr></table>'
        detail = '<div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/agenda.pdf">PDF</a></div>'
        adapter = self._make_adapter("test", list_html,
            {"https://example.gov/meetings/m1/": detail}, tmp_path)
        result = adapter.capture()
        for field in ["capture_id", "source_id", "captured_at", "institution_id",
                      "meeting_count", "meetings", "record_refs", "errors"]:
            assert field in result

    def test_capture_extracts_artifacts(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Council: February 10, 2025</a></td></tr></table>'
        detail = '''
        <div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/agenda.pdf">PDF</a></div>
        <div id="tab-minutes"><a href="https://storage.googleapis.com/proudcity/x/minutes.pdf">PDF</a></div>
        '''
        adapter = self._make_adapter("test", list_html,
            {"https://example.gov/meetings/m1/": detail}, tmp_path)
        result = adapter.capture()
        m = result["meetings"][0]
        assert m["artifacts"]["agenda"]["available"] is True
        assert m["artifacts"]["minutes"]["available"] is True

    def test_capture_uses_archive_pages(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Meeting: March 1, 2025</a></td></tr></table>'
        archive_html = '<table><tr><td><a href="/meetings/m2/">Meeting: June 5, 2024</a></td></tr></table>'
        detail = '<div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/a.pdf">PDF</a></div>'
        adapter = self._make_adapter(
            "test", list_html,
            {
                "https://example.gov/meetings/m1/": detail,
                "https://example.gov/meetings/m2/": detail,
                "https://example.gov/2024-archive/": archive_html,
            },
            tmp_path,
            archive_pages=["https://example.gov/2024-archive/"],
        )
        result = adapter.capture()
        assert result["meeting_count"] == 2

    def test_capture_filters_by_backfill(self, tmp_path):
        list_html = '''
        <table>
        <tr><td><a href="/meetings/old/">Meeting: January 5, 2018</a></td></tr>
        <tr><td><a href="/meetings/new/">Meeting: March 1, 2025</a></td></tr>
        </table>
        '''
        detail = '<div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/a.pdf">PDF</a></div>'
        adapter = self._make_adapter("test", list_html,
            {
                "https://example.gov/meetings/old/": detail,
                "https://example.gov/meetings/new/": detail,
            },
            tmp_path)
        result = adapter.capture()
        # 2018 meeting filtered out, only 2025 remains
        assert result["meeting_count"] == 1
        assert result["meetings"][0]["date"] == "2025-03-01"

    def test_capture_handles_fetch_error(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Meeting: March 1, 2025</a></td></tr></table>'

        def bad_fetch(url):
            if "m1" in url:
                raise ConnectionError("timeout")
            return list_html

        config = {
            "id": "test",
            "adapter": "proudcity",
            "url": "https://example.gov/meetings/",
            "jurisdiction_id": "place-test",
            "institution_id": "org-test",
            "backfill_from": "2019-01-01",
        }
        adapter = ProudCityAdapter(config, tmp_path)
        adapter._request_delay = 0
        adapter._fetch_page = bad_fetch
        result = adapter.capture()
        assert len(result["errors"]) == 1
        assert result["meetings"][0]["artifacts"]["agenda"]["available"] is False
