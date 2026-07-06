"""R3a lane framework parity tests.

The three shipped attach builders are the source of truth for this tranche:
pin their exact assertion/SAME_AS payloads first, then require the generic
builder to reproduce them byte-for-byte through registry metadata.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import identity_key_registry as keys  # noqa: E402
from enrich_county_vendor_eins import build_ein_attach  # noqa: E402
from enrich_county_vendor_sos import build_sos_attach  # noqa: E402
from enrich_fppc_keys import build_committee_attach  # noqa: E402

REVIEWER = "stuart@eastpeak.cc"
DECIDED_AT = "2026-07-06T12:00:00Z"
POLICY_VERSION = "policy-v1"
POLICY_HASH = "sha256:policy"
ELIGIBILITY_HASH = "sha256:eligibility"

EIN_CANDIDATE = {
    "subject_ref": "org-bmf-ein-844738834",
    "candidate_ref": "org-marincontract-recipient-rise-scholars",
    "evidence_record_ids": ["record-bmf-844738834"],
    "ein": "844738834",
}
EIN_VENDOR = {
    "id": "org-marincontract-recipient-rise-scholars",
    "display_label": "RISE SCHOLARS INC",
}

SOS_CANDIDATE = {
    "subject_ref": "org-casos-1234567",
    "candidate_ref": "org-marincontract-recipient-ghilotti",
    "evidence_record_ids": ["record-casos-1234567"],
    "sos_ref": {"sos_id": "1234567", "display_label": "Ghilotti Construction Inc"},
}
SOS_VENDOR = {
    "id": "org-marincontract-recipient-ghilotti",
    "display_label": "Ghilotti Construction",
}

COMMITTEE_CANDIDATE = {
    "subject_ref": "org-fppc-1439160",
    "candidate_ref": "org-bonta-for-attorney-general-2022",
    "committee_id": "1439160",
    "evidence_record_ids": ["record-fppc-1439160"],
}
COMMITTEE_VENDOR = {
    "id": "org-bonta-for-attorney-general-2022",
    "display_label": "Bonta for Attorney General 2022",
}

EXPECTED_ATTACH = {
    "ein": (
        {
            "id": "assertion-3ada3a01e3c3e213",
            "subject_ref": "org-bmf-ein-844738834",
            "target_ref": "org-marincontract-recipient-rise-scholars",
            "status": "approved",
            "basis": "operator_approved_ein",
            "reviewer": REVIEWER,
            "decided_at": DECIDED_AT,
            "evidence_refs": ["record-bmf-844738834"],
            "subject_fingerprint": "19fe4cf6dd595fc19a9f0422fc33aa22b6fe5153",
            "target_fingerprint": "2b2a3d2553966c5b4f298766b8da46c2c4270264",
            "reviewed_raw_variants": [],
            "source_snapshot_hash": "5caab58ded1e4875836617c292f9ba523210c548",
            "policy_version": POLICY_VERSION,
            "legacy_projection": False,
            "supersedes": None,
            "superseded_by": None,
            "review_after": None,
            "policy_hash": POLICY_HASH,
            "eligibility_snapshot_hash": ELIGIBILITY_HASH,
        },
        {
            "source_id": "org-bmf-ein-844738834",
            "target_id": "org-marincontract-recipient-rise-scholars",
            "relationship_type": "SAME_AS",
            "properties": {
                "basis": "operator_approved_ein",
                "assertion_id": "assertion-3ada3a01e3c3e213",
            },
        },
    ),
    "sos_id": (
        {
            "id": "assertion-f03495a6cc064e5f",
            "subject_ref": "org-casos-1234567",
            "target_ref": "org-marincontract-recipient-ghilotti",
            "status": "approved",
            "basis": "operator_approved_sos_id",
            "reviewer": REVIEWER,
            "decided_at": DECIDED_AT,
            "evidence_refs": ["record-casos-1234567"],
            "subject_fingerprint": "cb54ff027986d7dd682ccf8c322408d3b1ad32d8",
            "target_fingerprint": "57fc7c1926c61b5135e64bc69a97a13b69e05a9a",
            "reviewed_raw_variants": [],
            "source_snapshot_hash": "14d56ce890a17a728f22d62ba022d0e77cc02fbd",
            "policy_version": POLICY_VERSION,
            "legacy_projection": False,
            "supersedes": None,
            "superseded_by": None,
            "review_after": None,
            "policy_hash": POLICY_HASH,
            "eligibility_snapshot_hash": ELIGIBILITY_HASH,
        },
        {
            "source_id": "org-casos-1234567",
            "target_id": "org-marincontract-recipient-ghilotti",
            "relationship_type": "SAME_AS",
            "properties": {
                "basis": "operator_approved_sos_id",
                "assertion_id": "assertion-f03495a6cc064e5f",
            },
        },
    ),
    "committee_id": (
        {
            "id": "assertion-b94c1cd89f42e25c",
            "subject_ref": "org-fppc-1439160",
            "target_ref": "org-bonta-for-attorney-general-2022",
            "status": "approved",
            "basis": "operator_approved_committee_id",
            "reviewer": REVIEWER,
            "decided_at": DECIDED_AT,
            "evidence_refs": ["record-fppc-1439160"],
            "subject_fingerprint": "0dd33b829d432062f45ea53165ba01bfb5469784",
            "target_fingerprint": "f5e2a43106d32fd61ea1754aef68e15d0e826c80",
            "reviewed_raw_variants": [],
            "source_snapshot_hash": "2f71f1dd8e98232a4f2f87544da011f1deb694c1",
            "policy_version": POLICY_VERSION,
            "legacy_projection": False,
            "supersedes": None,
            "superseded_by": None,
            "review_after": None,
            "policy_hash": POLICY_HASH,
            "eligibility_snapshot_hash": ELIGIBILITY_HASH,
        },
        {
            "source_id": "org-fppc-1439160",
            "target_id": "org-bonta-for-attorney-general-2022",
            "relationship_type": "SAME_AS",
            "properties": {
                "basis": "operator_approved_committee_id",
                "assertion_id": "assertion-b94c1cd89f42e25c",
            },
        },
    ),
}


def _approval_kwargs() -> dict[str, str]:
    return {
        "reviewer": REVIEWER,
        "decided_at": DECIDED_AT,
        "policy_version": POLICY_VERSION,
        "policy_hash": POLICY_HASH,
        "eligibility_snapshot_hash": ELIGIBILITY_HASH,
    }


def test_existing_attach_builders_are_pinned_exactly():
    assert build_ein_attach(EIN_CANDIDATE, EIN_VENDOR, **_approval_kwargs()) == EXPECTED_ATTACH["ein"]
    assert build_sos_attach(SOS_CANDIDATE, SOS_VENDOR, **_approval_kwargs()) == EXPECTED_ATTACH["sos_id"]
    assert (
        build_committee_attach(COMMITTEE_CANDIDATE, COMMITTEE_VENDOR, **_approval_kwargs())
        == EXPECTED_ATTACH["committee_id"]
    )


def test_generic_build_attach_reproduces_pinned_lane_payloads():
    from identity_attach import build_attach  # noqa: E402

    assert (
        build_attach(keys.entry("ein", "self"), EIN_CANDIDATE, EIN_VENDOR, **_approval_kwargs())
        == EXPECTED_ATTACH["ein"]
    )
    assert (
        build_attach(keys.entry("sos_id", "self"), SOS_CANDIDATE, SOS_VENDOR, **_approval_kwargs())
        == EXPECTED_ATTACH["sos_id"]
    )
    assert (
        build_attach(
            keys.entry("committee_id", "self_committee"),
            COMMITTEE_CANDIDATE,
            COMMITTEE_VENDOR,
            **_approval_kwargs(),
        )
        == EXPECTED_ATTACH["committee_id"]
    )
