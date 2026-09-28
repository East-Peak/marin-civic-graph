"""Per-type public property allowlist: what the bake SERIALIZES into nodes.props.

The bake derives labels, browse rows, FTS and rollups from the full
(sanitized) props, then writes only the keys below. Anything else — embedding
and cluster internals, display_label, provenance bookkeeping — never reaches
the public artifact. Edge props are not governed here (identity_links reads
assertion_id/basis/decided_at/reviewer from edges at bake time).

Each list is the union of what app/src reads for that type: facts panel,
hero stats, browse columns, temporal/ranking keys, data-query join keys and
evidence flags. tests/scripts/test_public_props.py pins the app's reads.
"""
from __future__ import annotations

from typing import Mapping

# Read on any node: entity label fallback, search envelope, editorial callout,
# and path-finder's type-agnostic event-date probe (path-finder-substrate.ts).
PATH_EVENT_DATE_KEYS = (
    "meeting_date", "decided_at", "flow_date", "signed_at", "election_date",
    "occurred_at", "proceeding_date", "date", "effective_date", "filed_at",
    "started_at", "start_date", "parent_meeting_date", "published_at", "captured_at",
)
COMMON_PUBLIC_PROPS = frozenset({
    "id", "name", "search_label", "search_terms",
    "search_key_fact", "search_last_activity", "search_rank", "jurisdiction_name",
    "editorial_note", "editorial_blurb", "editorial",
    *PATH_EVENT_DATE_KEYS,
})

_PLACE_JOINS = ("primary_place_id", "jurisdiction_place_id", "place_ids")
_ROLLUP_HERO = ("total_money", "decisions_count", "counterparties_count",
                "records_count", "evidence_count")

PUBLIC_PROPS: dict[str, frozenset[str]] = {
    "Person": frozenset({
        "current_seat_display", "aliases", "current_seat_started_at",
        "current_seat_ended_at", "service_start_date", "service_end_date",
        "filings_count",
    }),
    "Decision": frozenset({
        "title", "institution_name", "institution_id", "vote_summary", "status",
        "agenda_item_number", "item_number",
    }),
    "Project": frozenset({"status", "address", *_ROLLUP_HERO, *_PLACE_JOINS}),
    "Program": frozenset({"status", "program_type", *_ROLLUP_HERO, *_PLACE_JOINS}),
    "Case": frozenset({
        "caption", "docket_number", "closed_at", "status", "court_name", "court",
        "constrains_count", *_PLACE_JOINS,
    }),
    "Meeting": frozenset({
        "title", "institution_name", "meeting_type", "agenda_items_count",
        "decisions_count",
    }),
    "Filing": frozenset({
        "filing_type", "period_start", "period_end", "filed_by", "filed_by_name",
        "filer_name", "candidate_name",
    }),
    "Committee": frozenset({
        "fppc_id", "treasurer", "candidate_name", "elections_count", "total_money_in",
    }),
    "Organization": frozenset({"subtype", "labels", "website"}),
    "MoneyFlow": frozenset({"amount", "flow_type", "source_schedule"}),
    "Seat": frozenset({"title", "institution_name", "jurisdiction_id"}),
    "SeatService": frozenset({
        "seat_title", "person_name", "end_date", "ended_at", "jurisdiction_id", "seat_id",
    }),
    "Election": frozenset({"title", "election_type"}),
    "Candidacy": frozenset({"person_name", "seat_title", "election_name", "outcome"}),
    "AgendaItem": frozenset({"heading", "title", "meeting_title", "item_number"}),
    "Proceeding": frozenset({"title", "case_caption", "proceeding_type"}),
    "Agreement": frozenset({"title", "agreement_type", "parties", "amount", "project_id"}),
    "Amendment": frozenset({"title", "parent_title", "parent_id"}),
    "Record": frozenset({
        "record_type", "preferred_display_artifact", "preferred_public_url",
        "has_public_source",
    }),
    "Place": frozenset({"place_type", "parent_name"}),
    "Issue": frozenset({"description"}),
    "Membership": frozenset({
        "person_name", "organization_name", "role", "ended_at", "source_basis",
    }),
    "EconomicInterest": frozenset({
        "interest_type", "counterparty_name_raw", "amount_band", "amount", "position",
        "schedule",
    }),
}

# Support nodes (registry support_labels) have no UI NodeType. They keep graph
# topology (edges) and identity only; their measurement payload stays operator-side.
SUPPORT_PUBLIC_PROPS: dict[str, frozenset[str]] = {
    "ValidationCheck": frozenset({"id"}),
}

# Read by the bake to derive public surfaces, deliberately never serialized.
BAKE_ONLY_PROPS = frozenset({
    "display_label", "record_title", "label",  # _search_label fallbacks
})

_ALLOWED: dict[str, frozenset[str]] = {
    **{node_type: keys | COMMON_PUBLIC_PROPS for node_type, keys in PUBLIC_PROPS.items()},
    **SUPPORT_PUBLIC_PROPS,
}


def public_props(node_type: str, props: Mapping) -> dict:
    """The serialized props for one node; unknown types fail closed."""
    allowed = _ALLOWED.get(node_type)
    if allowed is None:
        raise ValueError(f"no public property policy for node type {node_type!r}")
    return {key: value for key, value in props.items() if key in allowed}
