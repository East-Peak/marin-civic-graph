"""Reconciliation read-model emitter — the versioned, ledger-aware, redaction-bounded
candidate read model the Tranche-2 workbench UI consumes.

Goal 1 of the civic reconciliation toolkit (Tranche 1; spec §5). Built across two
units: Unit 3 (the redaction boundary primitives below) and Unit 6 (the full
``ReconciliationCase``-envelope emitter that collapses the EIN/sos/committee adapters
+ AI-adjudicator verdicts + the ledger into one contract).

REDACTION BOUNDARY (spec §5.4): the emitter serializes ONLY each adapter's declared
public fields, runs ``scan_for_forbidden`` over the FINAL output, and may emit ONLY
``public_hash(public_fields)`` for any hash — it must NEVER copy a ledger assertion's
``subject_fingerprint`` / ``target_fingerprint`` / ``source_snapshot_hash`` (those
derive from the full, possibly-PII subject/target).
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from dedup_merge_applier import apply_component_merge
from enrich_casos_keys import scan_for_forbidden  # consume the shipped recursive leak scan
from identity_ledger import make_assertion
from reconciliation_cases import OperatorAction, rejection_status, validate_action

# Ledger namespacing (spec §5.2): attach assertions and dedup assertions live in
# distinct files; dedup bases are prefixed `org_dedup` and ONLY they assemble into
# merge components. An attach assertion can never enter a dedup component.
ATTACH_LEDGER = "data/identity/assertions.jsonl"
DEDUP_LEDGER = "data/identity/dedup-assertions.jsonl"

POLICY_VERSION = "recon-read-model-v1"


def public_hash(public_fields: dict[str, Any]) -> str:
    """A stable hash over ONLY the given public fields — the sole hash the read model
    may emit. Order-independent; ``pub-`` prefixed so it can never be mistaken for (or
    collide with) a ledger assertion's private-derived fingerprint/snapshot hash."""
    blob = json.dumps(public_fields, sort_keys=True, separators=(",", ":"), default=str)
    return "pub-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def forbidden_violations(obj: Any) -> list[str]:
    """The read model's leak gate: recursive ``scan_for_forbidden`` over emitted output.
    Returns a list of violations ([] = clean). The emitter asserts this is empty over
    the FINAL serialized rows before writing."""
    return scan_for_forbidden(obj)


# --- MergePlan (entity_dedup_merge only; spec §5.3) -------------------------

def build_merge_plan(component: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Dry-run the dedup merge over a SCRATCH copy of ``graph`` → the MergePlan (counts
    only). Computed from ``dedup_merge_applier.apply_component_merge`` (NOT component
    membership alone), so ``edge_ops_count`` / ``selfloop_drops`` / ``collision_count``
    reflect the real applier. Never mutates the input graph. NODE policy =
    tombstone_no_field_merge; EDGE policy = parallel edges collapse via
    ``apoc.merge.relationship`` (the ``collapse`` op)."""
    record = apply_component_merge(copy.deepcopy(graph), component)
    edge_ops = record["edge_ops"]
    return {
        "canonical_id": record["canonical_id"],
        "superseded_ids": list(record["superseded_ids"]),
        "edge_ops_count": len(edge_ops),
        "selfloop_drops": sum(1 for o in edge_ops if o["op"] == "selfloop_drop"),
        "collision_count": sum(1 for o in edge_ops if o["op"] == "collapse"),
        "node_policy": "tombstone_no_field_merge",
        "edge_policy": "apoc_merge_relationship_collapse",
    }


# --- OperatorAction → ledger write (spec §5.2.1 action matrix) ---------------

def operator_action_to_ledger(
    action: OperatorAction,
    *,
    attach_builder=None,
    candidate: dict[str, Any] | None = None,
    vendor_ref: dict[str, Any] | None = None,
    subject: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any] | None:
    """Map one ``OperatorAction`` to its ledger write, routed to the correct namespace.

    Returns ``None`` for ``unsure`` (no write), else a dict
    ``{ledger, assertion, same_as}``. ``identity_key_attach``/approve delegates to the
    lane's ``build_*_attach`` (``attach_builder``) → (assertion, SAME_AS) into the
    ATTACH ledger; reject writes an attach-namespace rejection assertion. ``entity_dedup_merge``
    writes an ``org_dedup_operator_*`` assertion into the DEDUP ledger (approve = status
    ``approved``, basis ``org_dedup_operator_approved`` — the human name-tier merge, NOT
    the deterministic same-key path). Attach bases are never ``org_dedup*``."""
    validate_action(action.case_type, action.action, action.rejection_kind)
    if action.action == "unsure":
        return None

    if action.case_type == "identity_key_attach":
        if action.action == "approve":
            if attach_builder is None:
                raise ValueError("identity_key_attach/approve requires an attach_builder")
            assertion, same_as = attach_builder(
                candidate, vendor_ref,
                reviewer=action.reviewer, decided_at=action.decided_at, policy_version=policy_version,
            )
            return {"ledger": ATTACH_LEDGER, "assertion": assertion, "same_as": same_as}
        # reject → attach-namespace rejection status (never org_dedup*)
        assertion = make_assertion(
            subject_ref=subject["id"], target_ref=target["id"],
            status=rejection_status(action.rejection_kind),
            basis=f"operator_rejected_{action.key_type}",
            subject=subject, target=target,
            reviewer=action.reviewer, decided_at=action.decided_at, policy_version=policy_version,
        )
        return {"ledger": ATTACH_LEDGER, "assertion": assertion, "same_as": None}

    # entity_dedup_merge → DEDUP ledger, org_dedup_operator_* basis
    if action.action == "approve":
        status, basis = "approved", "org_dedup_operator_approved"
    else:
        status, basis = rejection_status(action.rejection_kind), "org_dedup_operator_rejected"
    assertion = make_assertion(
        subject_ref=subject["id"], target_ref=target["id"], status=status, basis=basis,
        subject=subject, target=target,
        reviewer=action.reviewer, decided_at=action.decided_at, policy_version=policy_version,
    )
    return {"ledger": DEDUP_LEDGER, "assertion": assertion, "same_as": None}
