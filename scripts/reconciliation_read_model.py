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
from pathlib import Path
from typing import Any

from dedup_merge_applier import apply_component_merge
from enrich_casos_keys import scan_for_forbidden  # consume the shipped recursive leak scan
from identity_ledger import fingerprint, make_assertion, read_assertions, should_requeue
from reconciliation_cases import (
    CandidateJoin,
    EntityRef,
    OperatorAction,
    ReconciliationCase,
    rejection_status,
    validate_action,
    validate_case,
)

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


# --- ledger status (read-model wrapper; spec §5.5/Predeclared 10) ------------

def load_ledger(path: str | Path, *, allow_missing: bool = False) -> list[dict[str, Any]]:
    """Read a ledger JSONL. ``read_assertions`` returns ``[]`` for a missing file, so
    this wrapper fails loud on a MISSING path unless ``allow_missing`` (an explicitly
    empty ledger) — the read model must not silently report 'none' on a typo'd path."""
    p = Path(path)
    if not p.is_file():
        if allow_missing:
            return []
        raise FileNotFoundError(
            f"ledger path {str(path)!r} is missing; pass allow_missing=True for an empty ledger"
        )
    return read_assertions(p)


def ledger_status(
    assertions: list[dict[str, Any]],
    subject_ref: str,
    target_ref: str,
    *,
    now: str | None = None,
    current_subject: dict[str, Any] | None = None,
    current_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive ``current_ledger_status`` for a pair from the ledger. ``requeued`` is a
    READ-MODEL state derived (not a ledger status) via fingerprint drift / elapsed
    ``review_after``, gated through ``should_requeue``. ai_reviews never affect this."""
    matching = [
        a for a in assertions
        if a.get("subject_ref") == subject_ref and a.get("target_ref") == target_ref
    ]
    if not matching:
        return {"status": "none", "assertion_refs": [], "requeue_reason": None}
    refs = [a["id"] for a in matching]
    live = [a for a in matching if a.get("superseded_by") is None]
    a = live[-1] if live else matching[-1]
    if a.get("superseded_by") is not None:
        return {"status": "superseded", "assertion_refs": refs, "requeue_reason": None}
    status = a["status"]
    trigger: str | None = None
    if current_subject is not None and fingerprint(current_subject) != a.get("subject_fingerprint"):
        trigger = "fingerprint_drift"
    elif current_target is not None and fingerprint(current_target) != a.get("target_fingerprint"):
        trigger = "fingerprint_drift"
    elif a.get("review_after") and now is not None and a["review_after"] <= now:
        trigger = "review_after_elapsed"
    if trigger and should_requeue(status, trigger):
        return {"status": "requeued", "assertion_refs": refs, "requeue_reason": trigger}
    return {"status": status, "assertion_refs": refs, "requeue_reason": None}


# --- ai_reviews (advisory; from synthetic adjudicator verdicts) -------------

def ai_reviews_from_verdicts(
    verdict_rows: list[dict[str, Any]],
    *,
    model: str = "county-keying-adjudicator",
    prompt_version: str = "v1",
    created_at: str = "2026-06-26",
    cited_columns: tuple[str, ...] = ("vendor_name", "registry_name"),
) -> list[dict[str, Any]]:
    """Map verdict rows (vendor_id, proposed_key, verdict, confidence, reason) to
    advisory ai_reviews. ``confidence`` → ``signal_strength``; deterministic metadata.
    These NEVER set ``current_ledger_status``."""
    out: list[dict[str, Any]] = []
    for r in verdict_rows:
        seed = f"{r.get('vendor_id', '')}|{r.get('proposed_key', '')}"
        out.append({
            "model": model,
            "prompt_version": prompt_version,
            "input_hash": "ai-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12],
            "verdict": r["verdict"],
            "reason": r.get("reason", ""),
            "signal_strength": float(r.get("confidence", r.get("signal_strength", 0.0))),
            "created_at": created_at,
            "cited_fields": {c: r[c] for c in cited_columns if c in r},
        })
    return out


# --- envelope serialization (public fields only; leak-gated) ----------------

def _ref_row(ref: EntityRef) -> dict[str, Any]:
    return {
        "source_id": ref.source_id, "local_id": ref.local_id, "display_label": ref.display_label,
        "public_fields": ref.public_fields, "provenance": ref.provenance,
    }


def _join_row(j: CandidateJoin) -> dict[str, Any]:
    row: dict[str, Any] = {
        "candidate_id": j.candidate_id, "left_ref": _ref_row(j.left_ref),
        "right_ref": _ref_row(j.right_ref), "signals": j.signals, "signal_strength": j.signal_strength,
    }
    if j.subject_fingerprint is not None:
        row["subject_fingerprint"] = j.subject_fingerprint
    if j.target_fingerprint is not None:
        row["target_fingerprint"] = j.target_fingerprint
    return row


def build_case_row(case: ReconciliationCase) -> dict[str, Any]:
    """Validate + serialize one ReconciliationCase to its JSONL row (public fields only),
    then run the leak gate over the FINAL row. Raises on a reserved case_type (validator)
    or any forbidden leak."""
    validate_case(case)
    row: dict[str, Any] = {
        "schema_version": case.schema_version,
        "case_id": case.case_id,
        "case_type": case.case_type,
        "candidate_joins": [_join_row(j) for j in case.candidate_joins],
        "actionability": case.actionability,
        "current_ledger_status": case.current_ledger_status,
        "ledger_assertion_refs": case.ledger_assertion_refs,
        "ai_reviews": case.ai_reviews,
        "graph_context_refs": case.graph_context_refs,
    }
    if case.component is not None:
        row["component"] = case.component
    if case.merge_plan is not None:
        row["merge_plan"] = case.merge_plan
    violations = forbidden_violations(row)
    if violations:
        raise ValueError(f"read-model row failed the leak gate: {violations}")
    return row


def emit_jsonl(cases: list[ReconciliationCase]) -> list[str]:
    """Serialize cases to JSONL lines (each validated + leak-gated by build_case_row),
    then re-scan the joined raw text as a belt-and-suspenders final sweep."""
    rows = [build_case_row(c) for c in cases]
    lines = [json.dumps(r, sort_keys=True) for r in rows]
    final = forbidden_violations(json.loads("[" + ",".join(lines) + "]")) if lines else []
    if final:
        raise ValueError(f"emitted JSONL failed the final leak gate: {final}")
    return [ln + "\n" for ln in lines]
