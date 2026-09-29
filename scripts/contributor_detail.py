"""Reported contributor detail: what an individual's Schedule A contribution may show about its contributor.

Donations are investigatable (decisions/2026-09-29-open-marin-donor-exposure.md): the contributor's occupation,
employer, city, state and ZIP5 are public, as reported on the filing; the street address never is. The details
live on each contribution (the MoneyFlow), never on the Person: name-slug Persons merge namesakes.

This module is the one policy every stage shares. The normalizer attaches its outcomes to counted MoneyFlows, the
bake re-applies it before any public derivation, the migration plan recomputes it from the ledger to verify, and
the privacy scan reuses its detectors. The raw cells stay in the private ledger; a display value differs from its
cell only by collapsed whitespace, and a value the rules below exclude is withheld whole, never edited.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable, Mapping, NamedTuple

FIELDS = ("occupation", "employer", "city", "state", "zip5")
PROPS = {field: f"reported_{field}" for field in FIELDS}
ENTITY_PROP = "reported_entity_cd"  # private eligibility marker: explicit IND on every reporting row
LEDGER_KEYS = {"occupation": "occupation", "employer": "employer", "city": "city", "state": "state", "zip5": "zip"}
REVIEWED_PATH = Path(__file__).resolve().parent.parent / "registry" / "contributor-detail-reviewed.json"

# Why a populated source value does not publish. Every rule is counted in the coverage report.
WITHHELD_RULES = (
    "non_text_cell", "malformed_zip", "malformed_state", "malformed_city",
    "phone", "email", "url", "street", "suspected_pii_unreviewed", "conflicting_reports",
)

USPS_CODES = frozenset("""
    AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK
    OR PA RI SC SD TN TX UT VT VA WA WV WI WY AS GU MP PR VI UM FM MH PW AA AE AP
""".split())

_ZIP = re.compile(r"([0-9]{5})(?:-[0-9]{4})?")  # ASCII digits only: a look-alike digit is not a ZIP
_CITY = re.compile(r"[^\W\d_](?:[^\W\d_]|[ .'’()-])*")  # letters in any script, as spelled
_SUFFIX = (
    r"(?:ST|STREET|RD|ROAD|DR|DRIVE|AVE|AVENUE|BLVD|BOULEVARD|LN|LANE|CT|COURT|WAY|PL|PLACE|CIR|CIRCLE|TER|"
    r"TERRACE|HWY|HIGHWAY|TRL|TRAIL|PKWY|PARKWAY|LOOP|ROW|ALY|ALLEY|PATH|DOCK|PIER|SQ|SQUARE|PLZ|PLAZA|"
    r"CRES|CRESCENT|XING|CROSSING)"
)
# Contact or address shapes: withheld outright, whatever else the value says.
CONTACT_DETECTORS: tuple[tuple[str, re.Pattern], ...] = (
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("url", re.compile(r"\bhttps?://|\bwww\.", re.I)),
    ("phone", re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
                         r"|(?<![\d-])\d{3}[\s.-]\d{4}(?!\d)")),
    ("street", re.compile(
        rf"\b\d+[A-Z]?\s+(?:[\w'.-]+\s+){{0,3}}{_SUFFIX}\b\.?"  # house number + street suffix
        r"|\bP\.?\s*O\.?\s*BOX\b|\bPOST\s+OFFICE\s+BOX\b"
        r"|\b(?:APT|APARTMENT|SUITE|STE)\b\.?\s*#?\s*\d+"
        r"|\b[A-Z]{2}\.?\s+\d{5}(?:-\d{4})?\b", re.I)),  # an embedded "ST 99999": the tail of an address
)
# Other text that may be personal information: withheld until Stuart reviews the value.
SUSPECT_DETECTORS: tuple[tuple[str, re.Pattern], ...] = (
    ("domain", re.compile(r"\b[\w-]+\.(?:com|net|org|edu|gov|io|co|us|biz|info|me)\b", re.I)),
    ("id_number", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)|\d{5,}")),
    ("date", re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")),
    ("house_number", re.compile(r"(?:^|[,;]\s*)\d+[A-Z]?\s+[A-Z]", re.I)),  # "12 Sample Ridge" with no suffix
    ("unit", re.compile(r"\bUNIT\s*#?\s*\d+|#\s*\d+", re.I)),
    ("care_of", re.compile(r"\bc/o\b|\bcare\s+of\b", re.I)),
    ("relationship", re.compile(
        r"\b(?:spouse|wife|husband|son|daughter|mother|father|child|widow|widower)\s+of\b"
        r"|\bmy\s+(?:wife|husband|spouse|son|daughter|mother|father|partner|family)\b", re.I)),
    ("birth_or_ssn", re.compile(r"\b(?:DOB|D\.O\.B|SSN|social\s+security|date\s+of\s+birth|born)\b", re.I)),
)


class Outcome(NamedTuple):
    value: str | None  # the display value to publish, or None
    rule: str | None  # why nothing publishes: source_missing or a WITHHELD_RULES entry


def display(raw) -> str | None:
    """The one normalization a display value gets: whitespace collapsed. Blank means missing."""
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    return text or None


def review_key(field: str, value: str) -> tuple[str, str]:
    return field, hashlib.sha256(display(value).encode()).hexdigest()


def load_reviewed(path: Path = REVIEWED_PATH) -> frozenset[tuple[str, str]]:
    """Stuart's publish decisions for flagged values, as (field, sha256 of the display value): never the text."""
    entries = json.loads(Path(path).read_text())["reviewed"]
    keys = set()
    for entry in entries:
        if entry.get("field") not in FIELDS or entry.get("decision") != "publish" \
                or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))):
            raise ValueError(f"not a publish decision on a contributor field: {entry!r}")
        keys.add((entry["field"], entry["sha256"]))
    return frozenset(keys)


def detect(text: str, detectors: Iterable[tuple[str, re.Pattern]]) -> str | None:
    return next((name for name, pattern in detectors if pattern.search(text)), None)


def classify(field: str, raw, reviewed: frozenset = frozenset()) -> Outcome:
    """One reported cell's public outcome under the rules above."""
    if raw is not None and not isinstance(raw, str):
        return Outcome(None, "non_text_cell")
    value = display(raw)
    if value is None:
        return Outcome(None, "source_missing")
    if field == "zip5":
        match = _ZIP.fullmatch(value)
        return Outcome(match.group(1), None) if match else Outcome(None, "malformed_zip")
    if field == "state":
        return Outcome(value, None) if value.upper() in USPS_CODES else Outcome(None, "malformed_state")
    contact = detect(value, CONTACT_DETECTORS)
    if contact:
        return Outcome(None, contact)
    if detect(value, SUSPECT_DETECTORS) and review_key(field, value) not in reviewed:
        return Outcome(None, "suspected_pii_unreviewed")
    if field == "city" and not _CITY.fullmatch(value):
        return Outcome(None, "malformed_city")
    return Outcome(value, None)


def _comparable(field: str, raw) -> object:
    """What two reports must share to agree: the whole cell up to whitespace, before any reduction or redaction."""
    return raw if raw is not None and not isinstance(raw, str) else display(raw)


def eligibility(schedule: str, rows: list[Mapping]) -> str | None:
    """None when every reporting row is an explicitly coded individual's Schedule A contribution; else why not."""
    if schedule != "A":
        return "not_schedule_a"
    codes = {row.get("entity_cd") for row in rows}
    if len(codes) != 1 or None in codes:
        return "entity_code_missing_or_conflicting"
    return None if codes == {"IND"} else "entity_code_not_ind"


def transaction_details(schedule: str, rows: list[Mapping], reviewed: frozenset = frozenset()
                        ) -> tuple[str | None, dict[str, Outcome]]:
    """(ineligibility reason, {field: outcome}) for one counted transaction from all of its reporting rows.

    Reports that agree on a field share it; reports that disagree withhold it (each raw value stays in the ledger).
    Fields are never mixed from different reports: a published field is one every report gives.
    """
    reason = eligibility(schedule, rows)
    if reason:
        return reason, {}
    details = {}
    for field in FIELDS:
        cells = [row["reported"].get(LEDGER_KEYS[field]) for row in rows]
        if len({json.dumps(_comparable(field, cell)) for cell in cells}) > 1:
            details[field] = Outcome(None, "conflicting_reports")
        else:
            details[field] = classify(field, cells[0], reviewed)
    return None, details


def flow_props(details: Mapping[str, Outcome]) -> dict:
    """The MoneyFlow props for an eligible transaction: the marker plus every field that publishes."""
    if not details:
        return {}
    return {ENTITY_PROP: "IND", **{PROPS[f]: o.value for f, o in details.items() if o.value is not None}}
