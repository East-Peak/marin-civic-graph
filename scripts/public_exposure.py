"""Bake-time public exposure policy for address-bearing nodes.

The operator graph keeps full permit data; the PUBLIC artifact gets only what
the policy table below allows. The transform runs on composed node props
before any public derivation (labels, browse rows, FTS, rollups), so every
derived surface is rebuilt from sanitized fields rather than scrubbed after.

Dial exposure per Project class by editing ADDRESS_EXPOSURE:
  full        -- source address and geo fields as-is
  street_city -- street name + city; no house number/range, unit, parcel, lat/long
  city        -- city only

and campaign contributors' locality by its campaign_contributor entry (the street is never published):
  city_zip    -- occupation, employer, city, state and ZIP5, as reported
  city        -- occupation, employer, city and state
  none        -- occupation and employer only
Contributor values also pass contributor_detail.py's rules here, whatever the graph holds, and only an
individual's Schedule A NetFile contribution is eligible (decisions/2026-09-29-open-marin-donor-exposure.md).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from contributor_detail import ENTITY_PROP, FIELDS, PROPS, classify

ADDRESS_EXPOSURE: dict[str, str] = {
    "residential_permit": "street_city",
    "commercial_permit": "full",
    "civic_project": "full",
    "campaign_contributor": "city_zip",
}
LEVELS = ("full", "street_city", "city")
CONTRIBUTOR_LEVELS: dict[str, frozenset[str]] = {
    "city_zip": frozenset(FIELDS),
    "city": frozenset({"occupation", "employer", "city", "state"}),
    "none": frozenset({"occupation", "employer"}),
}
CONTRIBUTOR_KEYS = frozenset({*PROPS.values(), ENTITY_PROP})
_NETFILE_FLOW_ID = re.compile(r"moneyflow-(\d+|Pending)-")

PERMIT_SOURCE = "marin-county-socrata-permits"
GEO_FIELDS = ("parcel_number", "latitude", "longitude")
FREE_TEXT_FIELDS = ("description", "name", "title")

_UNIT = r"(?:APT|APARTMENT|UNITS?|STE|SUITE|SPACE|SPC|SP|BLDG|BUILDING|LOT|RM|ROOM|FL|FLOOR)"
_UNIT_PART = re.compile(rf"^(?:{_UNIT}\b|#)", re.I)
_UNIT_TAIL = re.compile(rf"\s*(?:\b{_UNIT}\b\.?|#).*$", re.I)
_STATE_ZIP = re.compile(r"^(?:CA|CALIFORNIA)?\.?\s*(?:\d{5}(?:-\d{4})?)?$", re.I)
_CITY_STATE_ZIP = re.compile(r"\s+(?:CA|CALIFORNIA)\.?(?:\s+\d{5}(?:-\d{4})?)?$", re.I)
_PO_BOX = re.compile(r"^(?:P\.?\s*O\.?\s*BOX|POST\s+OFFICE\s+BOX|BOX)\b", re.I)
_HOUSE_NUMBER = re.compile(
    r"^\d+[A-Z]?(?:\s+\d/\d)?(?:\s*(?:-|&|/|\bAND\b|\bTHRU\b|\bTO\b)\s*\d+[A-Z]?)*\s+", re.I
)
_STREET = re.compile(r"^(?:\d+(?:ST|ND|RD|TH)\b|[A-Z])[A-Z0-9 .'/-]*$", re.I)
_BARE_NUMBER = re.compile(r"^\d+(?:/\d+)?[A-Z]?$", re.I)
_NUMBERED_ROAD_WORDS = frozenset({"ROUTE", "RTE", "HWY", "HIGHWAY", "SR", "GATE"})
_FIRST_WORD = re.compile(r"\b([A-Z][A-Z']*)", re.I)
_LEADING_STREET_WORD = re.compile(r"^\d+[A-Z]?(?:\s*[-&]\s*\d+[A-Z]?)*\s+([A-Z][A-Z']*)", re.I)
_CITY = re.compile(r"^[A-Z][A-Z .'()-]*$", re.I)
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")

_SUFFIX = (
    r"(?:ST|STREET|RD|ROAD|DR|DRIVE|AVE|AVENUE|BLVD|BOULEVARD|LN|LANE|CT|COURT|WAY|"
    r"PL|PLACE|CIR|CIRCLE|TER|TERRACE|HWY|HIGHWAY|TRL|TRAIL|PKWY|PARKWAY|LOOP|ROW|"
    r"ALY|ALLEY|PATH|DOCK|PIER)"
)
_FREE_TEXT_HOUSE_NUMBER = re.compile(
    rf"\b\d+[A-Z]?(?:\s*[-&/]\s*\d+[A-Z]?)*\s+(?=(?:[A-Z][\w'.]*\s+){{0,3}}{_SUFFIX}\b)", re.I
)
_FREE_TEXT_PARCEL = re.compile(r"\b(?:APN\s*#?\s*)?\d{3}-\d{3}-\d{2,3}\b", re.I)
_FREE_TEXT_UNIT = re.compile(r"#\s*\d+[A-Z]?\b", re.I)
_NUMBER_THEN_WORD = re.compile(r"\b(\d+)[A-Z]?\s+([A-Z][\w']*)", re.I)
_FREE_TEXT_NUMBER_WORD = re.compile(
    r"\b\d+[A-Z]?(?:\s+\d+/\d+)?(?:\s*(?:[-&/,+]|\bAND\b)\s*\d+[A-Z]?)*\s+([A-Z][\w']*)", re.I
)


@dataclass(frozen=True)
class ParsedAddress:
    kind: str  # street | po_box | ambiguous | empty
    street: str | None = None
    city: str | None = None


def classify_project(props: Mapping) -> str:
    is_permit = (
        props.get("source") == PERMIT_SOURCE
        or props.get("project_type") == "building_permit"
    )
    if not is_permit:
        return "civic_project"
    if str(props.get("type_permit") or "").upper() == "COMMERCIAL":
        return "commercial_permit"
    return "residential_permit"  # unknown permit class fails closed


def parse_address(address: str | None) -> ParsedAddress:
    if not address or not address.strip():
        return ParsedAddress("empty")
    parts = [part.strip() for part in address.split(",") if part.strip()]
    while len(parts) > 1 and _STATE_ZIP.match(parts[-1]):
        parts.pop()
    if len(parts) < 2:
        return ParsedAddress("ambiguous")

    city = _CITY_STATE_ZIP.sub("", parts[-1]).strip()
    city = city if _CITY.match(city) else None
    street_part, middle = parts[0], parts[1:-1]
    if city is None or not all(_UNIT_PART.match(part) for part in middle):
        return ParsedAddress("ambiguous", city=city)
    if _PO_BOX.match(street_part):
        return ParsedAddress("po_box", city=city)

    street = _UNIT_TAIL.sub("", _PARENTHETICAL.sub("", street_part)).strip()
    street = _HOUSE_NUMBER.sub("", street, count=1).strip(" \t-.,#")
    if (
        not _STREET.match(street)
        or len(re.findall(r"[A-Z]", street, re.I)) < 2
        or _has_stray_number(street)
    ):
        return ParsedAddress("ambiguous", city=city)
    return ParsedAddress("street", street=street, city=city)


def _has_stray_number(street: str) -> bool:
    """Bare numbers name a road only after ROUTE/HWY/GATE ("STATE ROUTE 1", "GATE 6 1/2")."""
    previous = ""
    for token in street.upper().split():
        allowed = previous in _NUMBERED_ROAD_WORDS or _BARE_NUMBER.match(previous)
        if _BARE_NUMBER.match(token) and not allowed:
            return True
        previous = token
    return False


def public_address(address: str | None, city_fallback: str | None, level: str) -> str | None:
    if level not in LEVELS:
        raise ValueError(f"unknown address exposure level: {level!r}")
    if level == "full":
        return address
    parsed = parse_address(address)
    city = parsed.city or city_fallback or None
    if level == "street_city" and parsed.kind == "street":
        return f"{parsed.street}, {city}"
    return city


def street_vocabulary(addresses: Iterable[str | None]) -> frozenset[str]:
    """Upper-cased first street words ("12 EXAMPLE RD" -> EXAMPLE)."""
    words = set()
    for address in addresses:
        match = _LEADING_STREET_WORD.match((address or "").split(",")[0].strip())
        if match:
            words.add(match.group(1).upper())
    return frozenset(words)


def scrub_free_text(text: str, street_words: frozenset[str] = frozenset()) -> str:
    """Remove house numbers, parcel ids and unit numbers from free text.

    A number is a house number when a street suffix follows within a few
    words, or when the next word is a known street name (street_words).
    """
    text = _FREE_TEXT_PARCEL.sub("", text)
    text = _FREE_TEXT_UNIT.sub("", text)
    text = _FREE_TEXT_HOUSE_NUMBER.sub("", text)
    text = _FREE_TEXT_NUMBER_WORD.sub(
        lambda m: m.group(1) if m.group(1).upper() in street_words else m.group(0), text
    )
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _permit_display_label(node_id: str, description: str | None, address: str | None) -> str:
    # Mirrors ingest_socrata_permits.transform_permit, over sanitized inputs.
    if description and address:
        return f"{description} at {address}"
    if description:
        return description
    if address:
        return f"Permit at {address}"
    unique_id = node_id.removeprefix("permit-marin-")
    return f"Permit {unique_id}"


def _search_terms(props: Mapping) -> str:
    # Mirrors build_search_properties.build_search_terms for Project.
    tokens = [str(props["id"]), props.get("name"), *(props.get("aliases") or [])]
    return " ".join(str(token).lower() for token in tokens if token)


def _address_keys(address: str | None) -> list[str]:
    """Every number in the street area + the first street word.

    "8 8-10 SAMPLE CT" -> 8/10 SAMPLE; "99001 STATE ROUTE 1 A K A 99003"
    -> 99001/1/99003 STATE. Deliberately coarse: unit, alias and suffix
    spellings vary between permits for one residence, and over-matching only
    fails closed.
    """
    parts = [part.strip() for part in (address or "").split(",") if part.strip()]
    while len(parts) > 1 and _STATE_ZIP.match(parts[-1]):
        parts.pop()
    street_area = " ".join(parts[:-1] if len(parts) > 1 else parts)
    word = _FIRST_WORD.search(street_area)
    if not word:
        return []
    upper = word.group(1).upper()
    return list(dict.fromkeys(f"{n} {upper}" for n in re.findall(r"\d+", street_area)))


def shared_address_levels(
    projects: Iterable[Mapping], policy: Mapping[str, str] = ADDRESS_EXPOSURE
) -> dict[str, str]:
    """Most restrictive level per street address across all Project classes.

    Permit classification is noisy (homes and apartment buildings carry
    "COMMERCIAL" permits), so an address any residential permit names is
    treated as a residence on every permit that names it.
    """
    levels: dict[str, str] = {}
    for props in projects:
        level = policy[classify_project(props)]
        for key in _address_keys(props.get("address")):
            levels[key] = max(levels.get(key, "full"), level, key=LEVELS.index)
    return levels


def contributor_eligible(node_id: str, props: Mapping) -> bool:
    """An individual's Schedule A contribution from a NetFile export; never inferred from Person type or defaults."""
    return (props.get("flow_type") == "contribution" and props.get("source_schedule") == "A"
            and props.get(ENTITY_PROP) == "IND" and bool(_NETFILE_FLOW_ID.match(node_id)))


def campaign_contributor_props(node_id: str, props: dict, level: str, reviewed: frozenset = frozenset()) -> dict:
    """An eligible flow keeps each reported value the rules and the level allow; any other flow keeps none."""
    if level not in CONTRIBUTOR_LEVELS:
        raise ValueError(f"unknown campaign_contributor level {level!r}")
    if not CONTRIBUTOR_KEYS & props.keys():
        return props
    out = {key: value for key, value in props.items() if key not in CONTRIBUTOR_KEYS}
    if contributor_eligible(node_id, props):
        for field in CONTRIBUTOR_LEVELS[level]:
            value = classify(field, props.get(PROPS[field]), reviewed).value
            if value is not None:
                out[PROPS[field]] = value
    return out


def sanitize_node_props(
    node_type: str,
    props: dict,
    policy: Mapping[str, str] = ADDRESS_EXPOSURE,
    node_id: str | None = None,
    street_words: frozenset[str] = frozenset(),
    shared_levels: Mapping[str, str] | None = None,
    reviewed: frozenset = frozenset(),
) -> dict:
    """Return props safe for the public artifact (the input object if unchanged)."""
    if node_type == "MoneyFlow":
        return campaign_contributor_props(str(node_id or props.get("id")), props, policy["campaign_contributor"],
                                          reviewed)
    if node_type != "Project":
        return props
    project_class = classify_project(props)
    level = policy[project_class]
    for key in _address_keys(props.get("address")):
        level = max(level, (shared_levels or {}).get(key, level), key=LEVELS.index)
    node_id = str(node_id or props.get("id"))
    if level == "full":
        if project_class == "civic_project" or not shared_levels:
            return props
        return _drop_private_mentions(node_id, props, shared_levels)

    out = {key: value for key, value in props.items() if key not in GEO_FIELDS}
    address = public_address(props.get("address"), props.get("city_town"), level)
    if address is None:
        out.pop("address", None)
    else:
        out["address"] = address
    street_words = street_words | street_vocabulary([props.get("address")])
    for key in FREE_TEXT_FIELDS:
        if isinstance(out.get(key), str):
            out[key] = scrub_free_text(out[key], street_words) or None
    out["display_label"] = _permit_display_label(node_id, out.get("description"), address)
    if "search_label" in out:
        out["search_label"] = str(out.get("name") or node_id)
    if "search_terms" in out:
        out["search_terms"] = _search_terms({**out, "id": node_id})
    return out


def _drop_private_mentions(node_id: str, props: dict, shared_levels: Mapping[str, str]) -> dict:
    """A full-exposure permit's free text must not name a residence's house number."""

    def drop(match: re.Match[str]) -> str:
        key = f"{match.group(1)} {match.group(2).upper()}"
        return match.group(2) if shared_levels.get(key, "full") != "full" else match.group(0)

    changed = {
        key: _NUMBER_THEN_WORD.sub(drop, props[key])
        for key in FREE_TEXT_FIELDS
        if isinstance(props.get(key), str)
    }
    changed = {key: text for key, text in changed.items() if text != props[key]}
    if not changed:
        return props
    out = {**props, **changed}
    out["display_label"] = _permit_display_label(node_id, out.get("description"), out.get("address"))
    return out
