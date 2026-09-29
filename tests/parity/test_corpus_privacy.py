"""The committed parity corpus pins the public exposure of a residential permit.

Residential permit addresses are published as street + city only (decision
2026-09-28; scripts/public_exposure.py). The July corpus predates that and
committed full addresses; this case makes the policy part of every replay, so a
regression that re-exposes a house number fails parity, not just a unit test.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

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


# --- every corpus file: no private address, email or phone ------------------------

ADDRESS_SHAPE = re.compile(
    r"\b\d{1,6}[A-Z]? [A-Z0-9][A-Z0-9 .'-]* (?:RD|WAY|AVE|DR|ST|LN|CT|PL|BLVD|CIR|TER|HWY|LOOP|"
    r"ROAD|STREET|AVENUE|DRIVE|LANE|COURT|PLACE|BOULEVARD|CIRCLE|TERRACE)\b",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")

# Reviewed 2026-09-29: civic sites and organization names, public by policy
# (civic_project / commercial exposure is full address). Compared case-insensitively.
PUBLIC_ADDRESSES = {
    "1100 E STREET", "190 MILL STREET", "250 ENTRADA DRIVE", "350 MERRYDALE ROAD",
    "380 MERRYDALE ROAD", "3833 REDWOOD HWY", "55 FAIRFAX STREET", "620 CANAL STREET",
    "700 IRWIN ST", "700 IRWIN STREET",
}
# Official public records kept by digest so this file adds no copy of the text:
# a council member's Brown Act teleconference location, printed on the agenda
# (allowlisted 2026-07 as official_public_record_brown_act_teleconference).
PUBLIC_ADDRESS_DIGESTS = {
    "e8a133a68414ee670815b19fa9a0c8fe4afd67ea2eeb4137060808648901bda9",
}


def _is_public(address: str) -> bool:
    key = " ".join(address.upper().split())
    return key in PUBLIC_ADDRESSES or hashlib.sha256(key.encode()).hexdigest() in PUBLIC_ADDRESS_DIGESTS


CORPUS_FILES = sorted(CORPUS.rglob("*.json"))


@pytest.mark.parametrize("path", CORPUS_FILES, ids=lambda p: str(p.relative_to(CORPUS)))
def test_no_corpus_file_carries_a_private_address_email_or_phone(path):
    text = path.read_text()
    private = sorted({m.group(0) for m in ADDRESS_SHAPE.finditer(text) if not _is_public(m.group(0))})
    assert not private, f"{len(private)} address-shaped string(s) not reviewed as public"
    assert not EMAIL.search(text), "email address in the corpus"
    assert not PHONE.search(text), "phone number in the corpus"


def test_the_scan_would_catch_an_all_caps_residential_address():
    assert ADDRESS_SHAPE.search("12 EXAMPLE RD, SOMEWHERE") and not _is_public("12 EXAMPLE RD")
