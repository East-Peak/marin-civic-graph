#!/usr/bin/env python3
"""schedule_i_990.py — Form 990 Schedule I (Part II) parser for CF6.

Answers one narrow question from IRS e-file XML: which organizations did this
filer report grants to on Schedule I, per tax year? Everything is stated as
"reported on Schedule I for TY..." — never "paid", and a recipient missing
from Schedule I is not evidence of no grant (cash may include accrued grants).

Privacy by construction: the parser reads the header, two Part I/VIII totals
and Schedule I Part II rows only. Part VII officers and Schedule I Part III
(grants to individuals) are never read into the output; Part III is recorded
as a presence flag. Street address lines are never kept. Amounts stay exact
decimal strings; absent is None, never 0.

Part III text is never emitted and is not a withhold source: Schedule I Part
III reports grant types and aggregate counts, not individuals' names; person
names anywhere in the return are. Every string in an emitted grant row,
address included, is checked against those names.

Reuses ingest_990's namespace-agnostic helpers (IRS schemas vary by version).
The CLI writes only under the case staging root and a directory that
campaign_ledger.resolve_output_root accepts.

Usage:
  python scripts/schedule_i_990.py --input data/raw/990 --ein 001234567 \
      --out ~/open-marin-staging/cf6-case/analysis/schedule-i
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from campaign_ledger import UnsafeOutputError, resolve_output_root
from identity_key_normalizers import _normalize_ein
from ingest_990 import (
    _children_by_local,
    _descendant_text,
    _find_descendant,
    _is_truthy,
    _local,
)
from org_resolution import _normalize_name

ROOT = Path(__file__).resolve().parent.parent
STAGING_ROOT = Path("/Users/tammypais/open-marin-staging/cf6-case")

# Return@returnVersion values actually observed (data/raw/990 and the committed
# tests/fixtures/990 returns) whose Schedule I / header paths were checked.
# Anything else is reported as unsupported, never parsed on a guess.
SUPPORTED_RETURN_VERSIONS = frozenset({
    "2021v4.0", "2021v4.1", "2021v4.2", "2022v4.1", "2022v5.0",
    "2023v5.0", "2023v5.1", "2023v6.0", "2024v5.0",
})

WITHHELD = "[withheld: matches a person named in the return]"

MARIN_ZIP_LIST_VERSION = "usps-preferred-city-2026-10"
# USPS ZIP codes in Marin County per the California Volunteers county lookup
# (californiavolunteers.ca.gov/look-up-your-county-by-zip-code/, fetched 2026-10).
MARIN_ZIP5 = frozenset(
    "94901 94903 94904 94912 94913 94914 94915 94920 94924 94925 94929 94930 94933 94937 94938 "
    "94939 94940 94941 94942 94945 94946 94947 94948 94949 94950 94956 94957 94960 94963 94964 "
    "94965 94966 94970 94971 94973 94974 94976 94977 94978 94979 94998".split()
)


def _amount(text: str | None) -> str | None:
    """The source text when it is a decimal number, else None (exact, never 0)."""
    if text is None:
        return None
    try:
        Decimal(text)
    except InvalidOperation:
        return None
    return text


def _direct(parent: ET.Element, *path: str) -> str | None:
    """Text at an exact child path under `parent` (namespace-agnostic)."""
    nodes = [parent]
    for name in path:
        nodes = [c for n in nodes for c in _children_by_local(n, name)]
    if not nodes or nodes[0].text is None:
        return None
    return nodes[0].text.strip() or None


def _address(row: ET.Element) -> dict[str, str | None]:
    us = next(iter(_children_by_local(row, "USAddress")), None)
    if us is not None:
        zip_text = _descendant_text(us, "ZIPCd", "ZIPCode") or ""
        digits = re.sub(r"\D", "", zip_text)
        return {
            "country": "US",
            "city": _descendant_text(us, "CityNm", "City"),
            "state": _descendant_text(us, "StateAbbreviationCd", "State"),
            "zip5": digits[:5] if len(digits) >= 5 else None,
        }
    foreign = next(iter(_children_by_local(row, "ForeignAddress")), None)
    if foreign is not None:
        return {"country": _descendant_text(foreign, "CountryCd", "Country"),
                "city": _descendant_text(foreign, "CityNm", "City"), "state": None, "zip5": None}
    return {"country": None, "city": None, "state": None, "zip5": None}


def _recipient_name(row: ET.Element) -> str | None:
    block = next(iter(_children_by_local(row, "RecipientBusinessName")), None)
    if block is None:
        return None
    line1 = _descendant_text(block, "BusinessNameLine1Txt", "BusinessNameLine1")
    line2 = _descendant_text(block, "BusinessNameLine2Txt", "BusinessNameLine2")
    return " ".join(p for p in (line1, line2) if p) or None


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


def _forbidden_values(root: ET.Element) -> set[str]:
    """Normalized person names (any *PersonNm, in both word orders) in this return.

    Free-text Schedule I fields are checked against these before output, so a
    name copied from Part VII into a purpose line cannot leak. Part III holds
    grant types and counts, not names; it is never emitted and never matched.
    """
    found: set[str] = set()
    for el in root.iter():
        text = _norm(el.text or "")
        if _local(el.tag).endswith("PersonNm") and text:
            tokens = text.split()
            found.update({text, " ".join(tokens[1:] + tokens[:1]), " ".join(tokens[-1:] + tokens[:-1])})
    return {f for f in found if len(f) >= 4}


class _Redactor:
    def __init__(self, forbidden: set[str]) -> None:
        self.forbidden, self.withheld = forbidden, 0

    def __call__(self, value: str | None) -> str | None:
        padded = f" {_norm(value or '')} "
        if value and any(f" {f} " in padded for f in self.forbidden):
            self.withheld += 1
            return WITHHELD
        return value


def _redact_strings(value: Any, redact: _Redactor) -> Any:
    """Apply `redact` to every string in a (nested) emitted structure, not a field list."""
    if isinstance(value, dict):
        return {k: _redact_strings(v, redact) for k, v in value.items()}
    return redact(value) if isinstance(value, str) else value


def _grant_row(row: ET.Element, redact: _Redactor) -> dict[str, Any]:
    ein = _normalize_ein(_direct(row, "RecipientEIN"))
    return _redact_strings({
        "recipient_name": _recipient_name(row),
        "recipient_ein": ein,
        "address": _address(row),
        "irc_section": _direct(row, "IRCSectionDesc"),
        "cash_grant_amt": _amount(_direct(row, "CashGrantAmt")),
        "non_cash_assistance_amt": _amount(_direct(row, "NonCashAssistanceAmt")),
        "non_cash_description": _direct(row, "NonCashAssistanceDesc"),
        "valuation_method": _direct(row, "ValuationMethodUsedDesc"),
        "purpose": _direct(row, "PurposeOfGrantTxt"),
    }, redact)


def _schedule_i(return_data: ET.Element, redact: _Redactor) -> dict[str, Any]:
    sched = next(iter(_children_by_local(return_data, "IRS990ScheduleI")), None)
    if sched is None:
        return {"present": False, "part_ii_present": False, "part_iii_present": False, "grants": None}
    rows = _children_by_local(sched, "RecipientTable")
    return {
        "present": True,
        "part_ii_present": bool(rows),
        "part_iii_present": bool(_children_by_local(sched, "GrantsOtherAsstToIndivInUSGrp")),
        "grants": [_grant_row(r, redact) for r in rows] if rows else None,
    }


def parse_return(source: Path | str | bytes, object_id: str | None = None) -> dict[str, Any]:
    """Parse one e-file return; never raises for a recognised non-990 or unknown version."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        object_id = object_id or path.stem.removesuffix("_public")
        source = path.read_bytes()
    root = ET.fromstring(source)
    header = next(iter(_children_by_local(root, "ReturnHeader")), None)
    return_data = next(iter(_children_by_local(root, "ReturnData")), None)
    filer = _find_descendant(header, "Filer") if header is not None else None
    ein = _normalize_ein(_descendant_text(filer, "EIN")) if filer is not None else None
    if return_data is None or not ein:
        raise ValueError(f"not an IRS e-file Return with a Filer EIN ({object_id or 'inline'})")

    period_end = _descendant_text(header, "TaxPeriodEndDt")
    irs990 = next(iter(_children_by_local(return_data, "IRS990")), None)
    out: dict[str, Any] = {
        "ein": ein,
        "return_type": _descendant_text(header, "ReturnTypeCd"),
        "return_version": root.attrib.get("returnVersion"),
        "tax_year": _descendant_text(header, "TaxYr") or (period_end[:4] if period_end else None),
        "tax_period_begin": _descendant_text(header, "TaxPeriodBeginDt"),
        "tax_period_end": period_end,
        "return_ts": _descendant_text(header, "ReturnTs"),
        "amended": _is_truthy(_descendant_text(root, "AmendedReturnInd")),
        "object_id": object_id,
        "total_revenue": None,
        "government_grants": None,
        "schedule_i": None,
        "withheld_fields": 0,
    }
    if out["return_type"] != "990" or irs990 is None:
        out["status"] = "not_form_990"
    elif out["return_version"] not in SUPPORTED_RETURN_VERSIONS:
        out["status"] = "unsupported_version"
    else:
        out["status"] = "ok"
        out["total_revenue"] = _amount(
            _direct(irs990, "TotalRevenueGrp", "TotalRevenueColumnAmt") or _direct(irs990, "CYTotalRevenueAmt"))
        out["government_grants"] = _amount(_descendant_text(irs990, "GovernmentGrantsAmt"))
        redact = _Redactor(_forbidden_values(root))
        out["schedule_i"] = _schedule_i(return_data, redact)
        out["withheld_fields"] = redact.withheld
    return out


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _ts(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return parsed if parsed and parsed.tzinfo else None  # naive times compare unsafely


def _year_key(year: str) -> tuple[int, str]:
    return (int(year), year) if year.isdigit() else (-1, year)


def select_latest_per_year(parsed: list[dict[str, Any]], ein: str) -> dict[str, Any]:
    """Latest ReturnTs per tax year among Form 990 returns of `ein`, supported or not.

    The latest filing decides: if it is an unsupported version the year is
    reported as `unsupported_latest` (a gap), never replaced by an older
    parse. Equal or missing ReturnTs makes the year `ambiguous`; the pick is
    then the highest object_id, deterministic but flagged.
    """
    want = _normalize_ein(ein)
    eligible = [r for r in parsed if r["status"] in ("ok", "unsupported_version") and r["ein"] == want
                and r["return_type"] == "990" and r["tax_year"]]
    by_year: dict[str, list[dict[str, Any]]] = {}
    for r in eligible:
        by_year.setdefault(r["tax_year"], []).append(r)

    years = []
    for year in sorted(by_year, key=_year_key, reverse=True)[:3]:
        group = by_year[year]
        stamped = [(t, r) for r in group if (t := _ts(r["return_ts"])) is not None]
        latest = max((t for t, _ in stamped), default=None)
        pool = [r for t, r in stamped if t == latest] if latest else group
        chosen = max(pool, key=lambda r: r["object_id"] or "")
        entry = {
            "tax_year": year,
            "status": "ok" if chosen["status"] == "ok" else "unsupported_latest",
            "object_id": chosen["object_id"],
            "amended": chosen["amended"],
            "superseded": sorted(r["object_id"] for r in group if r is not chosen),
            "ambiguous": len(pool) > 1 or len(stamped) < len(group),
        }
        if entry["status"] != "ok":
            entry["return_version"] = chosen["return_version"]
        years.append(entry)
    return {
        "ein": want,
        "years": years,
        "considered": [{"object_id": r["object_id"], "tax_year": r["tax_year"], "return_ts": r["return_ts"],
                        "status": r["status"], "return_version": r["return_version"]}
                       for r in sorted(eligible, key=lambda r: (_year_key(r["tax_year"]), r["object_id"] or ""))],
    }


# ---------------------------------------------------------------------------
# Geography and target matching
# ---------------------------------------------------------------------------


def marin_rule(address: dict[str, str | None]) -> str:
    """"in_rule" iff country US, state CA and ZIP5 in MARIN_ZIP5.

    A reporting convenience, not a residency finding: the list
    (MARIN_ZIP_LIST_VERSION) is an approximation — some ZIPs cross county
    lines and PO-box ZIPs say nothing about where an organization operates.
    Foreign or non-CA or other-ZIP is "outside_rule"; missing data is "unknown".
    """
    country, state, zip5 = address.get("country"), address.get("state"), address.get("zip5")
    if country is None:
        return "unknown"
    if country != "US" or (state is not None and state != "CA"):
        return "outside_rule"
    if state is None or zip5 is None:
        return "unknown"
    return "in_rule" if zip5 in MARIN_ZIP5 else "outside_rule"


def match_targets(grant: dict[str, Any], targets: list[dict[str, Any]]) -> str | None:
    """"ein_match:<label>" or "name_match:<label>"; geography plays no part.

    Name equality (normalized) is a fallback only for a recipient that
    reports no EIN: a differing EIN is evidence of a different organization.
    """
    ein = _normalize_ein(grant.get("recipient_ein"))
    if ein:
        for t in targets:
            if ein in {_normalize_ein(e) for e in t.get("eins", [])}:
                return f"ein_match:{t['label']}"
        return None
    name = _normalize_name(grant.get("recipient_name") or "")
    if name:
        for t in targets:
            if name in {_normalize_name(n) for n in t.get("names", [])}:
                return f"name_match:{t['label']}"
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def resolve_safe_output(out: Path) -> Path:
    """`out` must resolve (symlinks followed) under STAGING_ROOT and pass resolve_output_root."""
    resolved = Path(out).expanduser().resolve()
    staging = STAGING_ROOT.resolve()
    if staging not in resolved.parents:
        raise UnsafeOutputError(f"output must be under {staging}")
    return resolve_output_root(resolved, ROOT)


def _input_files(inputs: list[str]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        p = Path(item)
        files.extend(sorted(p.glob("*.xml")) if p.is_dir() else [p])
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", nargs="+", required=True, help="XML files or directories")
    ap.add_argument("--ein", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)

    out = resolve_safe_output(args.out)
    returns = [parse_return(f) for f in _input_files(args.input)]
    out.mkdir(parents=True, exist_ok=True)
    payload = {"selection": select_latest_per_year(returns, args.ein), "returns": returns}
    (out / "schedule-i.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
