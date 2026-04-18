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
    parse_bos_agenda,
    parse_fairfax_agenda,
    build_agenda_item_node,
    normalize_agenda_url,
)


# ---------------------------------------------------------------------------
# detect_agenda_format
# ---------------------------------------------------------------------------

class TestDetectAgendaFormat:
    def test_granicus_format(self):
        text = "A. CONVENE\n   G.1. Approve minutes\n   G.2. Accept report"
        assert detect_agenda_format(text) == "granicus"

    def test_civicplus_format(self):
        text = "1. CALL TO ORDER\n   4.A. Approve minutes\n   4.B. Accept report"
        assert detect_agenda_format(text) == "civicplus"

    def test_granicus_full_header(self):
        text = "G. CONSENT CALENDAR\n   G.1.   Approve the minutes\n   G.2.   Accept report"
        assert detect_agenda_format(text) == "granicus"

    def test_civicplus_multi_section(self):
        text = "4. CONSENT CALENDAR\n5. PUBLIC HEARINGS\n   5.A. Zoning variance\n   5.B. Use permit"
        assert detect_agenda_format(text) == "civicplus"

    def test_unknown_returns_none(self):
        text = "Meeting agenda\nNo discernible structure here."
        assert detect_agenda_format(text) is None

    def test_sausalito_civicplus_not_fairfax(self):
        """Sausalito uses CivicPlus format — must NOT be detected as fairfax."""
        text = (
            "1. CALL TO ORDER\n"
            "2. ROLL CALL\n"
            "3. CONSENT CALENDAR\n"
            "   3.A Approve the minutes of February 11, 2025\n"
            "   3.B Accept the Treasurer's monthly report\n"
            "   3.C Ratify purchase orders\n"
            "4. PUBLIC HEARINGS\n"
            "   4.A Proposed amendment to zoning ordinance\n"
            "5. ADJOURNMENT\n"
        )
        fmt = detect_agenda_format(text)
        assert fmt != "fairfax", f"Sausalito should not detect as fairfax, got {fmt}"
        assert fmt == "civicplus"

    def test_bos_not_fairfax(self):
        """BOS uses CA-N format — must NOT be detected as fairfax."""
        text = (
            "Consent Agenda A\n"
            "CA - 1. Director of Public Works requests approval\n"
            "CA - 2. County Counsel reports on litigation\n"
            "CA - 3. County Administrator recommends adoption\n"
            "CA - 4. Auditor-Controller submits quarterly report\n"
            "Public Hearing\n"
            "Request to approve variance for 123 Main St\n"
        )
        fmt = detect_agenda_format(text)
        assert fmt != "fairfax", f"BOS should not detect as fairfax, got {fmt}"
        assert fmt == "bos"

    def test_fairfax_simple_numbered(self):
        """Fairfax uses simple numbered items with section keywords."""
        text = (
            "CONSENT CALENDAR\n"
            "3. Approve the minutes of March 5, 2025\n"
            "4. Accept financial report for February 2025\n"
            "5. Ratify purchase orders\n"
            "PUBLIC HEARING\n"
            "6. Zoning amendment for downtown overlay district\n"
            "7. Use permit application for 123 Main Street\n"
            "ADJOURNMENT\n"
        )
        fmt = detect_agenda_format(text)
        assert fmt == "fairfax"

    def test_civicplus_items_beat_fairfax(self):
        """When text has N.LETTER sub-items, civicplus wins over fairfax."""
        text = (
            "1. CALL TO ORDER\n"
            "2. CONSENT CALENDAR\n"
            "   2.A Approve the minutes\n"
            "   2.B Accept report\n"
            "3. PUBLIC HEARING\n"
            "   3.A Zoning variance request\n"
            "4. ADJOURNMENT\n"
        )
        assert detect_agenda_format(text) == "civicplus"

    def test_granicus_items_beat_fairfax(self):
        """When text has LETTER.N sub-items, granicus wins over fairfax."""
        text = (
            "A. CONVENE\n"
            "G. CONSENT CALENDAR\n"
            "   G.1.   Approve minutes\n"
            "   G.2.   Accept report\n"
            "   G.3.   Ratify contracts\n"
            "I. PUBLIC HEARINGS\n"
            "   I.1.   Zoning variance\n"
            "ADJOURNMENT\n"
        )
        assert detect_agenda_format(text) == "granicus"


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
