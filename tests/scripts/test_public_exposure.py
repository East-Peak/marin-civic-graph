"""Tests for the bake-time public exposure (privacy) transform.

Samples are shaped like the real Marin County Socrata permit rows: upper-case
"N STREET, CITY, CA ZIP" addresses, unit parts as their own comma segment,
free-text descriptions that repeat the address, and the three civic Projects.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from public_exposure import (  # noqa: E402
    ADDRESS_EXPOSURE,
    classify_project,
    parse_address,
    public_address,
    sanitize_node_props,
    scrub_free_text,
    street_vocabulary,
)


def _residential(**overrides: object) -> dict:
    props = {
        "id": "permit-marin-IN_B46394_46394",
        "address": "444 HAZELMERE RD, KENTFIELD, CA 94904",
        "city_town": "KENTFIELD",
        "construction_value": 7000.0,
        "display_label": "Permit at 444 HAZELMERE RD, KENTFIELD, CA 94904",
        "issued_date": "2026-04-20",
        "latitude": 37.9518628,
        "longitude": -122.5641631,
        "parcel_number": "999-111-01",
        "permit_number": "B46394",
        "project_type": "building_permit",
        "source": "marin-county-socrata-permits",
        "type_permit": "RESIDENTIAL",
    }
    props.update(overrides)
    return props


MERRYDALE = {
    "id": "project-san-rafael-350-merrydale-interim-shelter",
    "name": "350 Merrydale Interim Shelter Project",
    "display_label": "350 Merrydale Interim Shelter Project",
    "search_label": "350 Merrydale Interim Shelter Project",
    "search_terms": "project-san-rafael-350-merrydale-interim-shelter 350 merrydale interim shelter project",
    "project_type": "interim_shelter_project",
    "primary_place_id": "place-350-merrydale-road",
    "status": "active",
}


def test_policy_is_one_declarative_knob_per_project_class() -> None:
    assert ADDRESS_EXPOSURE == {
        "residential_permit": "street_city",
        "commercial_permit": "full",
        "civic_project": "full",
    }


def test_classify_project_uses_source_and_permit_type() -> None:
    assert classify_project(_residential()) == "residential_permit"
    assert classify_project(_residential(type_permit="COMMERCIAL")) == "commercial_permit"
    assert classify_project(MERRYDALE) == "civic_project"
    # An unclassified permit is treated as residential: fail closed.
    assert classify_project(_residential(type_permit=None)) == "residential_permit"


@pytest.mark.parametrize(
    ("raw", "street", "city"),
    [
        ("444 HAZELMERE RD, KENTFIELD, CA 94904", "HAZELMERE RD", "KENTFIELD"),
        ("15 MOSSBROOK WAY, SUITE 39, SAN RAFAEL, CA 94903", "MOSSBROOK WAY", "SAN RAFAEL"),
        ("155 Farthingale Blvd #157, San Rafael, CA 94903", "Farthingale Blvd", "San Rafael"),
        ("12 QUILLMOOR ST APT 4B, SAN RAFAEL, CA 94901", "QUILLMOOR ST", "SAN RAFAEL"),
        ("51 -55 Corvid Blvd, Mill Valley, CA 94941", "Corvid Blvd", "Mill Valley"),
        ("12-14 BRACKENFELL AVE, NOVATO, CA 94945", "BRACKENFELL AVE", "NOVATO"),
        ("5757 ASHGROVE VALLEY RD, NICASIO,   94946", "ASHGROVE VALLEY RD", "NICASIO"),
        ("67 Starling Rd, San Anselmo, CA", "Starling Rd", "San Anselmo"),
        ("167 Pennyroyal Ln (And 169), Mill Valley, CA 94941", "Pennyroyal Ln", "Mill Valley"),
        ("123 5TH AVE, SAN RAFAEL, CA 94901", "5TH AVE", "SAN RAFAEL"),
        ("463 TAMSIN DR - APT #207, SAUSALITO, CA 94965", "TAMSIN DR", "SAUSALITO"),
        ("60 Barbaree Wy - Bldg 4, Units 10-18, Tiburon, CA 94920", "Barbaree Wy", "Tiburon"),
        ("12075 STATE ROUTE 1, POINT REYES STATION, CA 94956", "STATE ROUTE 1", "POINT REYES STATION"),
        ("18 GATE 6 1/2, SAUSALITO, CA 94965", "GATE 6 1/2", "SAUSALITO"),
    ],
)
def test_parse_address_strips_house_numbers_ranges_and_units(
    raw: str, street: str, city: str
) -> None:
    parsed = parse_address(raw)
    assert (parsed.kind, parsed.street, parsed.city) == ("street", street, city)


def test_parse_po_box_omits_the_box_number() -> None:
    parsed = parse_address("PO BOX 1234, SAN RAFAEL, CA 94915")
    assert (parsed.kind, parsed.street, parsed.city) == ("po_box", None, "SAN RAFAEL")
    assert public_address("P.O. Box 77, Novato, CA", "NOVATO", "street_city") == "Novato"


@pytest.mark.parametrize(
    ("raw", "city"),
    [
        ("11 Alderglen Dr & 13,15,17, Sausalito, CA 94965", "Sausalito"),
        ("22 Sable Crest Dr ( & 24,26,28), San Rafael, CA 94903", "San Rafael"),
        ("12 14 QUILLMOOR ST, SAN RAFAEL, CA 94901", "SAN RAFAEL"),
        ("LOT 7 SOMEWHERE NEAR THE CREEK", "CITY_TOWN FALLBACK"),
        ("24 GORSEWOOD DR A K A 26, MILL VALLEY, CA 94941", "MILL VALLEY"),
    ],
)
def test_ambiguous_addresses_fall_back_to_city_only(raw: str, city: str) -> None:
    assert parse_address(raw).kind == "ambiguous"
    assert public_address(raw, "CITY_TOWN FALLBACK", "street_city") == city


def test_public_address_levels() -> None:
    raw = "444 HAZELMERE RD, KENTFIELD, CA 94904"
    assert public_address(raw, "KENTFIELD", "full") == raw
    assert public_address(raw, "KENTFIELD", "street_city") == "HAZELMERE RD, KENTFIELD"
    assert public_address(raw, "KENTFIELD", "city") == "KENTFIELD"
    assert public_address(None, None, "street_city") is None
    with pytest.raises(ValueError):
        public_address(raw, "KENTFIELD", "house_number_please")


def test_residential_permit_is_street_city_with_regenerated_labels() -> None:
    props = _residential(search_label="permit-marin-IN_B46394_46394",
                         search_terms="permit-marin-in_b46394_46394")
    out = sanitize_node_props("Project", props)

    assert out["address"] == "HAZELMERE RD, KENTFIELD"
    assert out["display_label"] == "Permit at HAZELMERE RD, KENTFIELD"
    assert out["search_label"] == "permit-marin-IN_B46394_46394"
    assert out["search_terms"] == "permit-marin-in_b46394_46394"
    for key in ("parcel_number", "latitude", "longitude"):
        assert key not in out
    # Non-address facts survive; the input is not mutated.
    assert out["construction_value"] == 7000.0
    assert out["permit_number"] == "B46394"
    assert props["address"] == "444 HAZELMERE RD, KENTFIELD, CA 94904"


def test_residential_description_is_scrubbed_before_it_feeds_the_label() -> None:
    props = _residential(
        address="193 LINNET DR, SAN RAFAEL, CA 94901",
        city_town="SAN RAFAEL",
        description=(
            "Reroof my garage. The work is at my home at 193 Linnet Dr., San Rafael, "
            "APN 999-111-02. Cottage next to 142 Harrowgate Blvd, unit #13."
        ),
        display_label="Reroof my garage. at 193 LINNET DR, SAN RAFAEL, CA 94901",
    )
    out = sanitize_node_props("Project", props)
    text = f"{out['description']} {out['display_label']}"

    for leak in ("193", "999-111-02", "142 Harrowgate", "#13"):
        assert leak not in text
    assert "Linnet Dr" in out["description"]
    assert out["display_label"].endswith(" at LINNET DR, SAN RAFAEL")


def test_free_text_drops_numbers_before_known_street_names() -> None:
    vocab = street_vocabulary([
        "64 MERROW DR, SAN RAFAEL, CA 94903",
        "11 Alderglen Dr & 13,15,17, Sausalito, CA 94965",
        "PO BOX 9, NOVATO, CA",
        None,
    ])
    assert vocab == frozenset({"MERROW", "ALDERGLEN"})
    text = scrub_free_text(
        "Water service at both 60 & 64 Merrow; meter near 13 alderglen. "
        "Install 2 water heaters, 100 amp panel.",
        vocab,
    )
    assert text == (
        "Water service at both Merrow; meter near terrace. "
        "Install 2 water heaters, 100 amp panel."
    )


def test_residential_unit_range_and_po_box_labels_never_carry_numbers() -> None:
    unit = sanitize_node_props("Project", _residential(
        address="15 MOSSBROOK WAY, SUITE 39, SAN RAFAEL, CA 94903",
        description="REPLACE WATER HEATER",
    ))
    assert unit["display_label"] == "REPLACE WATER HEATER at MOSSBROOK WAY, SAN RAFAEL"

    po_box = sanitize_node_props("Project", _residential(
        address="PO BOX 1234, SAN RAFAEL, CA 94915", city_town="SAN RAFAEL",
    ))
    assert po_box["address"] == "SAN RAFAEL"
    assert "1234" not in po_box["display_label"]

    missing = sanitize_node_props("Project", _residential(address=None, city_town=None))
    assert "address" not in missing
    assert missing["display_label"] == "Permit IN_B46394_46394"


def test_commercial_permit_and_civic_projects_keep_their_policy() -> None:
    commercial = _residential(
        type_permit="COMMERCIAL",
        address="1600 KESTREL HOLLOW DR, SAN RAFAEL, CA 94903",
        display_label="TI at 1600 KESTREL HOLLOW DR, SAN RAFAEL, CA 94903",
    )
    assert sanitize_node_props("Project", commercial) == commercial
    assert sanitize_node_props("Project", dict(MERRYDALE)) == MERRYDALE
    # Non-Project types are never touched.
    person = {"id": "person-a", "name": "12 Quillmoor St Fan"}
    assert sanitize_node_props("Person", person) is person


def test_policy_knob_dials_exposure_without_code_changes() -> None:
    props = _residential()
    city_only = sanitize_node_props(
        "Project", props, policy={**ADDRESS_EXPOSURE, "residential_permit": "city"}
    )
    assert city_only["address"] == "KENTFIELD"
    assert city_only["display_label"] == "Permit at KENTFIELD"

    full = sanitize_node_props(
        "Project", props, policy={**ADDRESS_EXPOSURE, "residential_permit": "full"}
    )
    assert full == props


# --- artifact-wide leak test -------------------------------------------------

import json  # noqa: E402
import re  # noqa: E402
import sqlite3  # noqa: E402

from bake_public_substrate import bake_substrate  # noqa: E402

RESIDENTIAL_SAMPLES = {
    "permit-marin-IN_B46394_46394": {
        "address": "444 HAZELMERE RD, KENTFIELD, CA 94904",
        "city_town": "KENTFIELD",
        "display_label": "Permit at 444 HAZELMERE RD, KENTFIELD, CA 94904",
    },
    "permit-marin-IN_UNIT_1": {
        "address": "15 MOSSBROOK WAY, SUITE 39, SAN RAFAEL, CA 94903",
        "city_town": "SAN RAFAEL",
        "description": "REPLACE WATER HEATER at 15 Mossbrook Way",
        "display_label": "REPLACE WATER HEATER at 15 MOSSBROOK WAY, SUITE 39, SAN RAFAEL, CA 94903",
        "search_label": "permit-marin-IN_UNIT_1",
        "search_terms": "permit-marin-in_unit_1 15 mossbrook way",
    },
    "permit-marin-IN_RANGE_1": {
        "address": "51 -55 Corvid Blvd, Mill Valley, CA 94941",
        "city_town": "MILL VALLEY",
        "display_label": "Permit at 51 -55 Corvid Blvd, Mill Valley, CA 94941",
    },
    "permit-marin-IN_POBOX_1": {
        "address": "PO BOX 1234, SAN RAFAEL, CA 94915",
        "city_town": "SAN RAFAEL",
        "display_label": "Permit at PO BOX 1234, SAN RAFAEL, CA 94915",
    },
    "permit-marin-IN_AMBIG_1": {
        "address": "11 Alderglen Dr & 13,15,17, Sausalito, CA 94965",
        "city_town": "SAUSALITO",
        "display_label": "Permit at 11 Alderglen Dr & 13,15,17, Sausalito, CA 94965",
    },
}
COMMERCIAL_ADDRESS = "1600 KESTREL HOLLOW DR, SAN RAFAEL, CA 94903"


def _permit_row(node_id: str, type_permit: str, props: dict) -> dict:
    return {
        "id": node_id,
        "labels": ["Project"],
        "properties": {
            "id": node_id,
            "latitude": 37.95,
            "longitude": -122.56,
            "parcel_number": "999-111-01",
            "project_type": "building_permit",
            "source": "marin-county-socrata-permits",
            "type_permit": type_permit,
            **props,
        },
    }


def _leak_fixture(tmp_path: Path) -> tuple[Path, Path]:
    nodes = [
        _permit_row(node_id, "RESIDENTIAL", props)
        for node_id, props in RESIDENTIAL_SAMPLES.items()
    ]
    nodes.append(_permit_row("permit-marin-IN_COMM_1", "COMMERCIAL", {
        "address": COMMERCIAL_ADDRESS,
        "display_label": f"TI at {COMMERCIAL_ADDRESS}",
    }))
    nodes.append({"id": MERRYDALE["id"], "labels": ["Project"], "properties": MERRYDALE})
    export = tmp_path / "export"
    overlay = tmp_path / "overlay"
    for directory, rows in ((export, nodes), (overlay, [])):
        directory.mkdir()
        (directory / "nodes.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        (directory / "edges.jsonl").write_text("", encoding="utf-8")
    registry = tmp_path / "node-types.json"
    registry.write_text(json.dumps({
        "graph_node_types": {"Project": {}},
        "id_prefixes": {"permit-": "Project", "project-": "Project"},
    }))
    sqlite_path = tmp_path / "public-substrate.sqlite"
    bake_substrate(
        registry_path=registry,
        sqlite_path=sqlite_path,
        report_path=tmp_path / "report.json",
        source="live-export",
        live_export_dir=export,
        attach_overlay_dir=overlay,
    )
    return sqlite_path, registry


def _needles(address: str) -> set[str]:
    """House-number+street strings a leak would contain (normalized)."""
    street = " ".join(address.split(",")[0].upper().split())
    needles = {street}
    match = re.match(r"^([\d\s&-]+?)\s*([A-Z][A-Z.]*)", street)
    if match:
        for number in re.findall(r"\d+", match.group(1)):
            needles.add(f"{number} {match.group(2)}")
    return needles


def _artifact_texts(conn: sqlite3.Connection) -> list[str]:
    texts: list[str] = []
    for row in conn.execute("SELECT id, search_label, props FROM nodes"):
        texts.extend(row)
    for row in conn.execute("SELECT * FROM browse_rows"):
        texts.extend(str(value) for value in row if value is not None)
    for (value,) in conn.execute("SELECT value FROM meta"):
        texts.append(value)
    return [" ".join(text.upper().split()) for text in texts]


def test_artifact_wide_scan_finds_no_residential_house_number_street(
    tmp_path: Path,
) -> None:
    sqlite_path, _ = _leak_fixture(tmp_path)
    with sqlite3.connect(sqlite_path) as conn:
        texts = _artifact_texts(conn)
        leaks = sorted(
            needle
            for props in RESIDENTIAL_SAMPLES.values()
            for needle in _needles(props["address"])
            if any(needle in text for text in texts)
        )
        fts_hits = sorted(
            node_id
            for props in RESIDENTIAL_SAMPLES.values()
            for needle in _needles(props["address"])
            for (node_id,) in conn.execute(
                "SELECT n.id FROM search_fts JOIN nodes n ON n.rowid = search_fts.rowid "
                "WHERE search_fts MATCH ? AND json_extract(n.props, '$.type_permit') = 'RESIDENTIAL'",
                ('"' + needle.replace('"', "") + '"',),
            )
        )
        residential_geo_keys = conn.execute(
            """
            SELECT count(*) FROM nodes, json_each(nodes.props)
            WHERE json_extract(nodes.props, '$.type_permit') = 'RESIDENTIAL'
              AND json_each.key IN ('parcel_number', 'latitude', 'longitude')
            """
        ).fetchone()[0]
        hazelmere = conn.execute(
            "SELECT count(*) FROM search_fts WHERE search_fts MATCH '\"444 HAZELMERE\"'"
        ).fetchone()[0]
        labels = dict(conn.execute("SELECT id, search_label FROM nodes"))
        browse = dict(conn.execute(
            "SELECT id, col2_value FROM browse_rows WHERE type = 'Project'"
        ))

    assert leaks == []
    assert fts_hits == []
    assert residential_geo_keys == 0
    assert hazelmere == 0
    assert labels["permit-marin-IN_B46394_46394"] == "Permit at HAZELMERE RD, KENTFIELD"
    assert json.loads(browse["permit-marin-IN_UNIT_1"]) == "MOSSBROOK WAY, SAN RAFAEL"
    assert json.loads(browse["permit-marin-IN_POBOX_1"]) == "SAN RAFAEL"
    assert json.loads(browse["permit-marin-IN_AMBIG_1"]) == "Sausalito"
    # Controls: the scan is live — commercial and civic addresses are still public.
    assert any(COMMERCIAL_ADDRESS in text for text in texts)
    assert json.loads(browse["permit-marin-IN_COMM_1"]) == COMMERCIAL_ADDRESS
    assert labels[MERRYDALE["id"]] == "350 Merrydale Interim Shelter Project"
