"""enrich_org_keys.py — IRS EO-BMF parser → keyed registry org refs (Lane 1, Unit 1).

Open Marin Identity Enrichment, Lane 1 (EIN). The operator stages a Marin-filtered
slice of the IRS Exempt-Organization Business Master File (a public bulk CSV of
every IRS-recognized exempt org: EIN, NAME, CITY, STATE, SUBSECTION, NTEE_CD).
This module parses that staged CSV into registry org refs the shared resolver
(`org_resolution.propose_org_resolutions`) consumes — a LIGHTER bulk-key source
than the full-990-XML path in `ingest_990.py`; the two coexist and feed the same
ledger. There is NO fetch code here: the download is the operator step (runbook
in the CLI module — Unit 4).

The teeth (Codex round 1):

- **EIN must be EXACTLY 9 digits** after stripping non-digits, or the row is
  skipped with a logged reason — never a fabricated key. The resolver keys on any
  surviving digits, so a `123` that slipped through would manufacture a false
  merge target; it is dropped to the coverage report instead.
- **The subsection subtype is a SEPARATE field.** Identity Control A's
  `entity_class` is entity KIND (`organization` vs `committee`) and the egress
  gate compares it for equality; a registry subtype placed there would fail
  class-equality against an existing `organization` node and silently demote the
  deterministic EIN merge. So every ref keeps `entity_class: "organization"` and
  the two-digit `SUBSECTION` lands in `irs_subsection_class` (the false-friend
  signal that separates a c6 trade association from its c3 scholarship fund, and
  feeds the later dedup milestone).
- **Same-EIN rows are conflict-safe.** Byte-identical duplicate rows for one EIN
  dedupe to a single ref; rows that share an EIN but disagree on name/subsection
  are NOT first-wins — they emit a `bmf_row_conflict` and that EIN is WITHHELD
  from deterministic resolution (a contradiction the operator must see, never a
  silent pick).

Pure module: CSV in, refs/skips/conflicts out. No network, no DB.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

# Two-digit IRS subsection code → subtype class (Predeclared 2). A SEPARATE
# signal from Identity Control A's `entity_class`; never feeds the class gate.
_SUBSECTION_CLASS: dict[str, str] = {
    "03": "charity",
    "04": "social_welfare",
    "05": "labor_ag",
    "06": "trade_association",
    "07": "social_club",
    "19": "veterans",
}

# The BMF columns this lane reads. Extra columns in the staged CSV are ignored,
# so the same parser works on the full operator file and the fixture slice.
_REQUIRED_COLUMNS = ("EIN", "NAME", "CITY", "STATE", "SUBSECTION")


def irs_subsection_class(code: Any) -> str:
    """Map a BMF subsection code to its subtype class.

    Codes are two-digit strings (`"03"`, `"06"`); a stray un-padded code is
    zero-padded first. An unmapped or blank/None code → `"nonprofit_other"`
    (never blank — Predeclared 2 / the no-fabrication guardrail)."""
    if code is None:
        return "nonprofit_other"
    digits = re.sub(r"\D", "", str(code))
    if not digits:
        return "nonprofit_other"
    return _SUBSECTION_CLASS.get(digits.zfill(2), "nonprofit_other")


def _strict_ein(value: Any) -> str | None:
    """Digits only; return ONLY when exactly 9 digits survive, else None.

    Stricter than the resolver's `_normalize_ein` (which keeps any digits) — a
    registry key MUST be a full EIN or nothing, never a partial that the resolver
    would treat as a real identity."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) == 9 else None


def _titlecase_allcaps(value: str) -> str:
    """Title-case an ALL-CAPS source string for operator display; pass through
    mixed case unchanged (matches `ingest_990.title_if_allcaps`)."""
    return value.title() if value.isupper() else value


def bmf_org_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build one keyed registry org ref from a row whose EIN is already validated.

    `entity_class` is the constant `"organization"` (the subtype rides in
    `irs_subsection_class`). `evidence_record_ids` points at the row's
    `record-bmf-<ein>` provenance id (the field name the resolver + ledger expect,
    NOT `evidence`/`evidence_refs`)."""
    ein = _strict_ein(row["EIN"])
    if ein is None:  # defensive: callers validate first
        raise ValueError(f"bmf_org_ref called with non-9-digit EIN: {row['EIN']!r}")
    name = (row.get("NAME") or "").strip()
    city = (row.get("CITY") or "").strip()
    return {
        "id": f"org-bmf-ein-{ein}",
        "display_label": _titlecase_allcaps(name),
        "ein": ein,
        "entity_class": "organization",
        "irs_subsection_class": irs_subsection_class(row.get("SUBSECTION")),
        "city": _titlecase_allcaps(city),
        "state": (row.get("STATE") or "").strip().upper(),
        "evidence_record_ids": [f"record-bmf-{ein}"],
    }


def parse_bmf_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate BMF rows into refs / skipped / conflicts.

    Returns ``{"refs": [...], "skipped": [...], "conflicts": [...]}``:
    - ``refs`` — one ref per distinct, valid, non-conflicting EIN (sorted by EIN).
    - ``skipped`` — rows whose EIN is not exactly 9 digits
      (``{"reason": "ein_not_9_digits", "ein_raw", "name"}``).
    - ``conflicts`` — EINs with disagreeing name/subsection rows
      (``{"ein", "reason": "bmf_row_conflict", "variants": [...]}``); the EIN is
      WITHHELD from refs.

    Byte-identical rows for one EIN collapse to a single ref; identity here is the
    (display_label, irs_subsection_class) pair — the name/subsection the resolver
    and the dedup false-friend guard care about."""
    skipped: list[dict[str, Any]] = []
    by_ein: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        ein = _strict_ein(row.get("EIN"))
        if ein is None:
            skipped.append({
                "reason": "ein_not_9_digits",
                "ein_raw": str(row.get("EIN") or "").strip(),
                "name": (row.get("NAME") or "").strip(),
            })
            continue
        by_ein.setdefault(ein, []).append(bmf_org_ref(row))

    refs: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for ein in sorted(by_ein):
        variants = by_ein[ein]
        # Identity for dedup/conflict = (display_label, irs_subsection_class).
        distinct = {(v["display_label"], v["irs_subsection_class"]): v for v in variants}
        if len(distinct) == 1:
            refs.append(next(iter(distinct.values())))
        else:
            conflicts.append({
                "ein": ein,
                "reason": "bmf_row_conflict",
                "variants": [
                    {"display_label": dl, "irs_subsection_class": sub}
                    for (dl, sub) in sorted(distinct)
                ],
            })

    return {"refs": refs, "skipped": skipped, "conflicts": conflicts}


def parse_bmf_csv(path: str | Path) -> dict[str, Any]:
    """Parse an operator-staged BMF CSV (or fixture slice) into the
    refs/skipped/conflicts result of :func:`parse_bmf_rows`.

    Requires the columns this lane reads; a missing required column fails loud
    (never a silent all-skip)."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in _REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"BMF CSV {path} missing required columns: {missing}")
        return parse_bmf_rows(list(reader))
