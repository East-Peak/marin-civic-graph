"""Goal 1 — reconciliation read-model emitter. Grows unit by unit:
Unit 3 (redaction primitives: public_hash + the leak gate) and Unit 6 (the full
versioned ReconciliationCase-envelope emitter).
"""
from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import fields

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
    assert w["assertion"]["basis"] == "operator_rejected_ein_entity_distinct"  # kind-encoded (Refinement A)
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
    assert w["assertion"]["basis"] == "org_dedup_operator_rejected_current_evidence"  # kind-encoded (Refinement A)


def test_reserved_case_type_permits_no_write():
    with pytest.raises(ValueError, match="reserved"):
        rm.operator_action_to_ledger(_act("relationship_candidate", "approve"))


def test_rejection_basis_carries_no_key_and_changed_kind_is_distinct():
    # Refinement A: rejection bases never surface a key (not in _KEY_BEARING_BASES)...
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parents[2] / "scripts"))
    from export_existing_orgs import _KEY_BEARING_BASES  # noqa: E402
    assert "operator_rejected_ein_entity_distinct" not in _KEY_BEARING_BASES
    assert "org_dedup_operator_rejected_current_evidence" not in _KEY_BEARING_BASES
    # ...and a CHANGED rejection-kind yields a DISTINCT assertion id (so supersede can mint a clean id)
    subj, tgt = {"id": "org-bmf-ein-1", "display_label": "x"}, {"id": "org-v", "display_label": "V"}
    a1 = rm.operator_action_to_ledger(
        _act("identity_key_attach", "reject", key_type="ein", rejection_kind="current_evidence"),
        subject=subj, target=tgt)
    a2 = rm.operator_action_to_ledger(
        _act("identity_key_attach", "reject", key_type="ein", rejection_kind="entity_distinct"),
        subject=subj, target=tgt)
    assert a1["assertion"]["id"] != a2["assertion"]["id"]
    assert a1["assertion"]["basis"] == "operator_rejected_ein_current_evidence"


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


# --- Unit 6: ledger status + ai_reviews + envelope serialization ----------

import json as _json  # noqa: E402
from identity_ledger import make_assertion, write_assertions  # noqa: E402


def _assertion(subject_ref, target_ref, status, basis="b", **kw):
    return make_assertion(
        subject_ref=subject_ref, target_ref=target_ref, status=status, basis=basis,
        subject={"id": subject_ref, "display_label": "S"},
        target={"id": target_ref, "display_label": "T"},
        reviewer="stuart@eastpeak.cc", decided_at="2026-06-27", policy_version="v1", **kw,
    )


def _ref(local_id):
    return rc.EntityRef(source_id="ein", local_id=local_id, display_label=local_id,
                        public_fields={"display_label": local_id}, provenance={"adapter": "ein"})


def _join(jid="j1"):
    return rc.CandidateJoin(candidate_id=jid, left_ref=_ref("a"), right_ref=_ref("b"),
                            signals=["normalized_name_exact"], signal_strength=0.9)


def _attach_case(**kw):
    base = dict(schema_version=rc.SCHEMA_VERSION, case_id="c1", case_type="identity_key_attach",
                candidate_joins=[_join()], actionability="actionable")
    base.update(kw)
    return rc.ReconciliationCase(**base)


def test_load_ledger_missing_fails_loud(tmp_path):
    with pytest.raises(FileNotFoundError):
        rm.load_ledger(tmp_path / "nope.jsonl")
    assert rm.load_ledger(tmp_path / "nope.jsonl", allow_missing=True) == []


def test_load_ledger_reads(tmp_path):
    p = tmp_path / "l.jsonl"
    write_assertions([_assertion("s", "t", "approved")], p)
    assert len(rm.load_ledger(p)) == 1


def test_ledger_status_none_approved_rejected():
    assert rm.ledger_status([], "s", "t")["status"] == "none"
    a = _assertion("s", "t", "approved")
    out = rm.ledger_status([a], "s", "t")
    assert out["status"] == "approved" and out["assertion_refs"] == [a["id"]]
    r = _assertion("s", "t", "rejected_entity_distinct")
    assert rm.ledger_status([r], "s", "t")["status"] == "rejected_entity_distinct"


def test_ledger_status_superseded():
    a = _assertion("s", "t", "approved")
    a["superseded_by"] = "other-id"
    assert rm.ledger_status([a], "s", "t")["status"] == "superseded"


def test_ledger_status_requeue_review_after_elapsed():
    a = _assertion("s", "t", "approved", review_after="2026-01-01")
    out = rm.ledger_status([a], "s", "t", now="2026-06-27")
    assert out["status"] == "requeued" and out["requeue_reason"] == "review_after_elapsed"


def test_ledger_status_requeue_fingerprint_drift():
    a = _assertion("s", "t", "approved")
    out = rm.ledger_status([a], "s", "t", now="2026-06-27",
                           current_subject={"id": "s", "display_label": "CHANGED"})
    assert out["status"] == "requeued" and out["requeue_reason"] == "fingerprint_drift"


def test_ai_reviews_maps_confidence_advisory():
    revs = rm.ai_reviews_from_verdicts(
        [{"vendor_id": "v", "proposed_key": "k", "verdict": "same", "confidence": 0.9,
          "reason": "exact", "vendor_name": "V"}]
    )
    assert revs[0]["signal_strength"] == 0.9
    assert revs[0]["verdict"] == "same"
    assert revs[0]["input_hash"].startswith("ai-")
    assert "confidence" not in _json.dumps(revs)  # mapped away


def test_build_case_row_serializes_and_leak_gates():
    a = _assertion("org-bmf-ein-1", "org-vendor", "approved")
    case = _attach_case(current_ledger_status="approved", ledger_assertion_refs=[a["id"]],
                        ai_reviews=rm.ai_reviews_from_verdicts([{"vendor_id": "org-vendor",
                        "proposed_key": "1", "verdict": "same", "confidence": 0.9, "reason": "ok"}]))
    row = rm.build_case_row(case)
    assert row["case_type"] == "identity_key_attach"
    assert len(row["candidate_joins"]) == 1
    assert row["current_ledger_status"] == "approved"
    assert "confidence" not in _json.dumps(row)


def test_candidate_join_private_fingerprints_are_not_dataclass_fields():
    names = {f.name for f in fields(rc.CandidateJoin)}
    assert "subject_fingerprint" not in names
    assert "target_fingerprint" not in names


def test_candidate_join_private_fingerprints_do_not_leak_if_attached():
    join = _join()
    join.subject_fingerprint = "private-subject-hash"
    join.target_fingerprint = "private-target-hash"
    row = rm.build_case_row(_attach_case(candidate_joins=[join]))
    emitted_join = row["candidate_joins"][0]
    assert "subject_fingerprint" not in emitted_join
    assert "target_fingerprint" not in emitted_join
    assert "private-subject-hash" not in _json.dumps(row)
    assert "private-target-hash" not in _json.dumps(row)


def test_build_case_row_rejects_reserved():
    case = _attach_case(case_type="relationship_candidate")
    with pytest.raises(ValueError, match="reserved"):
        rm.build_case_row(case)


def test_emit_jsonl_clean():
    lines = rm.emit_jsonl([_attach_case()])
    assert len(lines) == 1 and lines[0].endswith("\n")
