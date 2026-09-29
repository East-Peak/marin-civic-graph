"""The committed parity corpus pins the public exposure of a residential permit.

Residential permit addresses are published as street + city only (decision
2026-09-28; scripts/public_exposure.py). The July corpus predates that and
committed full addresses; this case makes the policy part of every replay, so a
regression that re-exposes a house number fails parity, not just a unit test.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "corpus"
RESIDENTIAL_CASE = CORPUS / "entity" / "project-residential-permit.json"
STREET_AND_CITY = re.compile(r"^[A-Z][A-Z0-9 .'&/-]*, [A-Z][A-Z .'-]*$")


def _payload(path: Path) -> dict:
    return json.loads(path.read_text())["payload"]


def test_a_residential_permit_entity_case_is_in_the_corpus():
    assert RESIDENTIAL_CASE.is_file()
    assert _payload(RESIDENTIAL_CASE)["id"].startswith("permit-")


def test_its_address_is_street_and_city_without_a_house_number():
    address = _payload(RESIDENTIAL_CASE)["properties"]["address"]
    assert STREET_AND_CITY.match(address), address
    assert not re.match(r"^\d", address)


def test_the_browse_page_it_came_from_shows_the_same_street_and_city():
    rows = _payload(CORPUS / "browse" / "project-page1.json")["rows"]
    case_id = _payload(RESIDENTIAL_CASE)["id"]
    row = next(r for r in rows if r["id"] == case_id)
    assert row["address"] == _payload(RESIDENTIAL_CASE)["properties"]["address"]
