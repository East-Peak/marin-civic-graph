"""Tests for the resolution adapter + resolver-ref schema (Identity Control A, Unit 3).

Two additive pieces (the resolver `org_resolution.py` is NOT edited):
- `normalize_resolution_candidate_for_artifact()` — renames `confidence` →
  `signal_strength` for identity-resolution artifacts ONLY (a signal, never a
  calibrated probability). Graph-node `confidence` (Membership/EconomicInterest)
  is a different code path and untouched.
- the resolver-ref class schema + the deterministic-merge guardrail allowlist:
  EIN/UEI equality may become a SAME_AS only when the key is the org's OWN
  identity (`key_semantics == "self"`); a parent UEI / fiscal-sponsor EIN / DBA /
  PAC-committee / project key is a RELATIONSHIP candidate, never a SAME_AS.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from identity_resolution_adapter import (  # noqa: E402
    RELATIONSHIP_SEMANTICS,
    deterministic_merge_allowed,
    egress_ref_complete,
    normalize_resolution_candidate_for_artifact,
)


class TestSignalStrengthAdapter:
    def test_confidence_renamed_to_signal_strength(self):
        cand = {"subject_ref": "a", "candidate_ref": "b", "signals": ["normalized_name_exact"],
                "confidence": 0.9, "status": "queued", "evidence_record_ids": []}
        out = normalize_resolution_candidate_for_artifact(cand)
        assert out["signal_strength"] == 0.9
        assert "confidence" not in out
        assert out["subject_ref"] == "a" and out["signals"] == ["normalized_name_exact"]

    def test_idempotent_when_already_signal_strength(self):
        cand = {"subject_ref": "a", "candidate_ref": "b", "signal_strength": 0.87}
        out = normalize_resolution_candidate_for_artifact(cand)
        assert out["signal_strength"] == 0.87 and "confidence" not in out

    def test_does_not_mutate_input(self):
        cand = {"subject_ref": "a", "candidate_ref": "b", "confidence": 0.9}
        normalize_resolution_candidate_for_artifact(cand)
        assert cand["confidence"] == 0.9   # original untouched


class TestDeterministicMergeGuardrail:
    def test_self_identity_key_may_merge(self):
        assert deterministic_merge_allowed({"key_semantics": "self", "entity_class": "organization"}) is True

    def test_relationship_semantics_never_merge(self):
        for sem in RELATIONSHIP_SEMANTICS:
            assert deterministic_merge_allowed(
                {"key_semantics": sem, "entity_class": "organization"}) is False, sem
        # the canonical traps:
        assert deterministic_merge_allowed({"key_semantics": "fiscal_sponsor"}) is False
        assert deterministic_merge_allowed({"key_semantics": "parent"}) is False
        assert deterministic_merge_allowed({"key_semantics": "committee"}) is False  # PAC

    def test_entity_class_mismatch_never_merges(self):
        # an org's EIN must not merge to a committee/PAC entity even if "self"
        assert deterministic_merge_allowed(
            {"key_semantics": "self", "entity_class": "organization"},
            {"key_semantics": "self", "entity_class": "committee"}) is False

    def test_relationship_semantics_set(self):
        assert RELATIONSHIP_SEMANTICS == frozenset({"parent", "fiscal_sponsor", "dba", "committee", "project"})


class TestEgressRefCompleteness:
    def test_complete_ref_has_class_fields(self):
        assert egress_ref_complete(
            {"id": "org-a", "entity_class": "organization", "source_system": "form_990",
             "key_semantics": "self"}) is True

    def test_ref_missing_class_fields_is_incomplete(self):
        # an egress-capable caller that omits the schema must be caught (the gate
        # fails closed in Unit 4); a bare legacy ref is incomplete.
        assert egress_ref_complete({"id": "org-a", "display_label": "A"}) is False
        assert egress_ref_complete({"id": "org-a", "entity_class": "organization"}) is False
