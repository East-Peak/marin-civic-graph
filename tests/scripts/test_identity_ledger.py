"""Tests for scripts/identity_ledger.py — the IdentityAssertion ledger (Identity Control A, Unit 1).

The versioned, supersedable record of every cross-source identity decision
(deterministic key-merge / human approve / human reject). Only a `deterministic`
or `approved` assertion is publishing; everything else is private. Pure
read/write/supersede helpers — never a graph node type, never a clock
(`decided_at` is operator-supplied). The status × trigger re-queue matrix is
Predeclared 6 of the goal doc.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from identity_ledger import (  # noqa: E402
    PUBLISHING_STATUSES,
    STATUSES,
    assertion_id,
    fingerprint,
    is_publishing,
    make_assertion,
    read_assertions,
    should_requeue,
    source_snapshot_hash,
    supersede,
    write_assertions,
)


def _ref(id, label, **keys):
    return {"id": id, "display_label": label, **keys}


class TestSchemaConstants:
    def test_status_set_is_exactly_the_six(self):
        assert STATUSES == frozenset({
            "deterministic", "approved", "queued",
            "rejected_current_evidence", "rejected_entity_distinct", "superseded",
        })

    def test_only_deterministic_and_approved_publish(self):
        assert PUBLISHING_STATUSES == frozenset({"deterministic", "approved"})
        assert is_publishing({"status": "deterministic"})
        assert is_publishing({"status": "approved"})
        for s in ("queued", "rejected_current_evidence", "rejected_entity_distinct", "superseded"):
            assert not is_publishing({"status": s})


class TestFingerprintAndId:
    def test_fingerprint_stable_and_content_sensitive(self):
        a = _ref("org-x", "Acme Inc", ein="12-3456789")
        assert fingerprint(a) == fingerprint(dict(a))          # stable
        assert fingerprint(a) != fingerprint(_ref("org-x", "Acme LLC", ein="12-3456789"))  # label change
        assert fingerprint(a) != fingerprint(_ref("org-x", "Acme Inc"))                    # key change

    def test_snapshot_hash_combines_both_refs(self):
        s = _ref("org-a", "A"); t = _ref("org-b", "B")
        h = source_snapshot_hash(s, t)
        assert h == source_snapshot_hash(_ref("org-a", "A"), _ref("org-b", "B"))
        assert h != source_snapshot_hash(s, _ref("org-b", "B2"))

    def test_assertion_id_deterministic_and_drift_sensitive(self):
        h1 = source_snapshot_hash(_ref("org-a", "A"), _ref("org-b", "B"))
        h2 = source_snapshot_hash(_ref("org-a", "A2"), _ref("org-b", "B"))
        i1 = assertion_id("org-a", "org-b", "ein_exact", h1)
        assert i1 == assertion_id("org-a", "org-b", "ein_exact", h1)   # idempotent
        assert i1.startswith("assertion-")
        assert i1 != assertion_id("org-a", "org-b", "ein_exact", h2)   # drift → new id
        assert i1 != assertion_id("org-a", "org-b", "operator_approved_name", h1)  # basis matters


class TestMakeAssertion:
    def test_make_deterministic_assertion(self):
        s = _ref("org-a", "A", ein="12-3456789"); t = _ref("org-b", "B", ein="12-3456789")
        a = make_assertion(
            subject_ref="org-a", target_ref="org-b", status="deterministic",
            basis="ein_exact", subject=s, target=t,
            reviewer="system", decided_at="deterministic", policy_version="v1",
            evidence_refs=["record-1"],
        )
        assert a["status"] == "deterministic"
        assert a["basis"] == "ein_exact"
        assert a["id"].startswith("assertion-")
        assert a["subject_fingerprint"] == fingerprint(s)
        assert a["source_snapshot_hash"] == source_snapshot_hash(s, t)
        assert a["legacy_projection"] is False
        assert a["supersedes"] is None and a["superseded_by"] is None
        assert is_publishing(a)

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError, match="status"):
            make_assertion(subject_ref="a", target_ref="b", status="nope",
                           basis="x", subject=_ref("a", "A"), target=_ref("b", "B"),
                           reviewer="r", decided_at="d", policy_version="v1")

    def test_approved_carries_reviewed_raw_variants(self):
        a = make_assertion(
            subject_ref="grp", target_ref="org-z", status="approved",
            basis="operator_approved_name", subject=_ref("grp", "Z"), target=_ref("org-z", "Z"),
            reviewer="stuart@eastpeak.cc", decided_at="2026-06-21", policy_version="v1",
            reviewed_raw_variants=["Z CO", "Z COMPANY"],
        )
        assert a["reviewed_raw_variants"] == ["Z CO", "Z COMPANY"]
        assert a["reviewer"] == "stuart@eastpeak.cc"

    def test_policy_applied_assertion_carries_policy_and_snapshot_hashes(self):
        a = make_assertion(
            subject_ref="org-bmf-ein-1", target_ref="org-vendor", status="approved",
            basis="operator_approved_ein", subject=_ref("org-bmf-ein-1", "Anchor", ein="1"),
            target=_ref("org-vendor", "Vendor"),
            reviewer="research-fleet-v1/policy-stuart-2026-07-01",
            decided_at="2026-07-03T20:00:00Z",
            policy_version="research-fleet-v1/policy-stuart-2026-07-01",
            policy_hash="h-policy",
            eligibility_snapshot_hash="sha256:snapshot",
        )
        assert a["policy_hash"] == "h-policy"
        assert a["eligibility_snapshot_hash"] == "sha256:snapshot"


class TestReadWriteRoundTrip:
    def test_write_then_read_sorted_deterministic(self, tmp_path):
        s = _ref("org-a", "A"); t = _ref("org-b", "B")
        a1 = make_assertion(subject_ref="org-a", target_ref="org-b", status="approved",
                            basis="operator_approved_name", subject=s, target=t,
                            reviewer="r", decided_at="2026-06-21", policy_version="v1")
        a2 = make_assertion(subject_ref="org-c", target_ref="org-d", status="queued",
                            basis="name_signal", subject=_ref("org-c", "C"), target=_ref("org-d", "D"),
                            reviewer="r", decided_at="2026-06-21", policy_version="v1")
        p = tmp_path / "assertions.jsonl"
        write_assertions([a2, a1], p)             # unsorted in
        back = read_assertions(p)
        assert [x["id"] for x in back] == sorted(x["id"] for x in (a1, a2))  # sorted on disk
        # byte-identical second write (determinism)
        p2 = tmp_path / "again.jsonl"
        write_assertions([a1, a2], p2)
        assert p.read_bytes() == p2.read_bytes()


class TestSupersede:
    def test_supersede_links_old_and_new(self):
        s = _ref("org-a", "A"); t = _ref("org-b", "B")
        old = make_assertion(subject_ref="org-a", target_ref="org-b", status="approved",
                            basis="operator_approved_name", subject=s, target=t,
                            reviewer="r", decided_at="2026-06-21", policy_version="v1")
        new = supersede(old, new_status="queued", basis="alias_expansion",
                        reviewer="r", decided_at="2026-06-22", policy_version="v1")
        assert new["supersedes"] == old["id"]
        assert new["status"] == "queued"
        assert new["subject_ref"] == old["subject_ref"]
        # the returned superseded copy of old points forward
        sup_old = supersede.last_superseded  # type: ignore[attr-defined]
        assert sup_old["status"] == "superseded"
        assert sup_old["superseded_by"] == new["id"]


class TestRequeueMatrix:
    """Predeclared 6 — the status × trigger re-queue matrix, row by row."""

    APPROVED_ALL = ("one_sided_new_key", "hard_key_conflict",
                    "dup_target_merge", "fingerprint_drift", "review_after_elapsed")

    def test_approved_requeues_on_every_trigger(self):
        for trig in self.APPROVED_ALL:
            assert should_requeue("approved", trig) is True

    def test_rejected_current_evidence_requeues_on_every_trigger(self):
        for trig in self.APPROVED_ALL:
            assert should_requeue("rejected_current_evidence", trig) is True

    def test_rejected_entity_distinct_reopens_only_on_hard_key_conflict(self):
        assert should_requeue("rejected_entity_distinct", "hard_key_conflict") is True
        for trig in ("one_sided_new_key", "dup_target_merge",
                     "fingerprint_drift", "review_after_elapsed"):
            assert should_requeue("rejected_entity_distinct", trig) is False

    def test_unknown_trigger_or_status_raises(self):
        with pytest.raises(ValueError):
            should_requeue("approved", "made_up_trigger")
        with pytest.raises(ValueError):
            should_requeue("made_up_status", "hard_key_conflict")
