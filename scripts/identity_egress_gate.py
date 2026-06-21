"""identity_egress_gate.py — the ledger-aware public-egress gate (A, Unit 4).

Layer 3 of the three-layer identity model. It sits between candidate generation
(the resolver / ingestors) and the public graph, and is the ONLY thing that may
turn an identity decision into a published join. It NEVER edits the resolver.

Two entry points:

- `gate_same_as_edges()` — gate resolver-emitted SAME_AS through the ledger.
  An allowed self-identity merge (`deterministic_merge_allowed`) becomes a
  `deterministic` ledger assertion and the edge is stamped with its id. A
  relationship-semantics "merge" (fiscal sponsor / parent UEI / PAC / DBA /
  project) is DEMOTED — no SAME_AS, a queued relationship candidate. An endpoint
  missing from the refs or lacking the egress class schema fails closed
  (Predeclared 4). Empty input → empty output (a clean no-op for the real
  zero-SAME_AS Marin case, so the ingestors stay back-compatible).

- `join_citation()` — the both-ways gate every APPROVED egress path (County
  TO_TARGET, M4 INTEREST_IN, dual-role lanes) consults: a `deterministic` or
  `approved` assertion yields its id to cite in the join; any non-publishing
  status (`queued` / `rejected_current_evidence` / `rejected_entity_distinct` /
  `superseded`) yields None — NO join.
"""
from __future__ import annotations

from typing import Any

from identity_ledger import is_publishing, make_assertion
from identity_resolution_adapter import deterministic_merge_allowed, egress_ref_complete


def gate_same_as_edges(
    same_as_edges: list[dict[str, Any]],
    refs_by_id: dict[str, dict[str, Any]],
    *,
    policy_version: str,
    reviewer: str = "system",
    decided_at: str = "deterministic",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Gate resolver SAME_AS through the ledger → (gated_edges, assertions, demoted)."""
    gated: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []

    for edge in same_as_edges:
        s_id, t_id = edge["source_id"], edge["target_id"]
        subject = refs_by_id.get(s_id)
        target = refs_by_id.get(t_id)
        if subject is None or target is None:
            raise ValueError(
                f"egress gate: SAME_AS endpoint not in refs_by_id (fail closed): "
                f"{s_id} -> {t_id}"
            )
        # An egress-capable SAME_AS MUST carry the class schema, or fail closed —
        # the guardrail cannot judge an un-classed key (Predeclared 4).
        if not (egress_ref_complete(subject) and egress_ref_complete(target)):
            raise ValueError(
                f"egress gate: SAME_AS ref missing class schema (fail closed): "
                f"{s_id} -> {t_id}"
            )

        if not deterministic_merge_allowed(subject, target):
            # Relationship semantics (sponsor/parent/PAC/dba/project) or class
            # mismatch → never a SAME_AS; a queued relationship candidate.
            demoted.append({
                "subject_ref": s_id,
                "candidate_ref": t_id,
                "basis": "relationship_candidate",
                "key_semantics": subject.get("key_semantics"),
                "status": "queued",
            })
            continue

        assertion = make_assertion(
            subject_ref=s_id,
            target_ref=t_id,
            status="deterministic",
            basis=edge["properties"]["basis"],
            subject=subject,
            target=target,
            reviewer=reviewer,
            decided_at=decided_at,
            policy_version=policy_version,
        )
        assertions.append(assertion)
        stamped = dict(edge)
        stamped["properties"] = {**edge["properties"], "assertion_id": assertion["id"]}
        gated.append(stamped)

    return gated, assertions, demoted


def join_citation(assertion: dict[str, Any]) -> str | None:
    """The id to cite in a public join, or None when the assertion is
    non-publishing (the gate that keeps queued/rejected/superseded off the
    public graph)."""
    return assertion["id"] if is_publishing(assertion) else None


# Default policy version stamped on assertions this milestone writes.
POLICY_VERSION = "v1"


def gate_ingestor_same_as(
    same_as_edges: list[dict[str, Any]],
    new_refs: list[dict[str, Any]],
    existing_refs: list[dict[str, Any]],
    *,
    source_system: str,
    policy_version: str = POLICY_VERSION,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Convenience for an ingestor (990/USASpending): build egress-ready refs
    from its plain org refs — an ingestor's own EIN/UEI is the org's OWN identity
    (`key_semantics: "self"`, `entity_class: "organization"`) unless the ref
    already overrides them — then gate the resolver's SAME_AS through the ledger.
    Empty SAME_AS → empty output (the real zero-merge Marin case stays a no-op)."""
    refs_by_id: dict[str, dict[str, Any]] = {}
    for ref in (*new_refs, *existing_refs):
        refs_by_id[ref["id"]] = {
            "entity_class": "organization",
            "source_system": source_system,
            "key_semantics": "self",
            **ref,
        }
    return gate_same_as_edges(same_as_edges, refs_by_id, policy_version=policy_version)
