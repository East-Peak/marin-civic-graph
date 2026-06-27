"""Goal 1 Unit 1 — the reconciliation domain model + validator.

ReconciliationCase is the top-level unit (an envelope holding candidate_joins[]);
EntityRef is a normalized source endpoint (NOT the graph `Record`); CandidateJoin is
pairwise evidence inside a case. Only identity_key_attach + entity_dedup_merge are
active; relationship_candidate/pattern_candidate are reserved and validator-rejected.
The validator also enforces the §5.2.1 action matrix and join-count/actionability rules.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconciliation_cases as rc  # noqa: E402


def _ref(local_id: str) -> "rc.EntityRef":
    return rc.EntityRef(
        source_id="src", local_id=local_id, display_label=local_id,
        public_fields={"display_label": local_id}, provenance={"adapter": "test"},
    )


def _join(jid: str = "j1") -> "rc.CandidateJoin":
    return rc.CandidateJoin(
        candidate_id=jid, left_ref=_ref("a"), right_ref=_ref("b"),
        signals=["normalized_name_exact"], signal_strength=0.9,
    )


def _case(case_type: str, n_joins: int = 1) -> "rc.ReconciliationCase":
    return rc.ReconciliationCase(
        schema_version=rc.SCHEMA_VERSION, case_id="case-1", case_type=case_type,
        candidate_joins=[_join(f"j{i}") for i in range(n_joins)], actionability="actionable",
    )


# --- model shape ----------------------------------------------------------

def test_case_type_sets():
    assert rc.ACTIVE_CASE_TYPES == {"identity_key_attach", "entity_dedup_merge"}
    assert rc.RESERVED_CASE_TYPES == {"relationship_candidate", "pattern_candidate"}
    assert rc.ACTIVE_CASE_TYPES.isdisjoint(rc.RESERVED_CASE_TYPES)


def test_entity_ref_not_named_record():
    # the model endpoint is EntityRef; the graph Record type is untouched
    assert hasattr(rc, "EntityRef")
    assert not hasattr(rc, "Record")


def test_candidate_join_has_no_actionability_but_case_does():
    j = _join()
    assert not hasattr(j, "actionability")  # actionability is case/component-scoped
    c = _case("identity_key_attach")
    assert c.actionability == "actionable"  # one per case envelope


# --- validate_case --------------------------------------------------------

@pytest.mark.parametrize("reserved", ["relationship_candidate", "pattern_candidate"])
def test_validate_case_rejects_reserved(reserved):
    with pytest.raises(ValueError, match="reserved"):
        rc.validate_case(_case(reserved))


def test_validate_case_rejects_unknown_type():
    with pytest.raises(ValueError, match="case_type"):
        rc.validate_case(_case("nonsense"))


def test_validate_case_attach_requires_exactly_one_join():
    rc.validate_case(_case("identity_key_attach", 1))  # ok
    with pytest.raises(ValueError, match="one join"):
        rc.validate_case(_case("identity_key_attach", 2))
    with pytest.raises(ValueError, match="one join"):
        rc.validate_case(_case("identity_key_attach", 0))


def test_validate_case_dedup_requires_at_least_one_join():
    rc.validate_case(_case("entity_dedup_merge", 1))  # ok
    rc.validate_case(_case("entity_dedup_merge", 3))  # ok
    with pytest.raises(ValueError, match="at least one join"):
        rc.validate_case(_case("entity_dedup_merge", 0))


# --- validate_action (the §5.2.1 matrix) ----------------------------------

@pytest.mark.parametrize("reserved", ["relationship_candidate", "pattern_candidate"])
def test_reserved_permits_no_action(reserved):
    with pytest.raises(ValueError, match="reserved"):
        rc.validate_action(reserved, "approve")


@pytest.mark.parametrize("ct", ["identity_key_attach", "entity_dedup_merge"])
def test_active_approve_and_unsure_ok(ct):
    rc.validate_action(ct, "approve")
    rc.validate_action(ct, "unsure")


@pytest.mark.parametrize("ct", ["identity_key_attach", "entity_dedup_merge"])
def test_reject_requires_valid_rejection_kind(ct):
    rc.validate_action(ct, "reject", rejection_kind="current_evidence")
    rc.validate_action(ct, "reject", rejection_kind="entity_distinct")
    with pytest.raises(ValueError, match="rejection_kind"):
        rc.validate_action(ct, "reject")
    with pytest.raises(ValueError, match="rejection_kind"):
        rc.validate_action(ct, "reject", rejection_kind="bogus")


def test_rejection_kind_only_for_reject():
    with pytest.raises(ValueError, match="rejection_kind"):
        rc.validate_action("identity_key_attach", "approve", rejection_kind="current_evidence")


def test_unknown_action_rejected():
    with pytest.raises(ValueError, match="action"):
        rc.validate_action("identity_key_attach", "frobnicate")


def test_rejection_kind_maps_to_status():
    assert rc.rejection_status("current_evidence") == "rejected_current_evidence"
    assert rc.rejection_status("entity_distinct") == "rejected_entity_distinct"
