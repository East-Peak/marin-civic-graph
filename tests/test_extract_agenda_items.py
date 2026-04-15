"""Tests for agenda PDF extraction pipeline.

Tests cover pure text-parsing functions only — no PDF download or Neo4j needed.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from extract_agenda_items import (
    detect_agenda_format,
    parse_granicus_agenda,
    parse_civicplus_agenda,
    build_agenda_item_node,
    normalize_agenda_url,
)


# ---------------------------------------------------------------------------
# detect_agenda_format
# ---------------------------------------------------------------------------

class TestDetectAgendaFormat:
    def test_granicus_format(self):
        text = "A. CONVENE\n   G.1. Approve minutes"
        assert detect_agenda_format(text) == "granicus"

    def test_civicplus_format(self):
        text = "1. CALL TO ORDER\n   4.A. Approve minutes"
        assert detect_agenda_format(text) == "civicplus"

    def test_granicus_full_header(self):
        text = "G. CONSENT CALENDAR\n   G.1.   Approve the minutes\n   G.2.   Accept report"
        assert detect_agenda_format(text) == "granicus"

    def test_civicplus_multi_section(self):
        text = "4. CONSENT CALENDAR\n5. PUBLIC HEARINGS\n   5.A. Zoning variance"
        assert detect_agenda_format(text) == "civicplus"

    def test_unknown_returns_none(self):
        text = "Meeting agenda\nNo discernible structure here."
        assert detect_agenda_format(text) is None


# ---------------------------------------------------------------------------
# parse_granicus_agenda
# ---------------------------------------------------------------------------

class TestParseGranicusAgenda:
    def test_parses_sections(self):
        text = (
            "A. CONVENE\n"
            "B. CLOSED SESSION\n"
            "G. CONSENT CALENDAR\n"
            "   G.1.   Item one\n"
            "   G.2.   Item two\n"
        )
        sections, items = parse_granicus_agenda(text)
        assert len(sections) >= 3
        assert len(items) >= 2

    def test_item_has_fields(self):
        text = (
            "G. CONSENT CALENDAR\n"
            "   G.1.   Approve the minutes of March 10, 2026\n"
        )
        sections, items = parse_granicus_agenda(text)
        assert len(items) >= 1
        item = items[0]
        assert item["section"] == "G"
        assert item["number"] == "1"
        assert "minutes" in item["title"].lower()

    def test_item_captures_section_name(self):
        text = (
            "I. PUBLIC HEARINGS\n"
            "   I.1.   Proposed amendment to zoning ordinance\n"
        )
        sections, items = parse_granicus_agenda(text)
        item = items[0]
        assert item["section_name"] == "PUBLIC HEARINGS"

    def test_multiple_sections_with_items(self):
        text = (
            "G. CONSENT CALENDAR\n"
            "   G.1.   Approve minutes\n"
            "   G.2.   Accept treasurer report\n"
            "J. GENERAL BUSINESS\n"
            "   J.1.   Budget amendment\n"
        )
        sections, items = parse_granicus_agenda(text)
        assert len(sections) >= 2
        assert len(items) >= 3

    def test_empty_text_returns_empty(self):
        sections, items = parse_granicus_agenda("")
        assert sections == []
        assert items == []

    def test_section_has_label_and_name(self):
        text = "G. CONSENT CALENDAR\n   G.1.   Item\n"
        sections, items = parse_granicus_agenda(text)
        section = sections[0]
        assert "label" in section
        assert "name" in section
        assert section["label"] == "G"
        assert section["name"] == "CONSENT CALENDAR"


# ---------------------------------------------------------------------------
# parse_civicplus_agenda
# ---------------------------------------------------------------------------

class TestParseCivicPlusAgenda:
    def test_parses_sections(self):
        text = (
            "1. CALL TO ORDER\n"
            "4. CONSENT CALENDAR\n"
            "   4.A.   Approve minutes\n"
        )
        sections, items = parse_civicplus_agenda(text)
        assert len(items) >= 1

    def test_item_has_fields(self):
        text = (
            "4. CONSENT CALENDAR\n"
            "   4.A.   Approve the minutes of February 18, 2026\n"
        )
        sections, items = parse_civicplus_agenda(text)
        assert len(items) >= 1
        item = items[0]
        assert item["section"] == "4"
        assert item["number"] == "A"
        assert "minutes" in item["title"].lower()

    def test_item_captures_section_name(self):
        text = (
            "5. PUBLIC HEARINGS\n"
            "   5.A.   Zoning variance request\n"
        )
        sections, items = parse_civicplus_agenda(text)
        item = items[0]
        assert item["section_name"] == "PUBLIC HEARINGS"

    def test_multiple_items_in_section(self):
        text = (
            "4. CONSENT CALENDAR\n"
            "   4.A.   Approve minutes\n"
            "   4.B.   Accept financial report\n"
            "   4.C.   Ratify contracts\n"
        )
        sections, items = parse_civicplus_agenda(text)
        assert len(items) >= 3

    def test_empty_text_returns_empty(self):
        sections, items = parse_civicplus_agenda("")
        assert sections == []
        assert items == []


# ---------------------------------------------------------------------------
# build_agenda_item_node
# ---------------------------------------------------------------------------

class TestBuildAgendaItemNode:
    def test_creates_node(self):
        node = build_agenda_item_node(
            meeting_id="meeting-novato-city-council-2193",
            section="G",
            number="1",
            section_name="CONSENT CALENDAR",
            title="Approve the minutes",
            source_id="novato-city-council",
        )
        assert node["node_type"] == "AgendaItem"
        assert "consent" in node["properties"]["heading"].lower()

    def test_id_format(self):
        node = build_agenda_item_node(
            meeting_id="meeting-novato-city-council-2193",
            section="G",
            number="1",
            section_name="CONSENT CALENDAR",
            title="Approve the minutes",
            source_id="novato-city-council",
        )
        # ID should be: agenda-item-{meeting_id_suffix}-{section}{number}
        assert node["id"].startswith("agenda-item-")
        assert "g1" in node["id"].lower()

    def test_properties_have_required_fields(self):
        node = build_agenda_item_node(
            meeting_id="meeting-novato-city-council-2193",
            section="G",
            number="1",
            section_name="CONSENT CALENDAR",
            title="Approve the minutes of the March 10, 2026 meeting",
            source_id="novato-city-council",
        )
        props = node["properties"]
        assert "heading" in props
        assert "title" in props
        assert "section_number" in props
        assert "item_number" in props
        assert "meeting_id" in props
        assert props["meeting_id"] == "meeting-novato-city-council-2193"

    def test_promotion_state(self):
        node = build_agenda_item_node(
            meeting_id="meeting-novato-city-council-2193",
            section="I",
            number="1",
            section_name="PUBLIC HEARINGS",
            title="Variance request",
            source_id="novato-city-council",
        )
        assert node["promotion_state"] == "promoted"

    def test_civicplus_item(self):
        node = build_agenda_item_node(
            meeting_id="meeting-corte-madera-town-council-2025-03-04",
            section="4",
            number="A",
            section_name="CONSENT CALENDAR",
            title="Approve minutes",
            source_id="corte-madera-town-council",
        )
        assert node["node_type"] == "AgendaItem"
        assert node["properties"]["meeting_id"] == "meeting-corte-madera-town-council-2025-03-04"


# ---------------------------------------------------------------------------
# normalize_agenda_url
# ---------------------------------------------------------------------------

class TestNormalizeAgendaUrl:
    def test_prepends_https_to_protocol_relative(self):
        url = "//novato.granicus.com/AgendaViewer.php?view_id=7&clip_id=1422"
        assert normalize_agenda_url(url) == "https://novato.granicus.com/AgendaViewer.php?view_id=7&clip_id=1422"

    def test_leaves_https_url_unchanged(self):
        url = "https://example.com/agenda.pdf"
        assert normalize_agenda_url(url) == url

    def test_leaves_http_url_unchanged(self):
        url = "http://example.com/agenda.pdf"
        assert normalize_agenda_url(url) == url

    def test_none_returns_none(self):
        assert normalize_agenda_url(None) is None
