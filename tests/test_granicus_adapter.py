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
