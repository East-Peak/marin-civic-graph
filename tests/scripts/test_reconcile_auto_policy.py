"""Tests for reconcile_auto_policy.py — signed §9a first-batch preview.

The policy helper is deliberately separate from the workbench's old `bulk_eligible`
lane. It normalizes scale-run verdict keys, then computes a fresh eligibility
snapshot from verdicts + Codex second research + current read model + explicit
collision context. No ledger writes here.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconcile_auto_policy as ap  # noqa: E402
from identity_key_registry import ANCHOR_PREFIXES  # noqa: E402


POLICY_HASH = "h-policy"


def verdict(**over):
    row = {
        "gid": 13,
        "vendor_id": "vendor-a",
        "proposed_key": "org-bmf-ein-911930327",
        "verdict": "same",
        "confidence": 0.93,
        "key_sighted": True,
        "verify_ok": True,
        "refuted": False,
        "ks_valid": True,
        "auto_candidate": True,
    }
    row.update(over)
    return row


def second(**over):
    row = {
        "gid": 13,
        "vendor_id": "vendor-a",
        "proposed_key": "org-bmf-ein-911930327",
        "literal_key": "911930327",
        "organization": "Bridge the Gap College Prep",
        "second_researcher": {
            "verdict": "same",
            "confidence": 0.95,
            "key_sighted_valid": True,
        },
        "skeptic": {"concurrence": True, "refuted": False},
        "evidence": [{"url": "https://example.org/evidence"}],
    }
    row.update(over)
    return row


def case(**over):
    c = {
        "case_id": "attach|org-bmf-ein-911930327|vendor-a",
        "case_type": "identity_key_attach",
        "candidate_joins": [
            {
                "left_ref": {"source_id": "ein", "local_id": "vendor-a", "display_label": "Vendor A", "public_fields": {}},
                "right_ref": {
                    "local_id": "org-bmf-ein-911930327",
                    "display_label": "Bridge the Gap College Prep",
                    "public_fields": {"registry_ein": "911930327"},
                },
            }
        ],
        "current_ledger_status": "none",
        "review_flags": {},
        "bulk_eligible": False,
        "ai_reviews": [],
    }
    c.update(over)
    return c


def context(**over):
    ctx = {
        "display_label": "Bridge the Gap College Prep",
        "money_total": 20000,
        "flow_count": 2,
        "departments": ["Non Departmental"],
        "key_collision": False,
        "collides_with": [],
    }
    ctx.update(over)
    return ctx


def test_literal_key_normalization_uses_registry_anchor_prefixes():
    assert "org-fppc-" in ANCHOR_PREFIXES
    assert "org-usasp-uei-" in ANCHOR_PREFIXES
    assert ap.literal_proposed_key({"proposed_key": "org-bmf-ein-911930327"}) == "911930327"
    assert ap.literal_proposed_key({"proposed_key": "org-casos-0289793"}) == "0289793"
    assert ap.literal_proposed_key({"proposed_key": "org-fppc-1470249"}) == "1470249"
    assert ap.literal_proposed_key({"proposed_key": "org-usasp-uei-UEI123456789"}) == "UEI123456789"
    assert ap.literal_proposed_key({"proposed_key": "941156528"}) == "941156528"


def test_normalized_verdict_preserves_original_anchor_key_for_audit():
    out = ap.normalized_verdict_row(verdict())
    assert out["proposed_key"] == "911930327"
    assert out["source_proposed_key"] == "org-bmf-ein-911930327"


def test_case_ref_private_helpers_delegate_to_reconciliation_refs(monkeypatch):
    c = case()
    monkeypatch.setattr(ap, "vendor_id_of", lambda case: "vendor-from-helper")
    monkeypatch.setattr(ap, "anchor_id_of", lambda case: "anchor-from-helper")
    monkeypatch.setattr(ap, "literal_key_of", lambda case: "literal-from-helper")

    assert ap._vendor_id(c) == "vendor-from-helper"
    assert ap._anchor_id(c) == "anchor-from-helper"
    assert ap._case_literal_key(c) == "literal-from-helper"


def test_preview_eligibility_ignores_old_bulk_eligible_and_hashes_snapshot():
    preview = ap.build_preview(
        verdict_rows=[verdict()],
        second_research_rows=[second()],
        read_model_cases=[case()],
        context_by_vendor={"vendor-a": context()},
        policy_hash=POLICY_HASH,
    )
    assert preview["eligible_count"] == 1
    assert preview["eligible"][0]["case_id"] == "attach|org-bmf-ein-911930327|vendor-a"
    assert preview["eligible"][0]["money_total"] == 20000
    assert preview["eligible"][0]["evidence_urls"] == ["https://example.org/evidence"]
    assert preview["eligibility_snapshot_hash"].startswith("sha256:")


def test_preview_accepts_v1_verdict_feed_rows_with_nested_verification():
    preview = ap.build_preview(
        verdict_rows=[
            {
                "schema_version": "verdict-feed-v1",
                "vendor_id": "vendor-a",
                "proposed_key": "911930327",
                "verdict": "same",
                "confidence": 0.93,
                "provenance": {"model": "unit", "run": "r5"},
                "verification": {
                    "key_sighted": True,
                    "verify_ok": True,
                    "refuted": False,
                    "ks_valid": True,
                },
                "source_proposed_key": "org-bmf-ein-911930327",
                "gid": 13,
                "auto_candidate": True,
            }
        ],
        second_research_rows=[second()],
        read_model_cases=[case()],
        context_by_vendor={"vendor-a": context()},
        policy_hash=POLICY_HASH,
    )

    assert preview["eligible_count"] == 1
    assert preview["eligible"][0]["literal_key"] == "911930327"


def test_preview_requires_second_research_and_skeptic_concurrence():
    preview = ap.build_preview(
        verdict_rows=[verdict()],
        second_research_rows=[second(second_researcher={"verdict": "unsure", "key_sighted_valid": True})],
        read_model_cases=[case()],
        context_by_vendor={"vendor-a": context()},
        policy_hash=POLICY_HASH,
    )
    assert preview["eligible_count"] == 0
    assert preview["ineligible"][0]["reasons"] == ["second_research_not_same"]


def test_preview_requires_explicit_clean_collision_context():
    missing = ap.build_preview(
        verdict_rows=[verdict()],
        second_research_rows=[second()],
        read_model_cases=[case()],
        context_by_vendor={},
        policy_hash=POLICY_HASH,
    )
    collided = ap.build_preview(
        verdict_rows=[verdict()],
        second_research_rows=[second()],
        read_model_cases=[case()],
        context_by_vendor={"vendor-a": context(key_collision=True, collides_with=["org-other"])},
        policy_hash=POLICY_HASH,
    )
    assert missing["ineligible"][0]["reasons"] == ["missing_collision_context"]
    assert collided["ineligible"][0]["reasons"] == ["live_collision"]


def test_preview_recomputes_single_candidate_from_current_read_model():
    other = case(
        case_id="attach|org-bmf-ein-000000000|vendor-a",
        candidate_joins=[
            {
                "left_ref": {"local_id": "vendor-a", "display_label": "Vendor A", "public_fields": {}},
                "right_ref": {
                    "local_id": "org-bmf-ein-000000000",
                    "display_label": "Other",
                    "public_fields": {"registry_ein": "000000000"},
                },
            }
        ],
    )
    preview = ap.build_preview(
        verdict_rows=[verdict()],
        second_research_rows=[second()],
        read_model_cases=[case(), other],
        context_by_vendor={"vendor-a": context()},
        policy_hash=POLICY_HASH,
    )
    assert preview["eligible_count"] == 0
    assert preview["ineligible"][0]["reasons"] == ["not_single_candidate"]


def test_cli_preview_writes_deterministic_json(tmp_path):
    verdicts = tmp_path / "verdicts.jsonl"
    read_model = tmp_path / "read-model.jsonl"
    second_research = tmp_path / "second.json"
    context_file = tmp_path / "context.json"
    out = tmp_path / "preview.json"

    verdicts.write_text(json.dumps(verdict()) + "\n", encoding="utf-8")
    read_model.write_text(json.dumps(case()) + "\n", encoding="utf-8")
    second_research.write_text(json.dumps({"results": [second()]}), encoding="utf-8")
    context_file.write_text(json.dumps({"vendor-a": context()}), encoding="utf-8")

    rc = ap.main([
        "preview",
        "--verdicts", str(verdicts),
        "--second-research", str(second_research),
        "--read-model", str(read_model),
        "--context", str(context_file),
        "--policy-hash", POLICY_HASH,
        "--out", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["eligible_count"] == 1
    assert payload["eligible"][0]["literal_key"] == "911930327"


def _write_apply_inputs(tmp_path, *, context_row=None):
    verdicts = tmp_path / "verdicts.jsonl"
    read_model = tmp_path / "read-model.jsonl"
    second_research = tmp_path / "second.json"
    context_file = tmp_path / "context.json"
    preview_file = tmp_path / "preview.json"
    candidates = tmp_path / "ein-candidates.jsonl"

    verdicts.write_text(json.dumps(verdict()) + "\n", encoding="utf-8")
    read_model.write_text(json.dumps(case()) + "\n", encoding="utf-8")
    second_research.write_text(json.dumps({"results": [second()]}), encoding="utf-8")
    context_file.write_text(json.dumps({"vendor-a": context_row or context()}), encoding="utf-8")
    candidates.write_text(json.dumps({
        "subject_ref": "org-bmf-ein-911930327",
        "candidate_ref": "vendor-a",
        "ein": "911930327",
        "evidence_record_ids": ["ev-1", "ev-2"],
    }) + "\n", encoding="utf-8")

    preview = ap.build_preview(
        verdict_rows=[verdict()],
        second_research_rows=[second()],
        read_model_cases=[case()],
        context_by_vendor={"vendor-a": context_row or context()},
        policy_hash=POLICY_HASH,
    )
    preview_file.write_text(json.dumps(preview, sort_keys=True) + "\n", encoding="utf-8")
    return verdicts, read_model, second_research, context_file, preview_file, candidates


def _mark_context_fresh(context_file: Path, preview_file: Path) -> None:
    fresh = preview_file.stat().st_mtime + 1
    os.utime(context_file, (fresh, fresh))


def test_apply_batch_recomputes_snapshot_and_stamps_policy_metadata(tmp_path):
    verdicts, read_model, second_research, context_file, preview_file, candidates = _write_apply_inputs(tmp_path)
    _mark_context_fresh(context_file, preview_file)
    ledger = tmp_path / "ledger.jsonl"
    attach_dir = tmp_path / "attach"
    result = ap.apply_batch(
        verdicts=verdicts,
        second_research=second_research,
        read_model=read_model,
        context=context_file,
        preview=preview_file,
        policy_hash=POLICY_HASH,
        candidate_paths={"ein": candidates},
        ledger=ledger,
        attach_dir=attach_dir,
        reviewer=ap.RESEARCH_POLICY_REVIEWER,
        decided_at="2026-07-03T20:00:00Z",
    )
    assertion = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert result["applied_count"] == 1
    assert assertion["reviewer"] == ap.RESEARCH_POLICY_REVIEWER
    assert assertion["policy_version"] == ap.AUTO_APPROVE_POLICY_VERSION
    assert assertion["policy_version"] != assertion["reviewer"]
    assert assertion["policy_hash"] == POLICY_HASH
    assert assertion["eligibility_snapshot_hash"] == result["eligibility_snapshot_hash"]
    assert assertion["evidence_refs"] == ["ev-1", "ev-2"]
    edge = json.loads((attach_dir / "edges.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert edge["properties"]["assertion_id"] == assertion["id"]


def test_apply_batch_aborts_on_snapshot_drift_before_writing(tmp_path):
    verdicts, read_model, second_research, context_file, preview_file, candidates = _write_apply_inputs(tmp_path)
    _mark_context_fresh(context_file, preview_file)
    context_file.write_text(json.dumps({"vendor-a": context(money_total=21000)}) + "\n", encoding="utf-8")
    _mark_context_fresh(context_file, preview_file)
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(ValueError, match="snapshot drift"):
        ap.apply_batch(
            verdicts=verdicts,
            second_research=second_research,
            read_model=read_model,
            context=context_file,
            preview=preview_file,
            policy_hash=POLICY_HASH,
            candidate_paths={"ein": candidates},
            ledger=ledger,
            attach_dir=tmp_path / "attach",
            reviewer=ap.RESEARCH_POLICY_REVIEWER,
            decided_at="2026-07-03T20:00:00Z",
        )
    assert not ledger.exists()


def test_apply_batch_refuses_context_older_than_approved_preview(tmp_path):
    verdicts, read_model, second_research, context_file, preview_file, candidates = _write_apply_inputs(tmp_path)
    stale = preview_file.stat().st_mtime - 10
    os.utime(context_file, (stale, stale))
    ledger = tmp_path / "ledger.jsonl"

    with pytest.raises(ValueError, match="stale collision context"):
        ap.apply_batch(
            verdicts=verdicts,
            second_research=second_research,
            read_model=read_model,
            context=context_file,
            preview=preview_file,
            policy_hash=POLICY_HASH,
            candidate_paths={"ein": candidates},
            ledger=ledger,
            attach_dir=tmp_path / "attach",
            reviewer=ap.RESEARCH_POLICY_REVIEWER,
            decided_at="2026-07-03T20:00:00Z",
        )
    assert not ledger.exists()


def test_auto_policy_artifact_writers_refuse_poisoned_payloads(tmp_path):
    poisoned_jsonl = tmp_path / "poisoned.jsonl"
    with pytest.raises(ValueError, match="redaction"):
        ap._write_jsonl(poisoned_jsonl, [{"vendor_id": "vendor-a", "reason": "REDACT_ME_STREET"}])
    assert not poisoned_jsonl.exists()

    poisoned_json = tmp_path / "poisoned.json"
    with pytest.raises(ValueError, match="redaction"):
        ap._write_json(poisoned_json, {"principal_address": "not publishable"})
    assert not poisoned_json.exists()
