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
import identity_confidence as ic  # noqa: E402
from identity_ledger import make_assertion  # noqa: E402
from test_reconciliation_cli import EIN_RAW  # reuse the EIN candidate fixture  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SUBJECT, TARGET = "org-bmf-ein-953667812", "org-marincontract-recipient-x"
COMPUTED_AT = "2026-07-07T12:00:00Z"


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


def _write_confidence(tmp_path, read_model_path):
    cases = [json.loads(ln) for ln in read_model_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    records = ic.build_confidence(
        [
            {
                "schema_version": "verdict-feed-v1",
                "vendor_id": TARGET,
                "proposed_key": "953667812",
                "verdict": "same",
                "confidence": 0.86,
                "dimensions": ["service_domain", "county_payment_context"],
                "evidence": [
                    {
                        "source": "county_open_data",
                        "supports": "same",
                        "url_or_record_id": "record-county-contract-x",
                    }
                ],
                "provenance": {"model": "unit", "run": "confidence-overlay"},
                "reason": "same organization based on public records",
            }
        ],
        cases,
        [],
        {},
        computed_at=COMPUTED_AT,
    )
    conf = tmp_path / "confidence.jsonl"
    ic.write_confidence(records, conf)
    return conf


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


def test_overlay_attaches_active_confidence_band_when_file_supplied(tmp_path):
    rmf = _write_read_model(tmp_path)
    conf = _write_confidence(tmp_path, rmf)

    cases = rc.overlay_cases(rmf, [], confidence_path=conf)

    assert cases[0]["confidence"] == {"band": "high", "status": "active"}


def test_overlay_masks_confidence_against_live_publishing_ledger(tmp_path):
    rmf = _write_read_model(tmp_path)
    conf = _write_confidence(tmp_path, rmf)
    led = _write_ledger(tmp_path)

    cases = rc.overlay_cases(rmf, [led], confidence_path=conf)

    assert cases[0]["confidence"] == {"band": "high", "status": "superseded_by_assertion"}


def test_overlay_without_confidence_file_leaves_case_shape_unchanged(tmp_path):
    rmf = _write_read_model(tmp_path)

    cases = rc.overlay_cases(rmf, [])

    assert "confidence" not in cases[0]


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


def test_cli_confidence_arg_attaches_masked_band(tmp_path, capsys):
    import reconciliation_overlay as rc

    rmf = _write_read_model(tmp_path)
    conf = _write_confidence(tmp_path, rmf)
    led = _write_ledger(tmp_path)

    code = rc.main(["--read-model", str(rmf), "--ledger", str(led), "--confidence", str(conf)])

    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["confidence"] == {"band": "high", "status": "superseded_by_assertion"}
