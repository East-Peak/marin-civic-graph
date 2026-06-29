"""Goal A Unit 3 — reconcile_writer.apply_decision: attach-only, file-locked, atomic,
idempotent, superseding. No live DB."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconcile_writer as rw  # noqa: E402
from identity_ledger import make_assertion  # noqa: E402
from reconciliation_cases import OperatorAction  # noqa: E402

VENDOR = {"id": "org-marincontract-recipient-x", "display_label": "X"}
CAND = {"anchor_id": "org-bmf-ein-953667812", "label": "EX YOUTH", "ein": "953667812"}


def _fake_attach_builder(candidate, vendor_ref, *, reviewer, decided_at, policy_version):
    """Mirrors build_*_attach: returns (approve assertion, SAME_AS edge referencing its id)."""
    a = make_assertion(
        subject_ref=candidate["anchor_id"], target_ref=vendor_ref["id"],
        status="approved", basis="operator_approved_ein",
        subject={"id": candidate["anchor_id"], "display_label": candidate["label"],
                 "ein": candidate["ein"], "source": "bmf"},
        target=vendor_ref, reviewer=reviewer, decided_at=decided_at, policy_version=policy_version,
    )
    same_as = {"source_id": candidate["anchor_id"], "target_id": vendor_ref["id"],
               "relationship_type": "SAME_AS",
               "properties": {"basis": "operator_approved_ein", "assertion_id": a["id"]}}
    return a, same_as


def _approve(decided_at="2026-06-28T00:00:00Z"):
    return OperatorAction(case_id="c1", case_type="identity_key_attach", action="approve",
                          reviewer="op", decided_at=decided_at, key_type="ein")


def _reject(kind="entity_distinct", decided_at="2026-06-28T01:00:00Z"):
    return OperatorAction(case_id="c1", case_type="identity_key_attach", action="reject",
                          reviewer="op", decided_at=decided_at, key_type="ein", rejection_kind=kind)


def _approve_call(ledger, action=None):
    return rw.apply_decision(action or _approve(), candidate=CAND, vendor_ref=VENDOR,
                             attach_builder=_fake_attach_builder, ledger_path=ledger)


def _reject_call(ledger, action=None):
    return rw.apply_decision(action or _reject(), subject={"id": CAND["anchor_id"]},
                             target={"id": VENDOR["id"]}, ledger_path=ledger)


def _rows(ledger):
    return [json.loads(ln) for ln in Path(ledger).read_text().splitlines() if ln.strip()]


def test_attach_only_refuses_dedup(tmp_path):
    bad = OperatorAction(case_id="c", case_type="entity_dedup_merge", action="approve",
                         reviewer="op", decided_at="2026-06-28T00:00:00Z")
    with pytest.raises(ValueError, match="ATTACH-ONLY"):
        rw.apply_decision(bad, subject={"id": "a"}, target={"id": "b"},
                          ledger_path=tmp_path / "l.jsonl")


def test_unsure_writes_nothing(tmp_path):
    led = tmp_path / "l.jsonl"
    out = rw.apply_decision(OperatorAction(case_id="c1", case_type="identity_key_attach",
                            action="unsure", reviewer="op", decided_at="2026-06-28T00:00:00Z"),
                            ledger_path=led)
    assert out["result"] == "unsure"
    assert not led.exists()


def test_created(tmp_path):
    led = tmp_path / "l.jsonl"
    out = _approve_call(led)
    assert out["result"] == "created"
    assert out["same_as"]["properties"]["assertion_id"] == out["assertion"]["id"]
    assert len(_rows(led)) == 1


def test_idempotent_existing_ignores_decided_at(tmp_path):
    led = tmp_path / "l.jsonl"
    first = _approve_call(led)
    again = _approve_call(led, _approve(decided_at="2026-06-28T09:99:99Z".replace("99", "30")))
    assert again["result"] == "existing"
    assert again["assertion"]["id"] == first["assertion"]["id"]
    assert again["assertion"]["decided_at"] == first["assertion"]["decided_at"]  # original kept
    assert len(_rows(led)) == 1


def test_superseded_changed_decision_one_live_with_id_consistency(tmp_path):
    led = tmp_path / "l.jsonl"
    _reject_call(led)                       # created (reject)
    out = _approve_call(led)                # changed decision → supersede the reject
    assert out["result"] == "superseded"
    # id-consistency: persisted id == the SAME_AS assertion_id
    assert out["assertion"]["id"] == out["same_as"]["properties"]["assertion_id"]
    rows = _rows(led)
    live = [a for a in rows if a.get("superseded_by") is None]
    assert len(live) == 1 and live[0]["id"] == out["assertion"]["id"]
    superseded = [a for a in rows if a.get("superseded_by") is not None]
    assert len(superseded) == 1 and superseded[0]["superseded_by"] == out["assertion"]["id"]
    assert out["assertion"]["supersedes"] == superseded[0]["id"]


def test_atomic_backup_written_on_second_write(tmp_path):
    led = tmp_path / "l.jsonl"
    _reject_call(led)
    _approve_call(led)
    assert led.with_suffix(led.suffix + ".bak").exists()  # prior content backed up


# --- Unit 4: SAME_AS node+edge handoff ------------------------------------

import load_neo4j_v2  # noqa: E402

ANCHOR_NODE = {"id": "org-bmf-ein-953667812", "node_type": "Organization",
               "labels": ["Organization"], "display_label": "EX YOUTH",
               "properties": {"source": "bmf", "registry_ein": "953667812"}}


def _approve_handoff(ledger, attach_dir, anchor=None, action=None):
    return rw.apply_decision(action or _approve(), candidate=CAND, vendor_ref=VENDOR,
                             attach_builder=_fake_attach_builder, ledger_path=ledger,
                             attach_dir=attach_dir, anchor_node=anchor if anchor is not None else ANCHOR_NODE)


def _jsonl(path):
    return [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]


class _FakeSession:
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **kw):
        self.calls.append((query, kw))


class _FakeDriver:
    def __init__(self):
        self.calls = []

    def session(self, database=None):
        return _FakeSession(self.calls)


def test_approve_materializes_node_and_edge(tmp_path):
    led, att = tmp_path / "l.jsonl", tmp_path / "attach"
    _approve_handoff(led, att)
    nodes, edges = _jsonl(att / "nodes.jsonl"), _jsonl(att / "edges.jsonl")
    assert nodes == [ANCHOR_NODE]
    assert len(edges) == 1
    e = edges[0]
    assert (e["source_id"], e["target_id"], e["relationship_type"]) == \
        ("org-bmf-ein-953667812", "org-marincontract-recipient-x", "SAME_AS")
    assert e["properties"]["assertion_id"]


def test_reject_writes_no_handoff(tmp_path):
    led, att = tmp_path / "l.jsonl", tmp_path / "attach"
    rw.apply_decision(_reject(), subject={"id": CAND["anchor_id"]}, target={"id": VENDOR["id"]},
                      ledger_path=led, attach_dir=att, anchor_node=ANCHOR_NODE)
    assert not (att / "nodes.jsonl").exists() and not (att / "edges.jsonl").exists()


def test_approve_requires_anchor_node(tmp_path):
    led, att = tmp_path / "l.jsonl", tmp_path / "attach"
    with pytest.raises(ValueError, match="anchor_node"):
        rw.apply_decision(_approve(), candidate=CAND, vendor_ref=VENDOR,
                          attach_builder=_fake_attach_builder, ledger_path=led,
                          attach_dir=att, anchor_node=None)


def test_handoff_artifacts_load_via_loader(tmp_path):
    led, att = tmp_path / "l.jsonl", tmp_path / "attach"
    _approve_handoff(led, att)
    drv = _FakeDriver()
    ncounts = load_neo4j_v2.load_nodes(drv, _jsonl(att / "nodes.jsonl"), database="x")
    ecounts = load_neo4j_v2.load_edges(drv, _jsonl(att / "edges.jsonl"), database="x")
    assert ncounts["Organization"] == 1
    assert sum(ecounts.values()) == 1


def test_handoff_edge_last_write_wins_no_dup(tmp_path):
    led, att = tmp_path / "l.jsonl", tmp_path / "attach"
    att.mkdir()
    # seed a stale edge for the same (source, rel, target) with an OLD assertion_id
    (att / "edges.jsonl").write_text(json.dumps({
        "source_id": "org-bmf-ein-953667812", "target_id": "org-marincontract-recipient-x",
        "relationship_type": "SAME_AS", "properties": {"basis": "x", "assertion_id": "OLD"}}) + "\n")
    out = _approve_handoff(led, att)
    edges = _jsonl(att / "edges.jsonl")
    assert len(edges) == 1  # upserted, not duplicated
    assert edges[0]["properties"]["assertion_id"] == out["same_as"]["properties"]["assertion_id"] != "OLD"


def test_approve_reject_approve_reactivates_not_existing(tmp_path):
    """Codex Slice-4 HIGH: re-approving after a reject must REACTIVATE (one live = the
    re-approve), not return 'existing' and leave the reject live."""
    led, att = tmp_path / "l.jsonl", tmp_path / "attach"
    first = _approve_handoff(led, att)              # created (approve A)
    _reject_call(led)                               # reject B supersedes A
    again = _approve_handoff(led, att)              # approve A again → must reactivate
    assert again["result"] == "superseded"
    rows = _rows(led)
    live = [a for a in rows if a.get("superseded_by") is None]
    assert len(live) == 1
    assert live[0]["status"] == "approved" and live[0]["id"] == first["assertion"]["id"]
    # the handoff edge points at the now-live approve assertion
    edge = json.loads((att / "edges.jsonl").read_text().splitlines()[0])
    assert edge["properties"]["assertion_id"] == live[0]["id"]
