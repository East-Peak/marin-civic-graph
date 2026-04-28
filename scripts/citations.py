"""has_primary_source_citation — node-level provenance check.

Used by adjacency-flow eligibility (spec §6.3.2) and ingestion validators.
Mirror of app/src/lib/citations.ts.
"""
from __future__ import annotations

ARRAY_FIELDS = ("evidence_record_ids", "record_ids")
SINGLE_FIELDS = (
    "filing_id", "fppc_report_id", "form_700_line",
    "minutes_url", "agenda_url", "meeting_url",
    "docket_number", "permit_id",
    "source_filing_id", "fppc_id",
)
PAIR_REQUIRED = (("source_url", "source_id"),)


def _is_set(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    return bool(value)


def has_primary_source_citation(node: dict) -> bool:
    for f in ARRAY_FIELDS:
        if _is_set(node.get(f)):
            return True
    for f in SINGLE_FIELDS:
        if _is_set(node.get(f)):
            return True
    for fields in PAIR_REQUIRED:
        if all(_is_set(node.get(f)) for f in fields):
            return True
    return False
