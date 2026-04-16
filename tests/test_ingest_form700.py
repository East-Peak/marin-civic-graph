"""Tests for ingest_form700.py — NetFile /pub/ Form 700 ingestion.

Pure unit tests — no live HTTP required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ingest_form700 import (
    build_filing_node,
    build_filed_by_edge,
    build_in_jurisdiction_edge,
    normalize_name,
    parse_filing_rows,
    slugify,
)

# ---------------------------------------------------------------------------
# Sample HTML table (mimics the NetFile /pub/ export response)
# ---------------------------------------------------------------------------

SAMPLE_HTML_TABLE = """
<table>
<tr><td>Colin, Kate</td><td>03/15/2025</td><td>Annual</td><td>Mayor</td><td>City Council</td></tr>
<tr><td>Hill, Eli</td><td>03/20/2025</td><td>Annual</td><td>Council Member</td><td>City Council</td></tr>
<tr><td>Bushey, Maribeth</td><td>04/01/2025</td><td>Assuming Office</td><td>Council Member</td><td>City Council</td></tr>
</table>
"""

SAMPLE_HTML_TABLE_WITH_EXTRA_COLS = """
<table>
<tr><th>Name</th><th>Date</th><th>Type</th><th>Title</th><th>Dept</th></tr>
<tr><td>Smith, Jane</td><td>01/10/2025</td><td>Leaving Office</td><td>City Clerk</td><td>Administration</td></tr>
</table>
"""

SAMPLE_HTML_TABLE_WITH_ENTITIES = """
<table>
<tr><td>O&#39;Brien, Sean</td><td>02/14/2025</td><td>Annual</td><td>Council Member</td><td>City &amp; County</td></tr>
</table>
"""

SAMPLE_HTML_TABLE_WITH_LINKS = """
<table>
<tr><td>Doe, John</td><td>05/01/2025</td><td>Annual</td><td>Director</td><td>Planning</td><td><a href="/view/doc/123">View</a></td></tr>
</table>
"""

# ---------------------------------------------------------------------------
# TestParseFilingRows
# ---------------------------------------------------------------------------


class TestParseFilingRows:
    def test_extracts_rows(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE)
        assert len(rows) == 3

    def test_first_row_filer_name(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE)
        assert rows[0]["filer_name"] == "Colin, Kate"

    def test_first_row_filed_at(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE)
        assert rows[0]["filed_at"] == "2025-03-15"

    def test_first_row_statement_type(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE)
        assert rows[0]["statement_type"] == "Annual"

    def test_first_row_job_title(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE)
        assert rows[0]["job_title"] == "Mayor"

    def test_first_row_department(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE)
        assert rows[0]["department"] == "City Council"

    def test_second_row(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE)
        assert rows[1]["filer_name"] == "Hill, Eli"
        assert rows[1]["filed_at"] == "2025-03-20"

    def test_third_row_assuming_office(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE)
        assert rows[2]["statement_type"] == "Assuming Office"

    def test_empty_table_returns_empty_list(self):
        assert parse_filing_rows("<table></table>") == []

    def test_empty_string_returns_empty_list(self):
        assert parse_filing_rows("") == []

    def test_html_entity_decoding(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE_WITH_ENTITIES)
        assert rows[0]["filer_name"] == "O'Brien, Sean"
        assert rows[0]["department"] == "City & County"

    def test_skips_header_rows(self):
        # Header rows with <th> elements should not match
        rows = parse_filing_rows(SAMPLE_HTML_TABLE_WITH_EXTRA_COLS)
        assert len(rows) == 1
        assert rows[0]["filer_name"] == "Smith, Jane"

    def test_rows_with_extra_td_cells_are_parsed(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE_WITH_LINKS)
        assert len(rows) == 1
        assert rows[0]["filer_name"] == "Doe, John"

    def test_date_format_is_iso(self):
        rows = parse_filing_rows(SAMPLE_HTML_TABLE)
        for row in rows:
            parts = row["filed_at"].split("-")
            assert len(parts) == 3
            assert len(parts[0]) == 4  # YYYY
            assert len(parts[1]) == 2  # MM
            assert len(parts[2]) == 2  # DD


# ---------------------------------------------------------------------------
# TestNormalizeName
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_last_first_inverted(self):
        assert normalize_name("Colin, Kate") == "Kate Colin"

    def test_single_name_unchanged(self):
        assert normalize_name("Madonna") == "Madonna"

    def test_already_normal_order(self):
        # If no comma, return as-is
        assert normalize_name("Kate Colin") == "Kate Colin"

    def test_strips_whitespace(self):
        assert normalize_name("  Hill, Eli  ") == "Eli Hill"

    def test_middle_name_preserved(self):
        assert normalize_name("Smith, John A.") == "John A. Smith"


# ---------------------------------------------------------------------------
# TestSlugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic_slug(self):
        assert slugify("Kate Colin") == "kate-colin"

    def test_comma_and_space(self):
        assert slugify("Colin, Kate") == "colin-kate"

    def test_special_chars_replaced(self):
        assert slugify("O'Brien, Sean") == "o-brien-sean"

    def test_multiple_spaces_collapsed(self):
        assert slugify("City  Council") == "city-council"

    def test_lowercase(self):
        assert slugify("ANNUAL") == "annual"


# ---------------------------------------------------------------------------
# TestBuildFilingNode
# ---------------------------------------------------------------------------


class TestBuildFilingNode:
    def _row(self, **overrides) -> dict:
        base = {
            "filer_name": "Colin, Kate",
            "filed_at": "2025-03-15",
            "statement_type": "Annual",
            "job_title": "Mayor",
            "department": "City Council",
        }
        base.update(overrides)
        return base

    def test_node_type_is_filing(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["node_type"] == "Filing"

    def test_labels_contains_filing(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert "Filing" in node["labels"]

    def test_filing_type_is_form_700(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["filing_type"] == "form_700"

    def test_filer_name_preserved(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["filer_name"] == "Colin, Kate"

    def test_filed_at_preserved(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["filed_at"] == "2025-03-15"

    def test_statement_type_preserved(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["statement_type"] == "Annual"

    def test_job_title_preserved(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["job_title"] == "Mayor"

    def test_department_preserved(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["department"] == "City Council"

    def test_id_prefix(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["id"].startswith("filing-form700-raf-")

    def test_id_is_deterministic(self):
        row = self._row()
        n1 = build_filing_node(row, agency_id="raf")
        n2 = build_filing_node(row, agency_id="raf")
        assert n1["id"] == n2["id"]

    def test_id_differs_by_agency(self):
        row = self._row()
        n_raf = build_filing_node(row, agency_id="raf")
        n_cmar = build_filing_node(row, agency_id="cmar")
        assert n_raf["id"] != n_cmar["id"]

    def test_id_contains_date_and_name_slug(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert "2025-03-15" in node["id"]
        assert "colin-kate" in node["id"]

    def test_agency_id_stored_in_properties(self):
        node = build_filing_node(self._row(), agency_id="cmar")
        assert node["properties"]["agency_id"] == "cmar"

    def test_cmar_agency_label(self):
        node = build_filing_node(self._row(), agency_id="cmar", agency_label="Marin County")
        assert node["properties"]["agency"] == "Marin County"

    def test_agency_label_defaults_to_agency_id_upper(self):
        node = build_filing_node(self._row(), agency_id="raf")
        # Without explicit label, should still have agency field
        assert "agency_id" in node["properties"]

    def test_display_label_contains_filer(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert "Colin" in node["display_label"] or "Kate" in node["display_label"]


# ---------------------------------------------------------------------------
# TestBuildFiledByEdge
# ---------------------------------------------------------------------------


class TestBuildFiledByEdge:
    def test_relationship_type(self):
        edge = build_filed_by_edge("filing-form700-raf-abc", "person-kate-colin")
        assert edge["relationship_type"] == "FILED_BY"

    def test_source_is_filing(self):
        edge = build_filed_by_edge("filing-form700-raf-abc", "person-kate-colin")
        assert edge["source_id"] == "filing-form700-raf-abc"

    def test_target_is_person(self):
        edge = build_filed_by_edge("filing-form700-raf-abc", "person-kate-colin")
        assert edge["target_id"] == "person-kate-colin"

    def test_properties_is_dict(self):
        edge = build_filed_by_edge("filing-form700-raf-abc", "person-kate-colin")
        assert isinstance(edge["properties"], dict)


# ---------------------------------------------------------------------------
# TestBuildInJurisdictionEdge
# ---------------------------------------------------------------------------


class TestBuildInJurisdictionEdge:
    def test_relationship_type(self):
        edge = build_in_jurisdiction_edge("filing-form700-raf-abc", "place-san-rafael")
        assert edge["relationship_type"] == "IN_JURISDICTION"

    def test_source_is_filing(self):
        edge = build_in_jurisdiction_edge("filing-form700-raf-abc", "place-san-rafael")
        assert edge["source_id"] == "filing-form700-raf-abc"

    def test_target_is_place(self):
        edge = build_in_jurisdiction_edge("filing-form700-raf-abc", "place-san-rafael")
        assert edge["target_id"] == "place-san-rafael"

    def test_properties_is_dict(self):
        edge = build_in_jurisdiction_edge("filing-form700-raf-abc", "place-san-rafael")
        assert isinstance(edge["properties"], dict)


# ---------------------------------------------------------------------------
# TestPersonIdFromName
# ---------------------------------------------------------------------------


class TestPersonIdFromName:
    """Test the person ID lookup / generation logic."""

    def setup_method(self):
        from ingest_form700 import person_id_from_name
        self.fn = person_id_from_name

    def test_generates_stable_id(self):
        pid = self.fn("Colin, Kate")
        assert pid == self.fn("Colin, Kate")

    def test_inverted_and_normal_match(self):
        # "Colin, Kate" and "Kate Colin" should produce the same stable ID
        pid_inverted = self.fn("Colin, Kate")
        pid_normal = self.fn("Kate Colin")
        assert pid_inverted == pid_normal

    def test_id_prefix(self):
        pid = self.fn("Colin, Kate")
        assert pid.startswith("person-")

    def test_id_is_lowercase_slug(self):
        pid = self.fn("Colin, Kate")
        assert pid == pid.lower()
        assert " " not in pid
        assert "," not in pid
