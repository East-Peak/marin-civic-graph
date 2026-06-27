"""Goal 1 — reconciliation read-model emitter. Grows unit by unit:
Unit 3 (redaction primitives: public_hash + the leak gate) and Unit 6 (the full
versioned ReconciliationCase-envelope emitter).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pytest  # noqa: E402

import reconciliation_cases as rc  # noqa: E402
import reconciliation_read_model as rm  # noqa: E402
from enrich_casos_keys import scan_for_forbidden  # noqa: E402
from enrich_county_vendor_eins import build_ein_attach  # noqa: E402
from identity_ledger import fingerprint  # noqa: E402


def _act(case_type, action, **kw):
    return rc.OperatorAction(
        case_id="c1", case_type=case_type, action=action,
        reviewer="stuart@eastpeak.cc", decided_at="2026-06-27", **kw,
    )


# --- Unit 3: redaction boundary primitives --------------------------------

def test_public_hash_deterministic_and_order_independent():
    pf = {"sos_id": "0289793", "display_label": "Example LLC"}
    assert rm.public_hash(pf) == rm.public_hash({"display_label": "Example LLC", "sos_id": "0289793"})
    assert rm.public_hash({"a": 1}) != rm.public_hash({"a": 2})
    assert rm.public_hash(pf).startswith("pub-")  # distinguishable from ledger hashes


def test_public_hash_never_equals_private_ledger_fingerprint():
    # the read model may emit ONLY public_hash(public_fields); a ledger assertion's
    # fingerprint hashes the FULL (possibly-PII) ref and must never appear in output.
    public = {"sos_id": "0289793", "display_label": "Example LLC"}
    addr = "142 " + "Imaginary" + " Rd"  # runtime-built; no committed address literal
    private_ref = {**public, "principal_address": addr, "agent_name": "A. Person"}
    assert rm.public_hash(public) != fingerprint(private_ref)
    assert rm.public_hash(public) != fingerprint(public)  # even same input: prefixed/distinct format


def test_leak_gate_clean_on_public_rows():
    row = {"sos_id": "0289793", "display_label": "Example LLC", "entity_type": "LLC"}
    assert rm.forbidden_violations(row) == []
    assert scan_for_forbidden(row) == []


def test_leak_gate_catches_runtime_sentinel_and_forbidden_key():
    sentinel = "142 " + "Imaginary" + " Rd"  # built at runtime — never committed as a literal
    leaked_value = {"display_label": "ok", "note": f"address {sentinel}"}
    assert scan_for_forbidden(leaked_value, sentinels=(sentinel,))  # value sentinel caught
    assert scan_for_forbidden({"home_address": "x"}, forbidden_keys=("address",))  # key name caught


# --- Unit 4: OperatorAction → ledger write (§5.2.1 matrix + namespacing) ----

def test_attach_approve_uses_builder_into_attach_ledger():
    cand = {"subject_ref": "org-bmf-ein-953667812", "candidate_ref": "org-vendor-x", "ein": "953667812"}
    vref = {"id": "org-vendor-x", "display_label": "Vendor X"}
    w = rm.operator_action_to_ledger(
        _act("identity_key_attach", "approve", key_type="ein"),
        attach_builder=build_ein_attach, candidate=cand, vendor_ref=vref,
    )
    assert w["ledger"] == rm.ATTACH_LEDGER
    assert w["assertion"]["status"] == "approved"
    assert w["assertion"]["basis"] == "operator_approved_ein"
    assert not w["assertion"]["basis"].startswith("org_dedup")  # never enters a dedup component
    assert w["same_as"] is not None


def test_attach_reject_status_and_no_same_as():
    subj = {"id": "org-bmf-ein-1", "display_label": "x"}
    tgt = {"id": "org-vendor-x", "display_label": "Vendor X"}
    w = rm.operator_action_to_ledger(
        _act("identity_key_attach", "reject", key_type="ein", rejection_kind="entity_distinct"),
        subject=subj, target=tgt,
    )
    assert w["ledger"] == rm.ATTACH_LEDGER
    assert w["assertion"]["status"] == "rejected_entity_distinct"
    assert w["assertion"]["basis"] == "operator_rejected_ein"
    assert not w["assertion"]["basis"].startswith("org_dedup")
    assert w["same_as"] is None


def test_unsure_writes_nothing():
    assert rm.operator_action_to_ledger(_act("identity_key_attach", "unsure")) is None
    assert rm.operator_action_to_ledger(_act("entity_dedup_merge", "unsure")) is None


def test_dedup_approve_org_dedup_namespace():
    subj = {"id": "org-a", "display_label": "A"}
    tgt = {"id": "org-b", "display_label": "B"}
    w = rm.operator_action_to_ledger(_act("entity_dedup_merge", "approve"), subject=subj, target=tgt)
    assert w["ledger"] == rm.DEDUP_LEDGER
    assert w["assertion"]["status"] == "approved"
    assert w["assertion"]["basis"] == "org_dedup_operator_approved"
    assert w["assertion"]["basis"].startswith("org_dedup")  # the merge-component namespace


def test_dedup_reject():
    subj = {"id": "org-a", "display_label": "A"}
    tgt = {"id": "org-b", "display_label": "B"}
    w = rm.operator_action_to_ledger(
        _act("entity_dedup_merge", "reject", rejection_kind="current_evidence"), subject=subj, target=tgt,
    )
    assert w["assertion"]["status"] == "rejected_current_evidence"
    assert w["assertion"]["basis"] == "org_dedup_operator_rejected"


def test_reserved_case_type_permits_no_write():
    with pytest.raises(ValueError, match="reserved"):
        rm.operator_action_to_ledger(_act("relationship_candidate", "approve"))


# --- Unit 5: MergePlan (dry-run over a scratch graph) ----------------------

def test_merge_plan_counts_collision_and_selfloop():
    graph = {
        "nodes": {"org-a": {"properties": {}}, "org-b": {"properties": {}}, "org-x": {"properties": {}}},
        "edges": {
            ("org-b", "TO_TARGET", "org-x"): {"amount": 1},   # repoints → collides with org-a's edge
            ("org-a", "TO_TARGET", "org-x"): {"amount": 2},   # pre-existing → collapse
            ("org-b", "REL", "org-a"): {},                    # org-b→org-a → self-loop on merge → drop
        },
    }
    comp = {"members": ["org-a", "org-b"], "canonical": "org-a"}
    plan = rm.build_merge_plan(comp, graph)
    assert plan["canonical_id"] == "org-a"
    assert plan["superseded_ids"] == ["org-b"]
    assert plan["collision_count"] == 1
    assert plan["selfloop_drops"] == 1
    assert plan["edge_ops_count"] == 2
    assert plan["node_policy"] == "tombstone_no_field_merge"
    assert plan["edge_policy"] == "apoc_merge_relationship_collapse"


def test_merge_plan_is_a_dry_run_does_not_mutate_input():
    graph = {
        "nodes": {"org-a": {"properties": {}}, "org-b": {"properties": {}}, "org-x": {"properties": {}}},
        "edges": {("org-b", "TO_TARGET", "org-x"): {"amount": 1}},
    }
    rm.build_merge_plan({"members": ["org-a", "org-b"], "canonical": "org-a"}, graph)
    assert ("org-b", "TO_TARGET", "org-x") in graph["edges"]  # original edge untouched
    assert "dedup_superseded_by" not in graph["nodes"]["org-b"]["properties"]
