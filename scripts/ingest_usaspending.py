"""USASpending prime-award ingestion — funding-IN ledger, leg 2 (M2c).

Parses operator-downloaded USASpending API JSON pages (the
`POST /api/v2/search/spending_by_award/` endpoint) into namespaced
`Organization` recipient/agency nodes, award-level `MoneyFlow` facts,
`Record` provenance, and FROM_SOURCE/TO_TARGET/EVIDENCED_BY edges.
Recipient→existing-org joins reuse the shared resolver
(`org_resolution.propose_org_resolutions`, identity_keys=("ein", "uei")):
deterministic identity-key merges only, everything judged lands in the
`ResolutionCandidate` JSONL sidecar (spec §4.4 — enrichment-only until
recipient resolution is reviewed).

THIS MODULE NEVER FETCHES AND NEVER TOUCHES A DATABASE. The download and
`--load` are operator steps (procedure at the bottom of this docstring).

Scope: PRIME awards only. Sub-awards (`/api/v2/subawards/`) are explicitly
deferred (M2d-prep or M3) — pass-through visibility requires the sub-award
endpoint and is a separate coverage claim.

Ethics floor: recipients are organizations receiving public money (scrutiny
up the power gradient). Aggregate award records (`generated_internal_id`
prefix `ASST_AGG_`) are published in aggregate precisely because the
underlying recipients are individuals/PII-redacted — they are SKIPPED, never
ingested; no Person nodes from this source; skip logs carry the award id +
marker only, never the recipient string.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("ingest_usaspending")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Aggregate award records: county-level rollups whose underlying recipients
# are individuals (PII-redacted) — the structural skip marker (Decision 2).
AGGREGATE_PREFIX = "ASST_AGG_"

# Rows with no recipient identity at all cannot anchor an Organization node.
# On real data this coincides with the ASST_AGG_ rows.
NO_IDENTITY_MARKER = "no_recipient_identity"


# ---------------------------------------------------------------------------
# Parser — API response pages → award dicts (Decisions 1–2)
# ---------------------------------------------------------------------------


def parse_award_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """One API result row → a parsed award dict, or None for a logged skip.

    Identity is `generated_internal_id` — fails loud when absent. Skips
    (never errors): aggregate rows (`ASST_AGG_` prefix) and rows with
    neither UEI nor `recipient_id`. The skip log carries the award id and
    the marker(s) ONLY — never the recipient string (ethics floor: logs
    and evidence files are artifacts too).
    """
    award_id = row.get("generated_internal_id")
    if not award_id:
        raise ValueError(
            "award row missing generated_internal_id — cannot anchor "
            "identity; refusing to guess"
        )

    markers = []
    if award_id.startswith(AGGREGATE_PREFIX):
        markers.append(AGGREGATE_PREFIX)
    if not row.get("Recipient UEI") and not row.get("recipient_id"):
        markers.append(NO_IDENTITY_MARKER)
    if markers:
        logger.info("skipping award %s: %s", award_id, "+".join(markers))
        return None

    return {
        "award_id": award_id,
        "recipient_name": row.get("Recipient Name"),
        "recipient_id": row.get("recipient_id"),
        "uei": row.get("Recipient UEI"),
        "amount": row.get("Award Amount"),
        "start_date": row.get("Start Date"),
        "end_date": row.get("End Date"),
        "awarding_agency": row.get("Awarding Agency"),
        "awarding_sub_agency": row.get("Awarding Sub Agency"),
        "funding_agency": row.get("Funding Agency"),
        "funding_sub_agency": row.get("Funding Sub Agency"),
        "award_type": row.get("Award Type"),
        "cfda_number": row.get("CFDA Number"),
        "agency_slug": row.get("agency_slug"),
    }


def parse_awards_page(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One loaded API response body → parsed award dicts (skips dropped)."""
    awards = []
    for row in data.get("results", []):
        award = parse_award_row(row)
        if award is not None:
            awards.append(award)
    return awards


def parse_awards_file(path: Path) -> list[dict[str, Any]]:
    """One downloaded response page on disk → parsed award dicts."""
    return parse_awards_page(json.loads(Path(path).read_text()))
