import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter
from adapters.granicus import (
    strip_tags,
    extract_href,
    extract_onclick_url,
    extract_rows,
    classify_meeting,
    detect_variant,
    parse_legacy,
    parse_legacy_date,
    parse_modern,
    parse_modern_date,
    GranicusAdapter,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestAdapterRegistry:
    def test_get_granicus_adapter(self):
        cls = get_adapter_class("granicus")
        assert cls is not None
        assert issubclass(cls, BaseAdapter)

    def test_unknown_adapter_raises(self):
        with pytest.raises(KeyError):
            get_adapter_class("nonexistent")


class TestBaseAdapterContract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseAdapter({}, Path("."))


class TestStripTags:
    def test_removes_html(self):
        assert strip_tags("<b>hello</b> world") == "hello world"

    def test_decodes_entities(self):
        assert strip_tags("03&nbsp;/&nbsp;24") == "03 / 24"

    def test_collapses_whitespace(self):
        assert strip_tags("  hello   world  ") == "hello world"


class TestExtractHref:
    def test_extracts_href(self):
        html = '<a href="https://example.com/agenda">Agenda</a>'
        assert extract_href(html) == "https://example.com/agenda"

    def test_returns_none_for_no_link(self):
        assert extract_href("<td>empty</td>") is None

    def test_ignores_javascript_void(self):
        html = '<a href="javascript:void(0);" onClick="window.open(\'url\')">Video</a>'
        assert extract_href(html) is None


class TestExtractOnclickUrl:
    def test_extracts_window_open_url(self):
        html = """<a href="javascript:void(0);" onClick="window.open('//marin.granicus.com/MediaPlayer.php?view_id=33&event_id=4204','player')">Video</a>"""
        assert extract_onclick_url(html) == "//marin.granicus.com/MediaPlayer.php?view_id=33&event_id=4204"

    def test_returns_none_for_no_onclick(self):
        assert extract_onclick_url('<a href="http://example.com">Link</a>') is None


class TestClassifyMeeting:
    def test_regular(self):
        assert classify_meeting("Regular Meeting") == "regular"

    def test_special(self):
        assert classify_meeting("Special Meeting") == "special"

    def test_budget(self):
        assert classify_meeting("Budget Hearing") == "budget"

    def test_closed_session(self):
        assert classify_meeting("Closed Session") == "closed_session"

    def test_joint(self):
        assert classify_meeting("Joint Meeting with Planning Commission") == "joint_meeting"

    def test_default_other(self):
        assert classify_meeting("Something Unusual") == "other"


class TestDetectVariant:
    def test_legacy_detected(self):
        html = (FIXTURES / "granicus-marin-county-bos.html").read_text(errors="ignore")
        assert detect_variant(html) == "legacy"

    def test_modern_novato_detected(self):
        html = (FIXTURES / "granicus-novato-city-council.html").read_text(errors="ignore")
        assert detect_variant(html) == "modern"

    def test_modern_sausalito_detected(self):
        html = (FIXTURES / "granicus-sausalito-city-council.html").read_text(errors="ignore")
        assert detect_variant(html) == "modern"


class TestExtractRows:
    def test_extracts_rows_from_legacy(self):
        html = (FIXTURES / "granicus-marin-county-bos.html").read_text(errors="ignore")
        rows = extract_rows(html)
        assert len(rows) > 300

    def test_extracts_rows_from_modern(self):
        html = (FIXTURES / "granicus-novato-city-council.html").read_text(errors="ignore")
        rows = extract_rows(html)
        assert len(rows) > 300

    def test_each_row_is_html_string(self):
        html = (FIXTURES / "granicus-marin-county-bos.html").read_text(errors="ignore")
        rows = extract_rows(html)
        assert rows[0].startswith("<tr")


class TestParseLegacyDate:
    def test_two_digit_year(self):
        assert parse_legacy_date("04/14/26") == "2026-04-14"

    def test_with_time(self):
        assert parse_legacy_date("07/08/25 - 09:00 AM") == "2025-07-08"

    def test_returns_none_for_bad_input(self):
        assert parse_legacy_date("not a date") is None


class TestParseLegacy:
    @pytest.fixture
    def legacy_html(self):
        return (FIXTURES / "granicus-marin-county-bos.html").read_text(errors="ignore")

    def test_returns_meetings_list(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        assert isinstance(meetings, list)
        assert len(meetings) > 200

    def test_meeting_has_required_fields(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        m = meetings[0]
        assert "date" in m
        assert "title" in m
        assert "meeting_type" in m
        assert "artifacts" in m
        assert "source_row_number" in m

    def test_meeting_date_is_iso(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        for m in meetings[:10]:
            if m["date"]:
                assert re.match(r"\d{4}-\d{2}-\d{2}", m["date"])

    def test_respects_backfill_from(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2024-01-01")
        for m in meetings:
            if m["date"]:
                assert m["date"] >= "2024-01-01"

    def test_artifacts_use_available_url_format(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        for m in meetings[:10]:
            for art_name, art in m["artifacts"].items():
                assert "available" in art
                assert "url" in art

    def test_extracts_agenda_urls(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        agendas = [m for m in meetings if m["artifacts"].get("agenda", {}).get("available")]
        assert len(agendas) > 100

    def test_extracts_video_urls(self, legacy_html):
        meetings = parse_legacy(legacy_html, backfill_from="2019-01-01")
        videos = [m for m in meetings if m["artifacts"].get("video", {}).get("available")]
        assert len(videos) > 100


class TestParseModernDate:
    def test_numeric_with_nbsp(self):
        assert parse_modern_date("03\xa0/\xa024\xa0/\xa02026") == "2026-03-24"

    def test_numeric_with_spaces(self):
        assert parse_modern_date("03 / 24 / 2026") == "2026-03-24"

    def test_month_name_abbreviated(self):
        assert parse_modern_date("Apr\xa0 7,\xa02026") == "2026-04-07"

    def test_month_name_full(self):
        assert parse_modern_date("April 14, 2026") == "2026-04-14"

    def test_returns_none_for_bad_input(self):
        assert parse_modern_date("not a date") is None

    def test_handles_time_suffix(self):
        assert parse_modern_date("Apr\xa0 7,\xa02026 - 4:01\xa0PM") == "2026-04-07"


class TestParseModern:
    @pytest.fixture
    def novato_html(self):
        return (FIXTURES / "granicus-novato-city-council.html").read_text(errors="ignore")

    @pytest.fixture
    def sausalito_html(self):
        return (FIXTURES / "granicus-sausalito-city-council.html").read_text(errors="ignore")

    def test_returns_meetings_from_novato(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2019-01-01")
        assert isinstance(meetings, list)
        assert len(meetings) > 200

    def test_returns_meetings_from_sausalito(self, sausalito_html):
        meetings = parse_modern(sausalito_html, backfill_from="2019-01-01")
        assert isinstance(meetings, list)
        assert len(meetings) > 100

    def test_meeting_has_required_fields(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2019-01-01")
        m = meetings[0]
        assert "date" in m
        assert "title" in m
        assert "meeting_type" in m
        assert "artifacts" in m

    def test_meeting_date_is_iso(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2019-01-01")
        dated = [m for m in meetings if m["date"]]
        assert len(dated) > 100
        for m in dated[:20]:
            assert re.match(r"\d{4}-\d{2}-\d{2}", m["date"])

    def test_artifacts_use_available_url_format(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2019-01-01")
        for m in meetings[:10]:
            for art in m["artifacts"].values():
                assert "available" in art
                assert "url" in art

    def test_respects_backfill_from(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2024-01-01")
        for m in meetings:
            if m["date"]:
                assert m["date"] >= "2024-01-01"

    def test_extracts_agenda_urls_novato(self, novato_html):
        meetings = parse_modern(novato_html, backfill_from="2019-01-01")
        agendas = [m for m in meetings if m["artifacts"].get("agenda", {}).get("available")]
        assert len(agendas) > 100

    def test_extracts_minutes_urls_sausalito(self, sausalito_html):
        meetings = parse_modern(sausalito_html, backfill_from="2019-01-01")
        minutes = [m for m in meetings if m["artifacts"].get("minutes", {}).get("available")]
        assert len(minutes) > 30


class TestGranicusAdapterCapture:
    """Integration tests using saved HTML fixtures (no live HTTP)."""

    def _make_adapter(self, source_id, fixture_name, tmp_path):
        config = {
            "id": source_id,
            "adapter": "granicus",
            "url": "https://example.granicus.com/ViewPublisher.php?view_id=1",
            "jurisdiction_id": f"place-{source_id.rsplit('-', 1)[0]}",
            "institution_id": f"org-{source_id}",
            "backfill_from": "2019-01-01",
        }
        adapter = GranicusAdapter(config, tmp_path)
        fixture_path = FIXTURES / fixture_name
        adapter._fetch = lambda url: fixture_path.read_text(errors="ignore")
        return adapter

    def test_legacy_capture_returns_dict(self, tmp_path):
        adapter = self._make_adapter("marin-county-bos", "granicus-marin-county-bos.html", tmp_path)
        result = adapter.capture()
        assert isinstance(result, dict)
        assert result["source_id"] == "marin-county-bos"
        assert result["variant"] == "legacy"

    def test_modern_capture_returns_dict(self, tmp_path):
        adapter = self._make_adapter("novato-city-council", "granicus-novato-city-council.html", tmp_path)
        result = adapter.capture()
        assert isinstance(result, dict)
        assert result["variant"] == "modern"

    def test_capture_has_required_envelope_fields(self, tmp_path):
        adapter = self._make_adapter("marin-county-bos", "granicus-marin-county-bos.html", tmp_path)
        result = adapter.capture()
        assert "capture_id" in result
        assert "source_id" in result
        assert "captured_at" in result
        assert "institution_id" in result
        assert "jurisdiction_id" in result
        assert "meeting_count" in result
        assert "artifact_counts" in result
        assert "meetings" in result
        assert "record_refs" in result
        assert "errors" in result

    def test_capture_meeting_count_matches(self, tmp_path):
        adapter = self._make_adapter("marin-county-bos", "granicus-marin-county-bos.html", tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] == len(result["meetings"])
        assert result["meeting_count"] > 200

    def test_capture_writes_raw_html(self, tmp_path):
        adapter = self._make_adapter("marin-county-bos", "granicus-marin-county-bos.html", tmp_path)
        adapter.capture()
        raw_files = list((tmp_path / "data" / "raw" / "marin-county-bos").rglob("source.html"))
        assert len(raw_files) == 1

    def test_capture_record_refs_present(self, tmp_path):
        adapter = self._make_adapter("marin-county-bos", "granicus-marin-county-bos.html", tmp_path)
        result = adapter.capture()
        assert len(result["record_refs"]) >= 1
        ref = result["record_refs"][0]
        assert "id" in ref
        assert "record_type" in ref
        assert ref["record_type"] == "meeting_archive_page"

    def test_novato_meeting_count_reasonable(self, tmp_path):
        adapter = self._make_adapter("novato-city-council", "granicus-novato-city-council.html", tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] > 200

    def test_sausalito_meeting_count_reasonable(self, tmp_path):
        adapter = self._make_adapter("sausalito-city-council", "granicus-sausalito-city-council.html", tmp_path)
        result = adapter.capture()
        assert result["meeting_count"] > 100

    def test_capture_meetings_have_institution_id(self, tmp_path):
        adapter = self._make_adapter("novato-city-council", "granicus-novato-city-council.html", tmp_path)
        result = adapter.capture()
        for m in result["meetings"][:5]:
            assert m["institution_id"] == "org-novato-city-council"

    def test_capture_meetings_have_meeting_id(self, tmp_path):
        adapter = self._make_adapter("novato-city-council", "granicus-novato-city-council.html", tmp_path)
        result = adapter.capture()
        for m in result["meetings"][:5]:
            assert "meeting_id" in m
            assert m["meeting_id"].startswith("meeting-")
