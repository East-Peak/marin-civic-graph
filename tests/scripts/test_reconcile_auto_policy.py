"""Tests for reconcile_auto_policy.py — signed §9a first-batch preview.

The policy helper is deliberately separate from the workbench's old `bulk_eligible`
lane. It normalizes scale-run verdict keys, then computes a fresh eligibility
snapshot from verdicts + Codex second research + current read model + explicit
collision context. No ledger writes here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconcile_auto_policy as ap  # noqa: E402


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


def test_literal_key_normalization_handles_bmf_and_casos_anchor_ids():
    assert ap.literal_proposed_key({"proposed_key": "org-bmf-ein-911930327"}) == "911930327"
    assert ap.literal_proposed_key({"proposed_key": "org-casos-0289793"}) == "0289793"
    assert ap.literal_proposed_key({"proposed_key": "941156528"}) == "941156528"


def test_normalized_verdict_preserves_original_anchor_key_for_audit():
    out = ap.normalized_verdict_row(verdict())
    assert out["proposed_key"] == "911930327"
    assert out["source_proposed_key"] == "org-bmf-ein-911930327"


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


def test_apply_batch_recomputes_snapshot_and_stamps_policy_metadata(tmp_path):
    verdicts, read_model, second_research, context_file, preview_file, candidates = _write_apply_inputs(tmp_path)
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
    assert assertion["policy_version"] == ap.RESEARCH_POLICY_REVIEWER
    assert assertion["policy_hash"] == POLICY_HASH
    assert assertion["eligibility_snapshot_hash"] == result["eligibility_snapshot_hash"]
    assert assertion["evidence_refs"] == ["ev-1", "ev-2"]
    edge = json.loads((attach_dir / "edges.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert edge["properties"]["assertion_id"] == assertion["id"]


def test_apply_batch_aborts_on_snapshot_drift_before_writing(tmp_path):
    verdicts, read_model, second_research, context_file, preview_file, candidates = _write_apply_inputs(tmp_path)
    context_file.write_text(json.dumps({"vendor-a": context(money_total=21000)}) + "\n", encoding="utf-8")
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
