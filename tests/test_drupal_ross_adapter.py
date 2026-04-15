"""Tests for the Drupal (Ross) adapter."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter
from adapters.drupal_ross import extract_ross_meetings, parse_ross_date, DrupalRossAdapter

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestRegistry:
    def test_drupal_ross_registered(self):
        cls = get_adapter_class("drupal_ross")
        assert issubclass(cls, BaseAdapter)


class TestParseRossDate:
    def test_iso_content_attribute(self):
        assert parse_ross_date("2026-04-02T18:00:00-07:00") == "2026-04-02"

    def test_display_format(self):
        assert parse_ross_date("04/02/2026 - 6:00pm") == "2026-04-02"

    def test_returns_none_for_bad_input(self):
        assert parse_ross_date("not a date") is None


class TestExtractRossMeetings:
    def test_extracts_meetings_from_fixture(self):
        html = (FIXTURES / "drupal-ross.html").read_text(errors="ignore")
        meetings = extract_ross_meetings(html, "https://townofrossca.gov")
        assert len(meetings) > 5

    def test_meeting_has_required_fields(self):
        html = (FIXTURES / "drupal-ross.html").read_text(errors="ignore")
        meetings = extract_ross_meetings(html, "https://townofrossca.gov")
        if meetings:
            m = meetings[0]
            assert "date" in m
            assert "title" in m
            assert "artifacts" in m

    def test_artifacts_use_available_url_format(self):
        html = (FIXTURES / "drupal-ross.html").read_text(errors="ignore")
        meetings = extract_ross_meetings(html, "https://townofrossca.gov")
        for m in meetings[:5]:
            for art in m["artifacts"].values():
                assert "available" in art
                assert "url" in art


class TestDrupalRossCapture:
    def test_capture_returns_dict(self, tmp_path):
        config = {
            "id": "ross-town-council",
            "adapter": "drupal_ross",
            "url": "https://townofrossca.gov/meetings",
            "jurisdiction_id": "place-ross",
            "institution_id": "org-ross-town-council",
            "backfill_from": "2019-01-01",
        }
        adapter = DrupalRossAdapter(config, tmp_path)
        fixture = (FIXTURES / "drupal-ross.html").read_text(errors="ignore")
        adapter._fetch_page = lambda url: fixture
        result = adapter.capture()
        assert isinstance(result, dict)
        assert result["adapter"] == "drupal_ross"
        assert result["meeting_count"] > 5

    def test_capture_has_required_fields(self, tmp_path):
        config = {
            "id": "ross-town-council",
            "adapter": "drupal_ross",
            "url": "https://townofrossca.gov/meetings",
            "jurisdiction_id": "place-ross",
            "institution_id": "org-ross-town-council",
            "backfill_from": "2019-01-01",
        }
        adapter = DrupalRossAdapter(config, tmp_path)
        fixture = (FIXTURES / "drupal-ross.html").read_text(errors="ignore")
        adapter._fetch_page = lambda url: fixture
        result = adapter.capture()
        for field in [
            "capture_id",
            "source_id",
            "captured_at",
            "institution_id",
            "meeting_count",
            "meetings",
            "record_refs",
            "errors",
        ]:
            assert field in result
