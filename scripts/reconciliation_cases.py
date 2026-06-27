"""Reconciliation domain model — the typed ``ReconciliationCase`` + its validator.

Goal 1 of the civic reconciliation toolkit (Tranche 1; spec §5).

``ReconciliationCase`` is the top-level unit emitted to the workbench: an ENVELOPE
holding ``candidate_joins[]`` (pairwise ``EntityRef`` ↔ ``EntityRef`` evidence). Only
``identity_key_attach`` + ``entity_dedup_merge`` are active case types;
``relationship_candidate`` + ``pattern_candidate`` are RESERVED enum values the
validator rejects (reserved for later tranches; never emitted or actioned here).

``EntityRef`` is the normalized source endpoint — deliberately NOT named ``Record``
(the graph ``Record`` type is unrelated, evidence-only). ``actionability`` is
case/component-scoped (one decision per case), never per-join.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "recon-read-model-v1"

ACTIVE_CASE_TYPES: frozenset[str] = frozenset({"identity_key_attach", "entity_dedup_merge"})
RESERVED_CASE_TYPES: frozenset[str] = frozenset({"relationship_candidate", "pattern_candidate"})
ALL_CASE_TYPES: frozenset[str] = ACTIVE_CASE_TYPES | RESERVED_CASE_TYPES

ACTIONS: frozenset[str] = frozenset({"approve", "reject", "unsure"})
REJECTION_KINDS: frozenset[str] = frozenset({"current_evidence", "entity_distinct"})

# rejection_kind → the ledger's existing rejection STATUS (not a new basis).
_REJECTION_STATUS = {
    "current_evidence": "rejected_current_evidence",
    "entity_distinct": "rejected_entity_distinct",
}


@dataclass(frozen=True)
class EntityRef:
    """A normalized source entity endpoint (NOT the graph ``Record``)."""

    source_id: str
    local_id: str
    display_label: str
    public_fields: dict[str, Any]
    provenance: dict[str, Any]


@dataclass
class CandidateJoin:
    """Pairwise evidence inside a case. Fingerprints are PUBLIC-derived only (or None)."""

    candidate_id: str
    left_ref: EntityRef
    right_ref: EntityRef
    signals: list[str]
    signal_strength: float
    subject_fingerprint: str | None = None
    target_fingerprint: str | None = None


@dataclass
class ReconciliationCase:
    """The top-level read-model envelope. One JSONL row per case."""

    schema_version: str
    case_id: str
    case_type: str
    candidate_joins: list[CandidateJoin]
    actionability: str
    current_ledger_status: str | None = None
    ledger_assertion_refs: list[str] = field(default_factory=list)
    ai_reviews: list[dict[str, Any]] = field(default_factory=list)
    component: dict[str, Any] | None = None
    merge_plan: dict[str, Any] | None = None
    graph_context_refs: dict[str, Any] = field(default_factory=dict)


def rejection_status(rejection_kind: str) -> str:
    """Map an OperatorAction ``rejection_kind`` to the ledger rejection STATUS."""
    if rejection_kind not in REJECTION_KINDS:
        raise ValueError(
            f"unknown rejection_kind {rejection_kind!r}; must be one of {sorted(REJECTION_KINDS)}"
        )
    return _REJECTION_STATUS[rejection_kind]


def validate_case(case: ReconciliationCase) -> None:
    """Fail loud on a malformed case: reserved/unknown type or wrong join count."""
    ct = case.case_type
    if ct in RESERVED_CASE_TYPES:
        raise ValueError(f"case_type {ct!r} is reserved — not emitted or actioned in Tranche 1")
    if ct not in ACTIVE_CASE_TYPES:
        raise ValueError(f"unknown case_type {ct!r}; active: {sorted(ACTIVE_CASE_TYPES)}")
    n = len(case.candidate_joins)
    if ct == "identity_key_attach" and n != 1:
        raise ValueError(f"identity_key_attach requires exactly one join, got {n}")
    if ct == "entity_dedup_merge" and n < 1:
        raise ValueError(f"entity_dedup_merge requires at least one join, got {n}")


def validate_action(case_type: str, action: str, rejection_kind: str | None = None) -> None:
    """Enforce the §5.2.1 action matrix. Reserved case types permit NO action; ``reject``
    requires a valid ``rejection_kind``; ``rejection_kind`` is invalid for other actions."""
    if case_type in RESERVED_CASE_TYPES:
        raise ValueError(f"case_type {case_type!r} is reserved — permits no action")
    if case_type not in ACTIVE_CASE_TYPES:
        raise ValueError(f"unknown case_type {case_type!r}")
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; must be one of {sorted(ACTIONS)}")
    if action == "reject":
        if rejection_kind not in REJECTION_KINDS:
            raise ValueError(
                f"reject requires rejection_kind ∈ {sorted(REJECTION_KINDS)}, got {rejection_kind!r}"
            )
    elif rejection_kind is not None:
        raise ValueError(f"rejection_kind is only valid for action='reject', not {action!r}")
