"""C4 hard invariants for the identity-confidence sidecar.

Confidence is a derived operator-local projection. It must never become a
ledger-shaped object at public egress or a public-build artifact.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import identity_confidence as ic  # noqa: E402
from identity_egress_gate import join_citation  # noqa: E402
from identity_ledger import PUBLISHING_STATUSES, make_assertion  # noqa: E402


COMPUTED_AT = "2026-07-07T12:00:00Z"


def _case() -> dict:
    vendor = "org-marincontract-recipient-alpha"
    anchor = "org-casos-0123456"
    return {
        "schema_version": "recon-read-model-v2",
        "case_id": f"attach|{anchor}|{vendor}",
        "case_type": "identity_key_attach",
        "candidate_joins": [
            {
                "candidate_id": f"{anchor}|{vendor}",
                "left_ref": {
                    "source_id": "sos_id",
                    "local_id": vendor,
                    "display_label": "County Vendor Alpha",
                    "public_fields": {"display_label": "County Vendor Alpha"},
                    "provenance": {"adapter": "sos_id", "vendor_ref": vendor},
                },
                "right_ref": {
                    "source_id": "sos_id",
                    "local_id": anchor,
                    "display_label": "Alpha Services LLC",
                    "public_fields": {"display_label": "Alpha Services LLC", "sos_id": "0123456"},
                    "provenance": {"adapter": "sos_id", "anchor_ref": anchor},
                },
                "signals": ["normalized_name_exact"],
                "signal_strength": 0.9,
            }
        ],
        "current_ledger_status": "none",
        "ledger_assertion_refs": [],
        "review_flags": {"needs_careful_review": False},
    }


def _feed() -> dict:
    return {
        "schema_version": "verdict-feed-v1",
        "vendor_id": "org-marincontract-recipient-alpha",
        "proposed_key": "0123456",
        "verdict": "same",
        "confidence": 0.91,
        "dimensions": ["service_domain", "county_payment_context"],
        "evidence": [
            {
                "source": "county_open_data",
                "supports": "same",
                "url_or_record_id": "record-county-contract-alpha",
            }
        ],
        "provenance": {"model": "unit", "run": "c4"},
        "reason": "same organization based on public records",
        "gid": 1,
    }


def _approved_assertion() -> dict:
    return make_assertion(
        subject_ref="org-casos-0123456",
        target_ref="org-marincontract-recipient-alpha",
        status="approved",
        basis="operator_approved_sos_id",
        subject={"id": "org-casos-0123456", "display_label": "Alpha Services LLC", "sos_id": "0123456"},
        target={"id": "org-marincontract-recipient-alpha", "display_label": "County Vendor Alpha"},
        reviewer="stuart@eastpeak.cc",
        decided_at=COMPUTED_AT,
        policy_version="v1",
    )


def test_join_citation_refuses_f5_confidence_row_even_with_forged_approved_status():
    with pytest.raises(ValueError, match="assertion-"):
        join_citation({"id": "conf-deadbeef", "status": "approved"})


def test_join_citation_real_assertion_behavior_is_byte_identical():
    approved = _approved_assertion()
    deterministic = {**approved, "status": "deterministic"}
    queued = {**approved, "status": "queued"}

    assert join_citation(approved) == approved["id"]
    assert join_citation(deterministic) == deterministic["id"]
    assert join_citation(queued) is None
    assert approved["id"].startswith("assertion-")


def test_no_confidence_record_can_enter_egress_with_any_status():
    for status in ("active", "superseded_by_assertion", "approved", "deterministic", "queued"):
        with pytest.raises(ValueError, match="assertion-"):
            join_citation({"id": "conf-feedface", "status": status})


def test_publishing_statuses_source_bytes_stay_pinned():
    source = (SCRIPTS / "identity_ledger.py").read_text(encoding="utf-8")
    assert 'PUBLISHING_STATUSES: frozenset[str] = frozenset({"deterministic", "approved"})' in source
    assert PUBLISHING_STATUSES == frozenset({"deterministic", "approved"})


def test_public_egress_consumers_do_not_import_or_read_confidence_projection():
    public_egress_paths = [
        SCRIPTS / "identity_egress_gate.py",
        SCRIPTS / "export_existing_orgs.py",
        SCRIPTS / "build_dual_role_candidates.py",
        SCRIPTS / "ingest_marin_county_contracts.py",
        SCRIPTS / "economic_interest_builders.py",
    ]
    for path in public_egress_paths:
        text = path.read_text(encoding="utf-8")
        assert "data/identity/confidence.jsonl" not in text
        assert "confidence.jsonl" not in text
        assert "identity_confidence" not in text

    export_source = (SCRIPTS / "export_existing_orgs.py").read_text(encoding="utf-8")
    assert "data/identity/assertions.jsonl" in export_source


def test_attach_handoff_writers_and_live_handoff_edges_never_cite_confidence_ids():
    writer_paths = [
        SCRIPTS / "identity_attach.py",
        SCRIPTS / "reconcile_writer.py",
        SCRIPTS / "reconcile_decide.py",
        SCRIPTS / "enrich_county_vendor_eins.py",
        SCRIPTS / "enrich_county_vendor_sos.py",
        SCRIPTS / "enrich_fppc_keys.py",
        SCRIPTS / "enrich_casos_keys.py",
    ]
    for path in writer_paths:
        text = path.read_text(encoding="utf-8")
        assert "confidence.jsonl" not in text
        assert "identity_confidence" not in text
        assert "conf-" not in text

    handoff_paths = [
        ROOT / "data/review/attach/edges.jsonl",
        ROOT / "data/review/research-adjudicated/scale-checkpoint/pre-auto-backup-20260703/attach-edges.before-auto.jsonl",
        ROOT / "data/review/research-adjudicated/scale-checkpoint/pre-trio-auto-backup-20260704/attach-edges.before-trio-auto.jsonl",
    ]
    for path in handoff_paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            edge = json.loads(line)
            if edge.get("relationship_type") != "SAME_AS":
                continue
            assertion_id = (edge.get("properties") or {}).get("assertion_id")
            assert isinstance(assertion_id, str)
            assert assertion_id.startswith("assertion-")
            assert not assertion_id.startswith("conf-")


def test_backfill_cli_without_collision_context_caps_high_candidate_at_medium(tmp_path):
    verdicts = tmp_path / "verdicts.jsonl"
    read_model = tmp_path / "read-model.jsonl"
    ledger = tmp_path / "assertions.jsonl"
    out = tmp_path / "confidence.jsonl"

    verdicts.write_text(json.dumps(_feed()) + "\n", encoding="utf-8")
    read_model.write_text(json.dumps(_case()) + "\n", encoding="utf-8")
    original_ledger = json.dumps(_approved_assertion() | {"target_ref": "other-vendor"}) + "\n"
    ledger.write_text(original_ledger, encoding="utf-8")

    code = ic.main(
        [
            "--verdicts",
            str(verdicts),
            "--read-model",
            str(read_model),
            "--ledger",
            str(ledger),
            "--out",
            str(out),
            "--computed-at",
            COMPUTED_AT,
        ]
    )

    assert code == 0
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["band"] == "medium"
    assert row["status"] == "active"
    assert ledger.read_text(encoding="utf-8") == original_ledger


def test_backfill_cli_compacts_legacy_duplicate_pairs_last_append_wins(tmp_path):
    verdicts = tmp_path / "verdicts.jsonl"
    read_model = tmp_path / "read-model.jsonl"
    ledger = tmp_path / "assertions.jsonl"
    out = tmp_path / "confidence.jsonl"

    first = _feed() | {"verdict": "different", "confidence": 0.2, "gid": 1}
    second = _feed() | {"verdict": "same", "confidence": 0.91, "gid": 2}
    verdicts.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
    read_model.write_text(json.dumps(_case()) + "\n", encoding="utf-8")
    ledger.write_text("", encoding="utf-8")

    code = ic.main(
        [
            "--verdicts",
            str(verdicts),
            "--read-model",
            str(read_model),
            "--ledger",
            str(ledger),
            "--out",
            str(out),
            "--computed-at",
            COMPUTED_AT,
        ]
    )

    assert code == 0
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["source_row"] == {"run": "c4", "gid": 2}
    assert row["signals"]["confidence"] == 0.91
