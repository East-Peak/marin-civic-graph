"""Goal A Unit 5 — reconciliation_overlay.overlay_cases: overlay live ledger status on the
static read model, recompute actionability, never mutate the source. No DB.

The deprecated reconcile_cases.py path stays executable until the operator routes finish
their R3 migration window.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconciliation_overlay as rc  # noqa: E402
import reconciliation_read_model as rm  # noqa: E402
from identity_ledger import make_assertion  # noqa: E402
from test_reconciliation_cli import EIN_RAW  # reuse the EIN candidate fixture  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SUBJECT, TARGET = "org-bmf-ein-953667812", "org-marincontract-recipient-x"


def _write_read_model(tmp_path):
    rmf = tmp_path / "read-model.jsonl"
    rows = [rm.build_case_row(c) for c in rm.build_attach_read_model([EIN_RAW])]
    rmf.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return rmf


def _write_ledger(tmp_path, status="approved", basis="operator_approved_ein"):
    a = make_assertion(
        subject_ref=SUBJECT, target_ref=TARGET, status=status, basis=basis,
        subject={"id": SUBJECT}, target={"id": TARGET},
        reviewer="op", decided_at="2026-06-28T00:00:00Z", policy_version=rm.POLICY_VERSION,
    )
    led = tmp_path / "assertions.jsonl"
    led.write_text(json.dumps(a) + "\n", encoding="utf-8")
    return led


def test_overlay_status_none_without_ledger(tmp_path):
    rmf = _write_read_model(tmp_path)
    cases = rc.overlay_cases(rmf, [])
    assert cases[0]["current_ledger_status"] == "none"
    assert cases[0]["actionability"] == "actionable"
    assert "review_flags" in cases[0] and "bulk_eligible" in cases[0]


def test_pair_delegates_to_reconciliation_refs(monkeypatch):
    monkeypatch.setattr(rc, "anchor_id_of", lambda case: "anchor-from-helper")
    monkeypatch.setattr(rc, "vendor_id_of", lambda case: "vendor-from-helper")

    assert rc._pair({"case_id": "c", "candidate_joins": [{"left_ref": {}, "right_ref": {}}]}) == (
        "anchor-from-helper",
        "vendor-from-helper",
    )


def test_overlay_reflects_ledger_approval_and_recomputes_actionability(tmp_path):
    rmf = _write_read_model(tmp_path)
    led = _write_ledger(tmp_path)
    cases = rc.overlay_cases(rmf, [led])
    assert cases[0]["current_ledger_status"] == "approved"
    assert cases[0]["actionability"] == "resolved"  # recomputed from the overlaid status
    assert cases[0]["ledger_assertion_refs"]  # the approval's id surfaced


def test_overlay_never_mutates_the_source_file(tmp_path):
    rmf = _write_read_model(tmp_path)
    led = _write_ledger(tmp_path)
    before = rmf.read_bytes()
    rc.overlay_cases(rmf, [led])
    assert rmf.read_bytes() == before  # static read model untouched


def test_cli_emits_overlaid_cases_json(tmp_path, capsys):
    import reconciliation_overlay as rc
    rmf = _write_read_model(tmp_path)
    led = _write_ledger(tmp_path)
    code = rc.main(["--read-model", str(rmf), "--ledger", str(led)])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, list) and out[0]["current_ledger_status"] == "approved"


def test_deprecated_reconcile_cases_script_path_matches_reconciliation_overlay_cli(tmp_path):
    rmf = _write_read_model(tmp_path)
    led = _write_ledger(tmp_path)
    args = ["--read-model", str(rmf), "--ledger", str(led)]

    new_out = subprocess.check_output([sys.executable, str(SCRIPTS / "reconciliation_overlay.py"), *args], text=True)
    old_out = subprocess.check_output([sys.executable, str(SCRIPTS / "reconcile_cases.py"), *args], text=True)

    assert old_out == new_out
    parsed = json.loads(old_out)
    assert parsed[0]["current_ledger_status"] == "approved"
