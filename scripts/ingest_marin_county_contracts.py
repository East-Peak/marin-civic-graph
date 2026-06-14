"""ingest_marin_county_contracts.py — County of Marin delegated-contracts → graph (M3 leg-1).

Turns the County of Marin "delegated contracts" open-data CSV (vendor-level
contracts signed under delegated authority, July 2016→present; a SLICE of County
spend, NOT the full checkbook) into funding-IN `MoneyFlow` facts. The funder side
(County + departments) is modeled as Government `Organization` source nodes; the
recipient side is raw-name-on-the-fact (`recipient_name_raw`) until an operator
reviews a resolution and draws the gated `TO_TARGET` edge — NO recipient node is
auto-created, and NEVER a `Person` node (the file mixes orgs and individual
contractors; an individual is a small private vendor, scrutiny stays up the power
gradient, and nothing about them is ever indexed/profiled/published).

Money is `Decimal`, never float. This module NEVER fetches and NEVER touches a
live database (lazy `--load`, no top-level neo4j import), mirroring ingest_990 /
ingest_usaspending / extract_form700_interiors.

Operator capture (the loop never fetches): the dataset is published open data —
no records request needed. Full CSV in one command:
    curl -L -o delegated-contracts.csv \
      "https://data.marincounty.gov/api/views/rp6f-b7dy/rows.csv?accessType=DOWNLOAD"
SODA API for incremental pulls: https://data.marincounty.gov/resource/rp6f-b7dy.json
(no auth; $limit/$offset/$order paging). The full County AP/warrant register —
the real checkbook — is a separate CPRA records request (see the M3 runbook); this
delegated-contract slice is corroboration, never represented as total County spend.

Design reviewed adversarially by Codex (2 rounds): recipient identity is
name-only and review-gated; row-stable ids; Decimal tie-out; machine-readable
coverage honesty on every flow.
"""
from __future__ import annotations

import csv
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

# The "Review Contract" cell is "<contract#> (<url>)" — pull the URL out.
_URL_RE = re.compile(r"https?://[^)\s]+")

# CSV display-header → normalized key. (The SODA API field names differ; the CSV
# export uses these human headers.)
_HEADER_MAP = {
    "Month and Year": "month_and_year",
    "Contract Number": "contract_number",
    "Review Contract": "review_contract",
    "Department": "department",
    "Vendor Name": "vendor_name_raw",
    "Amount ($)": "amount",
    "Data Portal ID": "data_portal_id",
}


def _parse_amount(raw: str) -> Decimal | None:
    """Parse a dollar amount as Decimal. Empty/blank → None (missing, distinct
    from a real $0). Never float."""
    raw = (raw or "").strip().replace(",", "").replace("$", "")
    if raw == "":
        return None
    return Decimal(raw)


def parse_contract_rows(csv_path: Path) -> list[dict[str, Any]]:
    """Read the delegated-contracts CSV into normalized row dicts.

    Each row: {month_and_year, contract_number, review_contract (url|None),
    department, vendor_name_raw, amount (Decimal|None), data_portal_id}.
    """
    rows: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            row = {key: (raw.get(header) or "").strip()
                   for header, key in _HEADER_MAP.items()}
            row["amount"] = _parse_amount(row["amount"])
            url = _URL_RE.search(row["review_contract"])
            row["review_contract"] = url.group(0) if url else None
            rows.append(row)
    return rows


def source_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Frozen source-profile metrics — pinned by tests so a silently changed CSV
    (different row count / total) fails loud instead of skewing the graph."""
    present = [r["amount"] for r in rows if r["amount"] is not None]
    return {
        "row_count": len(rows),
        "distinct_vendor_count": len({r["vendor_name_raw"] for r in rows}),
        "distinct_data_portal_ids": len({r["data_portal_id"] for r in rows}),
        "amount_total": sum(present, Decimal("0")),
        "amount_present_count": len(present),
        "amount_missing_count": len(rows) - len(present),
        "spaced_slash_count": sum(1 for r in rows if " / " in r["vendor_name_raw"]),
    }
