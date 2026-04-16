"""Tests for ingest_socrata_permits.py — Marin County Socrata permit ingestion.

TDD: tests written first, implementation follows.

Covers pure transformation functions — no live API or Neo4j connection required:
  - transform_permit: field mapping, type coercion, missing fields
  - build_permit_edges: IN_JURISDICTION edge construction
  - slugify_city: city name → Place node slug
  - build_place_node: Place node construction from city name
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ingest_socrata_permits import (
    build_permit_edges,
    build_place_node,
    slugify_city,
    transform_permit,
)


class TestSlugifyCity:
    def test_simple_name(self):
        assert slugify_city("SAUSALITO") == "sausalito"

    def test_multi_word(self):
        assert slugify_city("SAN RAFAEL") == "san-rafael"

    def test_corte_madera(self):
        assert slugify_city("CORTE MADERA") == "corte-madera"

    def test_already_lower(self):
        assert slugify_city("novato") == "novato"

    def test_strips_whitespace(self):
        assert slugify_city("  TIBURON  ") == "tiburon"

    def test_multiple_spaces(self):
        assert slugify_city("MILL  VALLEY") == "mill-valley"


class TestBuildPlaceNode:
    def test_creates_place_node(self):
        node = build_place_node("SAUSALITO")
        assert node["id"] == "place-sausalito"
        assert node["node_type"] == "Place"
        assert node["labels"] == ["Place"]
        assert node["display_label"] == "Sausalito"

    def test_multi_word_city(self):
        node = build_place_node("SAN RAFAEL")
        assert node["id"] == "place-san-rafael"
        assert node["display_label"] == "San Rafael"

    def test_properties_have_city_field(self):
        node = build_place_node("NOVATO")
        assert node["properties"]["city_town"] == "NOVATO"
        assert node["properties"]["place_type"] == "city"
        assert node["properties"]["county"] == "Marin"
        assert node["properties"]["state"] == "CA"
        assert node["properties"]["source"] == "marin-county-socrata-permits"


class TestTransformPermit:
    def test_creates_project_node(self):
        raw = {
            "unique_id": "OM_93287",
            "permit_number": "8829",
            "address": "26 MAIN DOCK, SAUSALITO, CA 94965",
            "description": "Floating Home Occupancy Transfer",
            "issued_date": "2025-06-20T00:00:00.000",
            "construction_value": "50000",
            "type_permit": "RESIDENTIAL",
            "city_town": "SAUSALITO",
            "latitude": "37.872515",
            "longitude": "-122.502531",
        }
        node = transform_permit(raw)
        assert node["id"] == "permit-marin-OM_93287"
        assert node["node_type"] == "Project"
        assert node["labels"] == ["Project"]
        assert node["properties"]["construction_value"] == 50000.0
        assert node["properties"]["issued_date"] == "2025-06-20"

    def test_display_label(self):
        raw = {
            "unique_id": "OM_1",
            "description": "New Roof",
            "address": "123 Main St",
        }
        node = transform_permit(raw)
        assert node["display_label"] == "New Roof at 123 Main St"

    def test_display_label_missing_description(self):
        raw = {"unique_id": "OM_2", "address": "456 Oak Ave"}
        node = transform_permit(raw)
        assert "456 Oak Ave" in node["display_label"]

    def test_display_label_missing_address(self):
        raw = {"unique_id": "OM_3", "description": "Permit Work"}
        node = transform_permit(raw)
        assert "Permit Work" in node["display_label"]

    def test_handles_missing_fields(self):
        raw = {"unique_id": "OM_1", "description": "Test"}
        node = transform_permit(raw)
        assert node["id"] == "permit-marin-OM_1"
        assert node["properties"].get("construction_value") is None

    def test_handles_empty_construction_value(self):
        raw = {"unique_id": "OM_2", "construction_value": ""}
        node = transform_permit(raw)
        assert node["properties"]["construction_value"] is None

    def test_handles_zero_construction_value(self):
        raw = {"unique_id": "OM_3", "construction_value": "0"}
        node = transform_permit(raw)
        assert node["properties"]["construction_value"] == 0.0

    def test_iso_date_parsing(self):
        raw = {"unique_id": "OM_4", "issued_date": "2023-11-15T00:00:00.000"}
        node = transform_permit(raw)
        assert node["properties"]["issued_date"] == "2023-11-15"

    def test_missing_date_is_none(self):
        raw = {"unique_id": "OM_5"}
        node = transform_permit(raw)
        assert node["properties"]["issued_date"] is None

    def test_latitude_longitude_as_float(self):
        raw = {
            "unique_id": "OM_6",
            "latitude": "37.872515",
            "longitude": "-122.502531",
        }
        node = transform_permit(raw)
        assert node["properties"]["latitude"] == 37.872515
        assert node["properties"]["longitude"] == -122.502531

    def test_missing_lat_lng_is_none(self):
        raw = {"unique_id": "OM_7"}
        node = transform_permit(raw)
        assert node["properties"]["latitude"] is None
        assert node["properties"]["longitude"] is None

    def test_source_field(self):
        raw = {"unique_id": "OM_8"}
        node = transform_permit(raw)
        assert node["properties"]["source"] == "marin-county-socrata-permits"

    def test_project_type_field(self):
        raw = {"unique_id": "OM_9"}
        node = transform_permit(raw)
        assert node["properties"]["project_type"] == "building_permit"

    def test_all_expected_property_keys_present(self):
        raw = {
            "unique_id": "OM_10",
            "permit_number": "1234",
            "parcel_number": "55-22-11",
            "city_town": "MILL VALLEY",
            "description": "Deck addition",
            "type_permit": "RESIDENTIAL",
            "permit_category": "ALTERATION",
            "address": "7 Elm St",
        }
        node = transform_permit(raw)
        props = node["properties"]
        assert props["permit_number"] == "1234"
        assert props["parcel_number"] == "55-22-11"
        assert props["city_town"] == "MILL VALLEY"
        assert props["type_permit"] == "RESIDENTIAL"
        assert props["permit_category"] == "ALTERATION"
        assert props["address"] == "7 Elm St"


class TestBuildPermitEdges:
    def test_jurisdiction_edge(self):
        node = {"id": "permit-marin-1", "properties": {"city_town": "SAUSALITO"}}
        edges = build_permit_edges(node)
        juris = [e for e in edges if e["relationship_type"] == "IN_JURISDICTION"]
        assert len(juris) == 1
        assert juris[0]["source_id"] == "permit-marin-1"
        assert juris[0]["target_id"] == "place-sausalito"

    def test_jurisdiction_edge_multi_word_city(self):
        node = {"id": "permit-marin-2", "properties": {"city_town": "SAN RAFAEL"}}
        edges = build_permit_edges(node)
        juris = [e for e in edges if e["relationship_type"] == "IN_JURISDICTION"]
        assert juris[0]["target_id"] == "place-san-rafael"

    def test_no_edges_when_city_missing(self):
        node = {"id": "permit-marin-3", "properties": {}}
        edges = build_permit_edges(node)
        juris = [e for e in edges if e["relationship_type"] == "IN_JURISDICTION"]
        assert len(juris) == 0

    def test_no_edges_when_city_empty_string(self):
        node = {"id": "permit-marin-4", "properties": {"city_town": ""}}
        edges = build_permit_edges(node)
        juris = [e for e in edges if e["relationship_type"] == "IN_JURISDICTION"]
        assert len(juris) == 0

    def test_edge_has_properties_dict(self):
        node = {"id": "permit-marin-5", "properties": {"city_town": "NOVATO"}}
        edges = build_permit_edges(node)
        for edge in edges:
            assert "properties" in edge

    def test_edge_relationship_type_format(self):
        node = {"id": "permit-marin-6", "properties": {"city_town": "TIBURON"}}
        edges = build_permit_edges(node)
        for edge in edges:
            assert edge["relationship_type"] == edge["relationship_type"].upper()
