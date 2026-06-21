"""Tests for the legacy approved-file → ledger projection (Identity Control A, Unit 2).

The shipped flat approved-files (M2d / County / M4) all carry
`{subject_ref, candidate_ref, status:"approved"}` — no audit fields. Projecting
them into ledger assertions must NOT become an audit bypass (Predeclared 2):
fingerprints are DERIVED from the refs emitted THIS run (a stale ref BLOCKs);
audit fields are explicit (operator-supplied or named sentinels), never
inferred/clock; and a multi-raw-variant legacy County approval BLOCKS — it can
derive the group's variants but not which were REVIEWED.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from identity_legacy_projection import project_legacy_approved_row  # noqa: E402

REFS = {
    "economicinterest-x": {"id": "economicinterest-x", "display_label": "Grosvenor Properties Ltd."},
    "org-grosvenor": {"id": "org-grosvenor", "display_label": "Grosvenor Properties Ltd."},
    "org-funder": {"id": "org-funder", "display_label": "MALT"},
    "org-influence": {"id": "org-influence", "display_label": "MALT"},
    "marincontract-recipient-cam": {
        "id": "marincontract-recipient-cam", "display_label": "Community Action Marin",
        "raw_variants": ["COMMUNITY ACTION MARIN"],
    },
    "marincontract-recipient-multi": {
        "id": "marincontract-recipient-multi", "display_label": "Arborscience",
        "raw_variants": ["ARBORSCIENCE", "ARBORSCIENCE LLC"],
    },
    "org-cam": {"id": "org-cam", "display_label": "Community Action Marin"},
    "org-arbor": {"id": "org-arbor", "display_label": "Arborscience"},
}

KW = dict(legacy_reviewer="stuart@eastpeak.cc", legacy_decided_at="2026-06-14", policy_version="v1")


class TestEachLoaderShape:
    def test_m4_econ_interest_to_org(self):
        a = project_legacy_approved_row(
            {"subject_ref": "economicinterest-x", "candidate_ref": "org-grosvenor", "status": "approved"},
            loader="m4", refs_by_id=REFS, **KW)
        assert a["status"] == "approved" and a["legacy_projection"] is True
        assert a["basis"] == "operator_approved_name"
        assert a["subject_ref"] == "economicinterest-x" and a["target_ref"] == "org-grosvenor"
        assert a["subject_fingerprint"] and a["target_fingerprint"]   # derived from refs
        assert a["reviewer"] == "stuart@eastpeak.cc" and a["decided_at"] == "2026-06-14"

    def test_m2d_funder_to_influence(self):
        a = project_legacy_approved_row(
            {"subject_ref": "org-funder", "candidate_ref": "org-influence", "status": "approved"},
            loader="m2d", refs_by_id=REFS, **KW)
        assert a["subject_ref"] == "org-funder" and a["target_ref"] == "org-influence"
        assert a["legacy_projection"] is True

    def test_county_single_variant_projects_with_that_variant(self):
        a = project_legacy_approved_row(
            {"subject_ref": "marincontract-recipient-cam", "candidate_ref": "org-cam", "status": "approved"},
            loader="county", refs_by_id=REFS, **KW)
        assert a["reviewed_raw_variants"] == ["COMMUNITY ACTION MARIN"]


class TestAuditNotBypass:
    def test_non_approved_status_blocks(self):
        with pytest.raises(ValueError, match="status"):
            project_legacy_approved_row(
                {"subject_ref": "economicinterest-x", "candidate_ref": "org-grosvenor", "status": "queued"},
                loader="m4", refs_by_id=REFS, **KW)

    def test_stale_subject_ref_blocks(self):
        with pytest.raises(ValueError, match="subject_ref"):
            project_legacy_approved_row(
                {"subject_ref": "economicinterest-ghost", "candidate_ref": "org-grosvenor", "status": "approved"},
                loader="m4", refs_by_id=REFS, **KW)

    def test_stale_candidate_ref_blocks(self):
        with pytest.raises(ValueError, match="candidate_ref"):
            project_legacy_approved_row(
                {"subject_ref": "economicinterest-x", "candidate_ref": "org-ghost", "status": "approved"},
                loader="m4", refs_by_id=REFS, **KW)

    def test_multi_raw_county_approval_blocks(self):
        # The blocker: the current group has 2 raw variants; the flat legacy row
        # carries no reviewed variants → cannot know which were reviewed → BLOCK.
        with pytest.raises(ValueError, match="multi-raw|reviewed"):
            project_legacy_approved_row(
                {"subject_ref": "marincontract-recipient-multi", "candidate_ref": "org-arbor", "status": "approved"},
                loader="county", refs_by_id=REFS, **KW)

    def test_multi_raw_county_with_explicit_variants_projects(self):
        a = project_legacy_approved_row(
            {"subject_ref": "marincontract-recipient-multi", "candidate_ref": "org-arbor",
             "status": "approved", "reviewed_raw_variants": ["ARBORSCIENCE"]},
            loader="county", refs_by_id=REFS, **KW)
        assert a["reviewed_raw_variants"] == ["ARBORSCIENCE"]

    def test_missing_audit_fields_fall_back_to_named_sentinels(self):
        a = project_legacy_approved_row(
            {"subject_ref": "economicinterest-x", "candidate_ref": "org-grosvenor", "status": "approved"},
            loader="m4", refs_by_id=REFS,
            legacy_reviewer=None, legacy_decided_at=None, policy_version="v1")
        assert a["reviewer"] == "unknown_legacy"
        assert a["decided_at"] == "legacy_unknown"     # never a clock, never invented
