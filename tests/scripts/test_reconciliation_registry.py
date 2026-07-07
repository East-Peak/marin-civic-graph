"""R4 — reconciliation registry surfaces.

`registry/reconciliation.json` is the single source for reconciliation ledger
status actionability, operator-bench buckets, and public key-source fields.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import identity_key_registry as identity_keys  # noqa: E402
import reconciliation_read_model as read_model  # noqa: E402
from reconciliation_registry import (  # noqa: E402
    BENCH_BUCKETS,
    CONFIDENCE_BANDS,
    KEY_SOURCES,
    LEDGER_ACTIONABILITY,
    load_registry,
)

REGISTRY_PATH = ROOT / "registry" / "reconciliation.json"


def test_registry_file_exists():
    assert REGISTRY_PATH.is_file()


def test_read_model_actionability_derives_from_registry():
    assert read_model._ACTIONABILITY == LEDGER_ACTIONABILITY
    assert read_model._ACTIONABILITY == {
        "none": "actionable",
        "requeued": "needs_review",
        "approved": "resolved",
        "deterministic": "resolved",
        "superseded": "resolved",
        "rejected_current_evidence": "resolved",
        "rejected_entity_distinct": "resolved",
    }


def test_bench_bucket_registry_matches_existing_contract():
    assert BENCH_BUCKETS == {
        "rejected": ("rejected_current_evidence", "rejected_entity_distinct"),
        "done": ("approved", "superseded", "deterministic", "unsure"),
        "known_statuses": (
            "none",
            "requeued",
            "approved",
            "superseded",
            "deterministic",
            "rejected_current_evidence",
            "rejected_entity_distinct",
        ),
    }


def test_confidence_bands_registry_matches_identity_confidence_contract():
    assert CONFIDENCE_BANDS == {
        "order": ("high", "medium", "low"),
        "thresholds": {
            "high_min_confidence": 0.80,
            "medium_min_confidence": 0.65,
            "high_min_dimensions": 2,
        },
    }


def test_key_sources_cross_check_identity_key_registry_anchor_prefixes():
    identity_self_sources = {
        e.key_type: {
            "source_id": e.key_type,
            "anchor_prefix": e.anchor_prefix,
            "public_key_field": e.public_key_field,
            "anchor_source": e.anchor_source,
            "attach_basis": e.attach_basis,
            "anchor_subject_fields": dict(e.anchor_subject_fields),
        }
        for e in identity_keys.REGISTRY
        if e.key_type in {"ein", "sos_id", "committee_id"}
        and e.key_semantics == "self"
        and e.dedup_eligibility
    }

    assert {
        key: {
            "source_id": spec["source_id"],
            "anchor_prefix": spec["anchor_prefix"],
            "public_key_field": spec["public_key_field"],
            "anchor_source": spec["anchor_source"],
            "attach_basis": spec["attach_basis"],
            "anchor_subject_fields": spec["anchor_subject_fields"],
        }
        for key, spec in KEY_SOURCES.items()
    } == identity_self_sources
    assert {key: spec["public_key_field"] for key, spec in KEY_SOURCES.items()} == {
        "ein": "registry_ein",
        "sos_id": "sos_id",
        "committee_id": "committee_id",
    }


def test_registry_validation_rejects_missing_required_status(tmp_path):
    registry = load_registry()
    bad = json.loads(json.dumps(registry))
    del bad["ledger_statuses"]["none"]
    p = tmp_path / "missing-status.json"
    p.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValueError, match="ledger_statuses"):
        load_registry(p)


def test_registry_validation_rejects_unknown_bucket_status(tmp_path):
    registry = load_registry()
    bad = json.loads(json.dumps(registry))
    bad["bench_display_buckets"]["done"].append("mystery_status")
    p = tmp_path / "unknown-bucket-status.json"
    p.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown"):
        load_registry(p)


def test_registry_validation_rejects_key_source_drift(tmp_path):
    registry = load_registry()
    bad = json.loads(json.dumps(registry))
    bad["key_sources"]["ein"]["anchor_prefix"] = "org-drift-"
    p = tmp_path / "drift.json"
    p.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValueError, match="identity_key_registry"):
        load_registry(p)


def test_registry_validation_rejects_confidence_band_drift(tmp_path):
    registry = load_registry()
    bad = json.loads(json.dumps(registry))
    bad["confidence_bands"]["order"] = ["medium", "high", "low"]
    p = tmp_path / "band-order-drift.json"
    p.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValueError, match="confidence_bands.order"):
        load_registry(p)


def test_registry_validation_rejects_confidence_threshold_drift(tmp_path):
    registry = load_registry()
    bad = json.loads(json.dumps(registry))
    bad["confidence_bands"]["thresholds"]["high_min_dimensions"] = 1
    p = tmp_path / "band-threshold-drift.json"
    p.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValueError, match="high_min_dimensions"):
        load_registry(p)


def test_registry_validation_rejects_anchor_subject_field_drift(tmp_path):
    registry = load_registry()
    bad = json.loads(json.dumps(registry))
    bad["key_sources"]["committee_id"]["anchor_subject_fields"]["entity_class"] = "const:organization"
    p = tmp_path / "subject-drift.json"
    p.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValueError, match="identity_key_registry"):
        load_registry(p)
