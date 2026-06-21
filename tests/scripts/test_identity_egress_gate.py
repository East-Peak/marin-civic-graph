"""Tests for the ledger-aware egress gate (Identity Control A, Unit 4).

The wrapper layer that sits between the resolver/ingestors and the public graph.
It NEVER edits the resolver — it gates the resolver's SAME_AS output through the
ledger: an allowed self-identity merge becomes a `deterministic` assertion and
the edge is stamped with its id; a relationship-semantics "merge" (fiscal
sponsor / parent UEI / PAC / DBA / project) is DEMOTED to a queued relationship
candidate (no SAME_AS); an endpoint missing the class schema fails closed.

`join_citation` is the both-ways gate every approved egress path uses: a
publishing assertion yields its id to cite; a non-publishing one yields None
(no join).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from identity_egress_gate import gate_same_as_edges, join_citation  # noqa: E402
from identity_ledger import make_assertion  # noqa: E402


def _ein_edge(s, t):
    return {"source_id": s, "target_id": t, "relationship_type": "SAME_AS",
            "properties": {"basis": "ein_exact"}}


def _ref(id, label, semantics="self", cls="organization", system="form_990", **k):
    return {"id": id, "display_label": label, "key_semantics": semantics,
            "entity_class": cls, "source_system": system, **k}


REFS = {
    "org-a": _ref("org-a", "Acme Foundation", ein="12-3456789"),
    "org-b": _ref("org-b", "Acme Foundation", ein="12-3456789"),
    "org-sponsor": _ref("org-sponsor", "Tides Center", semantics="fiscal_sponsor", ein="94-0000001"),
    "org-project": _ref("org-project", "Sponsored Project X", semantics="self", ein="94-0000001"),
    "org-pac": _ref("org-pac", "Builders BPAC", semantics="self", cls="committee", committee_id="C1"),
    "org-assoc": _ref("org-assoc", "Builders Association", semantics="self", cls="organization", committee_id="C1"),
}


class TestGateSameAsEdges:
    def test_self_identity_merge_yields_deterministic_assertion_and_stamped_edge(self):
        gated, assertions, demoted = gate_same_as_edges(
            [_ein_edge("org-a", "org-b")], REFS, policy_version="v1")
        assert len(gated) == 1 and len(assertions) == 1 and demoted == []
        assert assertions[0]["status"] == "deterministic"
        assert assertions[0]["basis"] == "ein_exact"
        # the published edge cites the assertion id
        assert gated[0]["properties"]["assertion_id"] == assertions[0]["id"]
        # the resolver's own basis is preserved
        assert gated[0]["properties"]["basis"] == "ein_exact"

    def test_fiscal_sponsor_merge_is_demoted_never_same_as(self):
        # org-sponsor (fiscal_sponsor) shares an EIN with org-project — that is a
        # RELATIONSHIP, not identity. No SAME_AS; a queued relationship candidate.
        gated, assertions, demoted = gate_same_as_edges(
            [_ein_edge("org-sponsor", "org-project")], REFS, policy_version="v1")
        assert gated == [] and assertions == []
        assert len(demoted) == 1
        assert demoted[0]["status"] == "queued"
        assert demoted[0]["basis"] == "relationship_candidate"

    def test_org_to_committee_class_mismatch_demoted(self):
        # an org and a PAC sharing a committee id must never SAME_AS-merge.
        gated, assertions, demoted = gate_same_as_edges(
            [_ein_edge("org-assoc", "org-pac")], REFS, policy_version="v1")
        assert gated == [] and len(demoted) == 1

    def test_endpoint_missing_class_schema_fails_closed(self):
        bare = {"org-x": {"id": "org-x", "display_label": "X"},  # no class schema
                "org-y": _ref("org-y", "Y", ein="99")}
        with pytest.raises(ValueError, match="class schema|fail closed"):
            gate_same_as_edges([_ein_edge("org-x", "org-y")], bare, policy_version="v1")

    def test_endpoint_not_in_refs_fails_closed(self):
        with pytest.raises(ValueError, match="not in|fail closed"):
            gate_same_as_edges([_ein_edge("org-a", "org-ghost")], REFS, policy_version="v1")

    def test_empty_input_is_a_noop(self):
        # the real Marin case: zero shared EINs → zero SAME_AS → clean no-op,
        # no refs needed (back-compat for the ingestors).
        assert gate_same_as_edges([], {}, policy_version="v1") == ([], [], [])


class TestJoinCitation:
    def test_publishing_assertion_yields_its_id(self):
        for status in ("deterministic", "approved"):
            a = make_assertion(subject_ref="a", target_ref="b", status=status,
                               basis="x", subject={"id": "a"}, target={"id": "b"},
                               reviewer="r", decided_at="d", policy_version="v1")
            assert join_citation(a) == a["id"]

    def test_non_publishing_assertion_yields_no_join(self):
        for status in ("queued", "rejected_current_evidence", "rejected_entity_distinct", "superseded"):
            a = make_assertion(subject_ref="a", target_ref="b", status=status,
                               basis="x", subject={"id": "a"}, target={"id": "b"},
                               reviewer="r", decided_at="d", policy_version="v1")
            assert join_citation(a) is None


# ---------------------------------------------------------------------------
# Per-path: ingestor SAME_AS routes through the gate (COMPLETION 3)
# ---------------------------------------------------------------------------
from identity_egress_gate import gate_ingestor_same_as  # noqa: E402


class TestIngestorSameAsPath:
    def test_990_self_identity_same_as_is_gated_and_cites_assertion(self):
        # a shared EIN between a new 990 org and an existing graph org → the
        # resolver emits a SAME_AS; the gate stamps it with a deterministic id.
        new = [{"id": "org-990-ein-123456789", "display_label": "Acme Foundation", "ein": "12-3456789"}]
        existing = [{"id": "org-acme", "display_label": "Acme Foundation", "ein": "12-3456789"}]
        raw = [{"source_id": "org-990-ein-123456789", "target_id": "org-acme",
                "relationship_type": "SAME_AS", "properties": {"basis": "ein_exact"}}]
        gated, assertions, demoted = gate_ingestor_same_as(raw, new, existing, source_system="form_990")
        assert len(gated) == 1 and len(assertions) == 1 and demoted == []
        assert gated[0]["properties"]["assertion_id"] == assertions[0]["id"]
        assert assertions[0]["status"] == "deterministic"

    def test_usaspending_self_identity_same_as_is_gated(self):
        new = [{"id": "org-usasp-uei-ABC", "display_label": "Vendor Co", "uei": "ABC123XYZ789"}]
        existing = [{"id": "org-vendor", "display_label": "Vendor Co", "uei": "ABC123XYZ789"}]
        raw = [{"source_id": "org-usasp-uei-ABC", "target_id": "org-vendor",
                "relationship_type": "SAME_AS", "properties": {"basis": "uei_exact"}}]
        gated, assertions, _ = gate_ingestor_same_as(raw, new, existing, source_system="usaspending")
        assert gated[0]["properties"]["assertion_id"] == assertions[0]["id"]

    def test_ingestor_fiscal_sponsor_ref_demotes_never_same_as(self):
        # if a ref is tagged as a fiscal sponsor, its shared EIN is a relationship,
        # not identity → demoted, no edge.
        new = [{"id": "org-sponsor", "display_label": "Tides", "ein": "94-1", "key_semantics": "fiscal_sponsor"}]
        existing = [{"id": "org-proj", "display_label": "Project", "ein": "94-1"}]
        raw = [{"source_id": "org-sponsor", "target_id": "org-proj",
                "relationship_type": "SAME_AS", "properties": {"basis": "ein_exact"}}]
        gated, assertions, demoted = gate_ingestor_same_as(raw, new, existing, source_system="form_990")
        assert gated == [] and assertions == [] and len(demoted) == 1

    def test_empty_same_as_noop_real_case(self):
        assert gate_ingestor_same_as([], [{"id": "o"}], [], source_system="form_990") == ([], [], [])
