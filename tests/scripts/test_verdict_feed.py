"""R5 verdict-feed schema tests.

The feed is the durable advisory-verdict input for reconciliation. It must be
versioned, validate researcher free text through the redaction gate, and refuse
duplicate contradictions instead of silently taking the last row.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import verdict_feed as vf  # noqa: E402


def v1_row(**over):
    row = {
        "schema_version": "verdict-feed-v1",
        "vendor_id": "org-vendor-alpha",
        "proposed_key": "111111111",
        "verdict": "same",
        "confidence": 0.97,
        "provenance": {"model": "synthetic-model", "run": "unit-test"},
        "verification": {
            "verify_ok": True,
            "refuted": False,
            "ks_valid": True,
            "key_sighted": True,
        },
        "reason": "synthetic exact key sighting",
        "gid": 7,
        "auto_candidate": True,
    }
    row.update(over)
    return row


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def test_validate_v1_row_round_trips_through_loader(tmp_path):
    row = v1_row()
    assert vf.validate_row(row) == row
    p = tmp_path / "feed.jsonl"
    _write_jsonl(p, [row])

    loaded = vf.load_feed([p])

    assert loaded == [row]


def test_validate_rejects_prefixed_key_bad_confidence_and_forbidden_text():
    with pytest.raises(ValueError, match="literal"):
        vf.validate_row(v1_row(proposed_key="org-bmf-ein-111111111"))
    with pytest.raises(ValueError, match="confidence"):
        vf.validate_row(v1_row(confidence=1.01))
    with pytest.raises(ValueError, match="redaction"):
        vf.validate_row(v1_row(reason="REDACT_ME_STREET"))


def test_load_feed_collapses_byte_identical_duplicate_pair(tmp_path):
    p = tmp_path / "feed.jsonl"
    row = v1_row()
    _write_jsonl(p, [row, row])

    assert vf.load_feed([p]) == [row]


def test_load_feed_collapses_byte_identical_legacy_duplicate_across_files(tmp_path):
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    legacy = {
        "vendor_id": "org-vendor-alpha",
        "proposed_key": "111111111",
        "verdict": "same",
        "confidence": 0.97,
    }
    _write_jsonl(first, [legacy])
    _write_jsonl(second, [legacy])

    loaded = vf.load_feed([first, second])

    assert len(loaded) == 1
    assert loaded[0]["provenance"] == {"model": "legacy-verdict-feed", "run": "legacy"}


def test_load_feed_raises_on_conflicting_duplicate_pair_with_both_rows(tmp_path):
    p = tmp_path / "feed.jsonl"
    first = v1_row(verdict="same")
    second = v1_row(verdict="different")
    _write_jsonl(p, [first, second])

    with pytest.raises(vf.VerdictFeedConflictError) as exc:
        vf.load_feed([p])

    msg = str(exc.value)
    assert "org-vendor-alpha" in msg
    assert '"verdict": "same"' in msg
    assert '"verdict": "different"' in msg


def test_summarize_conflicts_surfaces_duplicate_conflict_fields():
    conflicts = vf.summarize_conflicts([
        v1_row(verdict="same", confidence=0.97),
        v1_row(verdict="different", confidence=0.88),
    ])

    assert conflicts == [
        {
            "vendor_id": "org-vendor-alpha",
            "proposed_key": "111111111",
            "fields": ["confidence", "verdict"],
            "first": v1_row(verdict="same", confidence=0.97),
            "second": v1_row(verdict="different", confidence=0.88),
        }
    ]


def test_upgrade_legacy_pilot_verdict_shape_to_v1():
    legacy = {
        "vendor_id": "org-vendor-pilot",
        "proposed_key": "942605669",
        "lane": "ein",
        "verdict": "same",
        "confidence": 0.95,
        "reason": "pilot reason",
        "model": "fable+sonnet researchers",
        "adjudicator_version": "pilot-v1",
        "key_sighted": True,
        "verifier": {"ran": True, "refuted": False},
    }

    upgraded = vf.upgrade_legacy(legacy, provenance_defaults={"model": "fallback", "run": "fallback-run"})

    assert upgraded == {
        "schema_version": "verdict-feed-v1",
        "vendor_id": "org-vendor-pilot",
        "proposed_key": "942605669",
        "verdict": "same",
        "confidence": 0.95,
        "provenance": {"model": "fable+sonnet researchers", "run": "pilot-v1"},
        "verification": {"key_sighted": True, "refuted": False},
        "reason": "pilot reason",
    }


def test_upgrade_legacy_scale_prefixed_key_shape_to_v1():
    legacy = {
        "gid": 1,
        "vendor_id": "org-vendor-scale",
        "proposed_key": "org-bmf-ein-111111111",
        "verdict": "same",
        "confidence": 0.93,
        "key_sighted": True,
        "verify_ok": True,
        "refuted": False,
        "ks_valid": True,
        "auto_candidate": False,
    }

    upgraded = vf.upgrade_legacy(
        legacy,
        provenance_defaults={"model": "scale-adjudicator", "run": "scale-checkpoint"},
    )

    assert upgraded["proposed_key"] == "111111111"
    assert upgraded["source_proposed_key"] == "org-bmf-ein-111111111"
    assert upgraded["verification"] == {
        "verify_ok": True,
        "refuted": False,
        "ks_valid": True,
        "key_sighted": True,
    }
    assert upgraded["gid"] == 1
    assert upgraded["auto_candidate"] is False
    assert upgraded["provenance"] == {"model": "scale-adjudicator", "run": "scale-checkpoint"}


def test_upgrade_legacy_tranche_shape_to_v1():
    legacy = {
        "gid": 1487,
        "vendor_id": "org-vendor-tranche",
        "literal_key": "0526212",
        "proposed_key": "org-casos-0526212",
        "verdict": "same",
        "confidence": 0.86,
        "researcher": "codex-2026-07-04",
        "key_sighted": False,
        "verify_ok": False,
        "ks_valid": False,
        "refuted": None,
        "auto_candidate": False,
        "reason": "tranche reason",
    }

    upgraded = vf.upgrade_legacy(
        legacy,
        provenance_defaults={"model": "research-tranche", "run": "shard3", "tranche": "1"},
    )

    assert upgraded == {
        "schema_version": "verdict-feed-v1",
        "vendor_id": "org-vendor-tranche",
        "proposed_key": "0526212",
        "verdict": "same",
        "confidence": 0.86,
        "provenance": {"model": "research-tranche", "run": "shard3", "tranche": "1"},
        "verification": {"verify_ok": False, "ks_valid": False, "key_sighted": False},
        "reason": "tranche reason",
        "source_proposed_key": "org-casos-0526212",
        "gid": 1487,
        "auto_candidate": False,
    }
