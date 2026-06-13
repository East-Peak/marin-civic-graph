"""economic_interest_builders.py — pure EconomicInterest node/edge builders (M4).

COI spec §4.2: an EconomicInterest reifies a single Form 700 disclosure line as
a node with prefix `economicinterest-`, connected by DISCLOSED_AS → from its
Filing, INTEREST_IN → to an Organization (gated: emitted only for an
operator-approved counterparty resolution — see extract_form700_interiors.py),
and the universal EVIDENCED_BY → Record for its `evidence_record_ids[]`
provenance.

Modeled on membership_builders / ingest_form700's build_* helpers: pure data
shapers in the graph ontology envelope ({id, node_type, labels, display_label,
properties} / {source_id, target_id, relationship_type, properties}), no Neo4j
connection. The extract_form700_interiors pipeline consumes these to emit
economicinterest-* nodes into load_neo4j_v2 — EconomicInterest is
ingestor-sourced, never projected via build_graph_v2.
"""
from __future__ import annotations

import re
from typing import Any

# The §4.2 interest-type vocabulary, enforced at the builder. M4 parsers emit
# only 6 of these — `business position` never comes from a parser (Sch C
# positions surface via the node's `position` field + the Membership
# convergence); the builder keeps the full set so a future/P3 caller can
# construct one directly.
INTEREST_TYPES: frozenset[str] = frozenset({
    "income source",
    "investment",
    "real property",
    "business position",
    "gift",
    "loan",
    "travel",
})


def slugify(value: str) -> str:
    """Convert a string to a lowercase URL-safe slug."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def build_economic_interest_node(
    *,
    filing_id: str,
    schedule: str,
    line_ordinal: int,
    interest_type: str,
    counterparty_name_raw: str,
    filer_normalized_name: str,
    filed_at: str,
    evidence_record_ids: list[str],
    amount_band: str | None = None,
    amount: str | None = None,
    position: str | None = None,
    confidence: float = 1.0,
) -> dict[str, Any]:
    """Build an EconomicInterest node dict from §4.2 fields.

    The id is deterministic: ``economicinterest-<filing-slug>-<schedule-slug>-
    <line-ordinal>`` where ``<filing-slug>`` is the Filing id minus its
    ``filing-form700-`` prefix and ``<line-ordinal>`` is the 1-based position of
    this EMITTED node within its schedule (the caller assigns it in document
    order). No content hashing — stable for a given staged PDF.

    ``amount_band`` XOR ``amount``: banded schedules carry a verbatim form band
    string, exact-value schedules (gift/travel) carry a verbatim dollar value,
    never both and never neither — with one carve-out: A-2 part-3 income-source
    rows carry NEITHER (the form discloses only a ≥$10,000 threshold; fabricating
    a band that is not a verbatim form literal is worse than absence).

    Fail-loud messages name the schedule, ordinal, and field keys only — never
    a raw counterparty name or band value (ethics: keys-only).
    """
    if interest_type not in INTEREST_TYPES:
        raise ValueError(
            f"unknown interest_type {interest_type!r} "
            f"(schedule {schedule} ordinal {line_ordinal}); "
            f"must be one of the §4.2 vocabulary"
        )

    has_band = amount_band is not None
    has_amount = amount is not None
    is_a2_income_source = schedule == "A-2" and interest_type == "income source"

    if is_a2_income_source:
        if has_band or has_amount:
            raise ValueError(
                f"A-2 income-source row (ordinal {line_ordinal}) must carry "
                f"neither amount_band nor amount (Predeclared 3 carve-out)"
            )
    elif has_band == has_amount:
        # both set or both unset — exactly one is required.
        raise ValueError(
            f"schedule {schedule} ordinal {line_ordinal}: exactly one of "
            f"amount_band / amount is required (got "
            f"amount_band={'set' if has_band else 'unset'}, "
            f"amount={'set' if has_amount else 'unset'})"
        )

    filing_slug = filing_id.removeprefix("filing-form700-")
    node_id = f"economicinterest-{filing_slug}-{slugify(schedule)}-{line_ordinal}"

    props: dict[str, Any] = {
        "interest_type": interest_type,
        "counterparty_name_raw": counterparty_name_raw,
        "schedule": schedule,
        "filing_id": filing_id,
        "confidence": confidence,
        "evidence_record_ids": evidence_record_ids,
    }
    if has_band:
        props["amount_band"] = amount_band
    if has_amount:
        props["amount"] = amount
    if position:
        props["position"] = position

    return {
        "id": node_id,
        "node_type": "EconomicInterest",
        "labels": ["EconomicInterest"],
        "display_label": (
            f"{interest_type} — {counterparty_name_raw} "
            f"({filer_normalized_name}, {filed_at})"
        ),
        "properties": props,
    }


def build_disclosed_as_edge(filing_id: str, economic_interest_id: str) -> dict[str, Any]:
    """Build a DISCLOSED_AS edge from a Filing node to its EconomicInterest."""
    return {
        "source_id": filing_id,
        "target_id": economic_interest_id,
        "relationship_type": "DISCLOSED_AS",
        "properties": {},
    }


def build_interest_in_edge(economic_interest_id: str, organization_id: str) -> dict[str, Any]:
    """Build an INTEREST_IN edge from an EconomicInterest node to an Organization.

    Gated by the caller: emitted only for an operator-approved counterparty
    resolution (Form 700 lines carry no deterministic identity key, so this
    never auto-fires — see extract_form700_interiors.py).
    """
    return {
        "source_id": economic_interest_id,
        "target_id": organization_id,
        "relationship_type": "INTEREST_IN",
        "properties": {},
    }


def build_evidenced_by_edge(economic_interest_id: str, record_id: str) -> dict[str, Any]:
    """Build the universal EVIDENCED_BY edge from an EconomicInterest to a Record."""
    return {
        "source_id": economic_interest_id,
        "target_id": record_id,
        "relationship_type": "EVIDENCED_BY",
        "properties": {},
    }
