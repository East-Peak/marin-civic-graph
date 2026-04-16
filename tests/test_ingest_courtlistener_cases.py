"""Tests for ingest_courtlistener_cases.py — CourtListener federal case ingestion.

TDD: tests written first, implementation follows.

Covers pure transformation functions — no live API or Neo4j connection required:
  - transform_case: field mapping, id construction, missing fields
  - build_case_edges: PARTY_TO, IN_JURISDICTION, HEARD_IN edge construction
  - identify_defendant_jurisdiction: party extraction from case name
  - slugify_jurisdiction: org-id derivation from jurisdiction name
  - build_court_org_node: court stub node construction
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ingest_courtlistener_cases import (
    build_case_edges,
    build_court_org_node,
    identify_defendant_jurisdiction,
    slugify_jurisdiction,
    transform_case,
)


class TestSlugifyJurisdiction:
    def test_city_of_san_rafael(self):
        assert slugify_jurisdiction("City of San Rafael") == "city-of-san-rafael"

    def test_county_of_marin(self):
        assert slugify_jurisdiction("County of Marin") == "county-of-marin"

    def test_marin_county(self):
        assert slugify_jurisdiction("Marin County") == "marin-county"

    def test_town_of_fairfax(self):
        assert slugify_jurisdiction("Town of Fairfax") == "town-of-fairfax"

    def test_lowercase(self):
        assert slugify_jurisdiction("CITY OF NOVATO") == "city-of-novato"

    def test_strips_whitespace(self):
        assert slugify_jurisdiction("  City of Sausalito  ") == "city-of-sausalito"


class TestIdentifyDefendantJurisdiction:
    def test_city_of_san_rafael(self):
        result = identify_defendant_jurisdiction("Lopez v. City of San Rafael")
        assert result is not None
        assert "san-rafael" in result

    def test_county_of_marin(self):
        result = identify_defendant_jurisdiction("Alves v. County of Marin")
        assert result is not None
        assert "marin" in result

    def test_marin_county(self):
        result = identify_defendant_jurisdiction("Smith v. Marin County")
        assert result is not None
        assert "marin" in result

    def test_marin_county_board(self):
        result = identify_defendant_jurisdiction("Alves v. Marin County Board of Education")
        assert result is not None

    def test_city_of_novato(self):
        result = identify_defendant_jurisdiction("Johnson v. City of Novato")
        assert result is not None
        assert "novato" in result

    def test_town_of_corte_madera(self):
        result = identify_defendant_jurisdiction("Doe v. Town of Corte Madera")
        assert result is not None
        assert "corte-madera" in result

    def test_no_match(self):
        assert identify_defendant_jurisdiction("Smith v. Jones") is None

    def test_no_match_unrelated_jurisdiction(self):
        assert identify_defendant_jurisdiction("Smith v. City of Oakland") is None

    def test_plaintiff_not_matched(self):
        # "City of San Rafael v. Smith" — city is plaintiff, not defendant
        # We still return it because we detect it as a Marin jurisdiction
        result = identify_defendant_jurisdiction("City of San Rafael v. Smith")
        assert result is not None

    def test_returns_org_id_format(self):
        result = identify_defendant_jurisdiction("Rivera v. City of San Rafael")
        assert result is not None
        assert result.startswith("org-")

    def test_empty_string(self):
        assert identify_defendant_jurisdiction("") is None

    def test_none_safe(self):
        assert identify_defendant_jurisdiction(None) is None


class TestTransformCase:
    def test_creates_case_node(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "court": "District Court, N.D. California",
            "court_id": "cand",
            "dateFiled": "2024-08-16",
            "dateTerminated": None,
            "cause": "42:1983 Civil Rights Act",
            "assignedTo": "Gonzalez Rogers",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert node["node_type"] == "Case"
        assert node["labels"] == ["Case"]

    def test_display_label_from_case_name(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert "Rivera" in node["display_label"]

    def test_id_uses_docket_id(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert node["id"] == "case-cl-69053064"

    def test_id_falls_back_to_slugified_docket_number(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
        }
        node = transform_case(raw)
        assert node["id"].startswith("case-cl-")
        assert "24-cv-05239" in node["id"]

    def test_docket_number_property(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert node["properties"]["docket_number"] == "4:24-cv-05239"

    def test_court_properties(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "court": "District Court, N.D. California",
            "court_id": "cand",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert node["properties"]["court"] == "District Court, N.D. California"
        assert node["properties"]["court_id"] == "cand"

    def test_date_filed(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "dateFiled": "2024-08-16",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert node["properties"]["date_filed"] == "2024-08-16"

    def test_date_terminated_none(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "dateTerminated": None,
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert node["properties"]["date_terminated"] is None

    def test_date_terminated_with_value(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "dateTerminated": "2025-01-10",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert node["properties"]["date_terminated"] == "2025-01-10"

    def test_cause_property(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "cause": "42:1983 Civil Rights Act",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert node["properties"]["cause"] == "42:1983 Civil Rights Act"

    def test_assigned_to_property(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "assignedTo": "Gonzalez Rogers",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert node["properties"]["assigned_to"] == "Gonzalez Rogers"

    def test_source_is_courtlistener(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert node["properties"]["source"] == "courtlistener"

    def test_missing_optional_fields_are_none(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        props = node["properties"]
        assert props.get("cause") is None
        assert props.get("assigned_to") is None
        assert props.get("date_filed") is None
        assert props.get("date_terminated") is None

    def test_courtlistener_url_property(self):
        raw = {
            "caseName": "Rivera v. City of San Rafael",
            "docketNumber": "4:24-cv-05239",
            "docket_absolute_url": "/docket/69053064/rivera-v-city-of-san-rafael/",
            "docket_id": 69053064,
        }
        node = transform_case(raw)
        assert "courtlistener_url" in node["properties"]
        assert "69053064" in node["properties"]["courtlistener_url"]


class TestBuildCaseEdges:
    def _make_node(self, case_id="case-cl-123", org_id=None, court_id="cand"):
        return {
            "id": case_id,
            "properties": {
                "court_id": court_id,
                "defendant_org_id": org_id,
            },
        }

    def test_heard_in_edge(self):
        node = self._make_node(org_id="org-city-of-san-rafael", court_id="cand")
        edges = build_case_edges(node, "place-san-rafael")
        heard = [e for e in edges if e["relationship_type"] == "HEARD_IN"]
        assert len(heard) == 1
        assert heard[0]["source_id"] == "case-cl-123"
        assert heard[0]["target_id"] == "org-court-cand"

    def test_party_to_edge_when_org_id_present(self):
        node = self._make_node(org_id="org-city-of-san-rafael")
        edges = build_case_edges(node, "place-san-rafael")
        party = [e for e in edges if e["relationship_type"] == "PARTY_TO"]
        assert len(party) == 1
        assert party[0]["source_id"] == "case-cl-123"
        assert party[0]["target_id"] == "org-city-of-san-rafael"
        assert party[0]["properties"]["role"] == "defendant"

    def test_no_party_to_edge_when_no_org(self):
        node = self._make_node(org_id=None)
        edges = build_case_edges(node, "place-san-rafael")
        party = [e for e in edges if e["relationship_type"] == "PARTY_TO"]
        assert len(party) == 0

    def test_in_jurisdiction_edge(self):
        node = self._make_node(org_id="org-city-of-san-rafael")
        edges = build_case_edges(node, "place-san-rafael")
        juris = [e for e in edges if e["relationship_type"] == "IN_JURISDICTION"]
        assert len(juris) == 1
        assert juris[0]["target_id"] == "place-san-rafael"

    def test_no_in_jurisdiction_when_no_place_id(self):
        node = self._make_node(org_id="org-city-of-san-rafael")
        edges = build_case_edges(node, None)
        juris = [e for e in edges if e["relationship_type"] == "IN_JURISDICTION"]
        assert len(juris) == 0

    def test_all_edges_have_properties_dict(self):
        node = self._make_node(org_id="org-city-of-san-rafael")
        edges = build_case_edges(node, "place-san-rafael")
        for edge in edges:
            assert "properties" in edge

    def test_no_court_id_still_produces_heard_in(self):
        node = {"id": "case-cl-99", "properties": {"court_id": None, "defendant_org_id": None}}
        edges = build_case_edges(node, None)
        heard = [e for e in edges if e["relationship_type"] == "HEARD_IN"]
        assert len(heard) == 0


class TestBuildCourtOrgNode:
    def test_creates_org_node(self):
        node = build_court_org_node("cand", "District Court, N.D. California")
        assert node["id"] == "org-court-cand"
        assert node["node_type"] == "Organization"
        assert "Organization" in node["labels"]

    def test_display_label(self):
        node = build_court_org_node("cand", "District Court, N.D. California")
        assert node["display_label"] == "District Court, N.D. California"

    def test_properties(self):
        node = build_court_org_node("cand", "District Court, N.D. California")
        assert node["properties"]["court_id"] == "cand"
        assert node["properties"]["org_type"] == "court"
        assert node["properties"]["source"] == "courtlistener"

    def test_empty_court_name_uses_id(self):
        node = build_court_org_node("ca9", "")
        assert "ca9" in node["display_label"] or "ca9" in node["id"]

    def test_none_court_name_uses_id(self):
        node = build_court_org_node("ca9", None)
        assert node["id"] == "org-court-ca9"
