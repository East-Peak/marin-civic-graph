"""Slice 4 — reconcile_decide: assemble a read-model case + a decision into
reconcile_writer.apply_decision, reading the RAW candidate so evidence is preserved.
No DB; scratch ledgers only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconcile_decide as rd  # noqa: E402
import reconciliation_read_model as rm  # noqa: E402
from test_reconciliation_cli import EIN_RAW, FPPC_RAW, SOS_RAW  # noqa: E402

EIN_CASE = "attach|org-bmf-ein-953667812|org-marincontract-recipient-x"
SOS_CASE = "attach|org-casos-0289793|org-marincontract-recipient-y"
FPPC_CASE = "attach|org-fppc-1470249|org-example-committee"


def _read_model(tmp_path, raws):
    rmf = tmp_path / "rm.jsonl"
    rows = [rm.build_case_row(c) for c in rm.build_attach_read_model(raws)]
    rmf.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return rmf


def _cand_file(tmp_path, name, raw):
    f = tmp_path / name
    f.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    return f


def test_approve_ein_preserves_evidence_and_materializes_handoff(tmp_path):
    ein = {**EIN_RAW, "evidence_record_ids": ["ev-1", "ev-2"]}
    rmf = _read_model(tmp_path, [ein])
    candf = _cand_file(tmp_path, "ein.jsonl", ein)
    led, att = tmp_path / "ledger.jsonl", tmp_path / "attach"
    out = rd.decide(EIN_CASE, "approve", reviewer="op", decided_at="2026-06-29T00:00:00Z",
                    read_model_path=rmf, candidate_paths={"ein": candf}, ledger_path=led, attach_dir=att)
    assert out["result"] == "created"
    assert out["assertion"]["evidence_refs"] == ["ev-1", "ev-2"]  # evidence preserved via raw candidate
    assert out["assertion"]["basis"] == "operator_approved_ein"
    node = json.loads((att / "nodes.jsonl").read_text().splitlines()[0])
    assert node["node_type"] == "Organization" and node["properties"]["registry_ein"] == "953667812"
    edge = json.loads((att / "edges.jsonl").read_text().splitlines()[0])
    assert edge["relationship_type"] == "SAME_AS" and edge["properties"]["assertion_id"] == out["assertion"]["id"]


def test_approve_ein_records_auto_policy_metadata(tmp_path):
    ein = {**EIN_RAW, "evidence_record_ids": ["ev-1"]}
    rmf = _read_model(tmp_path, [ein])
    candf = _cand_file(tmp_path, "ein.jsonl", ein)
    led, att = tmp_path / "ledger.jsonl", tmp_path / "attach"
    out = rd.decide(
        EIN_CASE, "approve",
        reviewer="research-fleet-v1/policy-stuart-2026-07-01",
        decided_at="2026-07-03T20:00:00Z",
        read_model_path=rmf,
        candidate_paths={"ein": candf},
        ledger_path=led,
        attach_dir=att,
        policy_version="research-fleet-v1/policy-stuart-2026-07-01",
        policy_hash="h-policy",
        eligibility_snapshot_hash="sha256:snapshot",
    )
    assert out["assertion"]["policy_version"] == "research-fleet-v1/policy-stuart-2026-07-01"
    assert out["assertion"]["policy_hash"] == "h-policy"
    assert out["assertion"]["eligibility_snapshot_hash"] == "sha256:snapshot"


def test_approve_sos_uses_real_casos_name(tmp_path):
    sos = {**SOS_RAW, "evidence_record_ids": ["ev-9"]}
    rmf = _read_model(tmp_path, [sos])
    candf = _cand_file(tmp_path, "sos.jsonl", sos)
    led, att = tmp_path / "ledger.jsonl", tmp_path / "attach"
    out = rd.decide(SOS_CASE, "approve", reviewer="op", decided_at="2026-06-29T00:00:00Z",
                    read_model_path=rmf, candidate_paths={"sos_id": candf}, ledger_path=led, attach_dir=att)
    assert out["result"] == "created"
    assert out["assertion"]["basis"] == "operator_approved_sos_id"
    node = json.loads((att / "nodes.jsonl").read_text().splitlines()[0])
    assert node["display_label"] == "Example LLC" and node["properties"]["sos_id"] == "0289793"


def test_reject_uses_reconciliation_ref_accessors(monkeypatch, tmp_path):
    rmf = _read_model(tmp_path, [EIN_RAW])
    monkeypatch.setattr(rd, "anchor_id_of", lambda case: "anchor-from-helper")
    monkeypatch.setattr(rd, "vendor_id_of", lambda case: "vendor-from-helper")
    captured = {}

    def fake_apply_decision(action, **kwargs):
        captured.update(kwargs)
        return {"result": "created", "assertion": None, "same_as": None}

    monkeypatch.setattr(rd, "apply_decision", fake_apply_decision)

    rd.decide(
        EIN_CASE,
        "reject",
        reviewer="op",
        decided_at="2026-06-29T00:00:00Z",
        rejection_kind="entity_distinct",
        read_model_path=rmf,
        candidate_paths={},
        ledger_path=tmp_path / "l.jsonl",
        attach_dir=tmp_path / "attach",
    )

    assert captured["subject"]["id"] == "anchor-from-helper"
    assert captured["target"]["id"] == "vendor-from-helper"


def test_reject_writes_rejection_no_handoff(tmp_path):
    rmf = _read_model(tmp_path, [EIN_RAW])
    led, att = tmp_path / "ledger.jsonl", tmp_path / "attach"
    out = rd.decide(EIN_CASE, "reject", reviewer="op", decided_at="2026-06-29T00:00:00Z",
                    rejection_kind="entity_distinct", read_model_path=rmf, candidate_paths={}, ledger_path=led, attach_dir=att)
    assert out["result"] == "created"
    assert out["assertion"]["basis"] == "operator_rejected_ein_entity_distinct"
    assert not (att / "nodes.jsonl").exists() and not (att / "edges.jsonl").exists()


def test_unsure_writes_nothing(tmp_path):
    rmf = _read_model(tmp_path, [EIN_RAW])
    led, att = tmp_path / "ledger.jsonl", tmp_path / "attach"
    out = rd.decide(EIN_CASE, "unsure", reviewer="op", decided_at="2026-06-29T00:00:00Z",
                    read_model_path=rmf, candidate_paths={}, ledger_path=led, attach_dir=att)
    assert out["result"] == "unsure"
    assert not led.exists()


def test_unknown_case_id_fails_loud(tmp_path):
    rmf = _read_model(tmp_path, [EIN_RAW])
    with pytest.raises(ValueError, match="case_id"):
        rd.decide("attach|nope|nope", "unsure", reviewer="op", decided_at="2026-06-29T00:00:00Z",
                  read_model_path=rmf, candidate_paths={}, ledger_path=tmp_path / "l.jsonl", attach_dir=tmp_path / "a")


def test_committee_decide_error_names_r3_scope(tmp_path):
    rmf = _read_model(tmp_path, [FPPC_RAW])
    with pytest.raises(ValueError, match=r"committee_id.*R3|R3.*committee_id"):
        rd.decide(
            FPPC_CASE,
            "approve",
            reviewer="op",
            decided_at="2026-07-06T00:00:00Z",
            read_model_path=rmf,
            candidate_paths={},
            ledger_path=tmp_path / "l.jsonl",
            attach_dir=tmp_path / "a",
        )
