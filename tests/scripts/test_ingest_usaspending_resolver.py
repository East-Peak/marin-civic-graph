"""Tests for scripts/ingest_usaspending.py — resolver wiring (M2c, Decision 6).

Recipient refs `{id, display_label, uei?, evidence_record_ids[]}` feed the
SHARED resolver (`org_resolution.propose_org_resolutions`) with
`identity_keys=("ein", "uei")`. Deterministic key merges ONLY: a USASpending
ref carries no EIN, so the single deterministic lane into the existing graph
is uei-exact — today's real export carries neither key, so the real-shaped
no-key e2e asserts ZERO SAME_AS. Everything judged (name signals) is a
queued ResolutionCandidate in the §4.3 sidecar shape — never a node, never
an edge (spec §4.4: enrichment-only until recipient resolution is reviewed).

`existing_orgs` lists are operator-injected run-time inputs (the M2b
`--existing-orgs` contract), NOT fixtures — entries here are shaped test
inputs with opaque ids; the positive lane uses the real CAM UEI from the
fixture rows.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from ingest_usaspending import (  # noqa: E402
    build_recipient_org_nodes,
    build_recipient_refs,
    parse_awards_file,
    resolve_recipient_orgs,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "usaspending"
GRANTS_P1 = FIXTURES / "spending-by-award-grants-p1.json"
GRANTS_P2 = FIXTURES / "spending-by-award-grants-p2.json"

# Real cross-page recipient: COMMUNITY ACTION MARIN — p1 row 0 + p2 row 1.
CAM_UEI = "JZ9FLAVMPEB9"
CAM_ORG_ID = f"org-usasp-uei-{CAM_UEI}"
CAM_RECORD_IDS = [
    "record-usasp-asst_non_09ch011669_075",
    "record-usasp-asst_non_09ch013338_075",
]

# The §4.3 ResolutionCandidate sidecar shape — and the envelope keys a
# candidate must NEVER carry (it is not a node and not an edge).
CANDIDATE_KEYS = {
    "subject_ref",
    "candidate_ref",
    "signals",
    "confidence",
    "status",
    "evidence_record_ids",
}
ENVELOPE_KEYS = {
    "id",
    "node_type",
    "labels",
    "display_label",
    "properties",
    "source_id",
    "target_id",
    "relationship_type",
}


def all_grant_awards() -> list[dict]:
    return parse_awards_file(GRANTS_P1) + parse_awards_file(GRANTS_P2)


def cam_awards() -> list[dict]:
    """The two REAL Community Action Marin rows (one per page)."""
    awards = [
        a
        for a in all_grant_awards()
        if a["recipient_id"] == "cf3072ee-ffc8-260e-4fc3-57dc5b893427-C"
    ]
    assert len(awards) == 2  # fixture ground truth
    return awards


def resolve(awards: list[dict], existing: list[dict]) -> tuple[list, list]:
    nodes, by_award = build_recipient_org_nodes(awards)
    return resolve_recipient_orgs(nodes, by_award, existing)


# ---------------------------------------------------------------------------
# Recipient refs — the Decision 6 shape {id, display_label, uei?, records[]}
# ---------------------------------------------------------------------------


def test_recipient_ref_shape_with_uei_and_sorted_evidence_records():
    nodes, by_award = build_recipient_org_nodes(cam_awards())
    assert build_recipient_refs(nodes, by_award) == [
        {
            "id": CAM_ORG_ID,
            "display_label": "Community Action Marin",
            "uei": CAM_UEI,
            "evidence_record_ids": CAM_RECORD_IDS,
        }
    ]


def test_recipient_ref_omits_uei_when_group_has_none():
    # Permitted mutation (a) on both REAL CAM rows → rid-fallback org; the
    # ref must OMIT the uei key (never carry uei: None into the resolver).
    first, second = (copy.deepcopy(a) for a in cam_awards())
    first["uei"] = None
    second["uei"] = None
    nodes, by_award = build_recipient_org_nodes([first, second])
    (ref,) = build_recipient_refs(nodes, by_award)
    assert "uei" not in ref
    assert ref["id"] == "org-usasp-rid-cf3072ee-ffc8-260e-4fc3-57dc5b893427-c"
    assert ref["evidence_record_ids"] == CAM_RECORD_IDS


def test_recipient_refs_are_sorted_by_org_id():
    nodes, by_award = build_recipient_org_nodes(all_grant_awards())
    ref_ids = [ref["id"] for ref in build_recipient_refs(nodes, by_award)]
    assert len(ref_ids) == 9
    assert ref_ids == sorted(ref_ids)


# ---------------------------------------------------------------------------
# Deterministic lane — uei-exact merges, conflicts queue (never double-merge)
# ---------------------------------------------------------------------------


def test_uei_exact_match_emits_one_same_as():
    # Existing side stores the uei lowercased — per-key normalization
    # (uppercase, alphanumerics only) must hold through the wiring.
    existing = [
        {
            "id": "org-existing-cam",
            "display_label": "Community Action Marin",
            "uei": CAM_UEI.lower(),
        }
    ]
    same_as, candidates = resolve(cam_awards(), existing)
    assert same_as == [
        {
            "source_id": CAM_ORG_ID,
            "target_id": "org-existing-cam",
            "relationship_type": "SAME_AS",
            "properties": {"basis": "uei_exact"},
        }
    ]
    assert candidates == []  # settled deterministically — nothing judged


def test_conflicting_uei_targets_queue_and_never_double_merge():
    # TWO existing orgs claim CAM's UEI → contradictory deterministic
    # identity is a human call: ZERO SAME_AS, each pair queued.
    existing = [
        {"id": "org-existing-a", "display_label": "Org A", "uei": CAM_UEI},
        {"id": "org-existing-b", "display_label": "Org B", "uei": CAM_UEI.lower()},
    ]
    same_as, candidates = resolve(cam_awards(), existing)
    assert same_as == []
    assert candidates == [
        {
            "subject_ref": CAM_ORG_ID,
            "candidate_ref": "org-existing-a",
            "signals": ["uei_exact", "identity_conflict"],
            "confidence": 0.95,
            "status": "queued",
            "evidence_record_ids": CAM_RECORD_IDS,
        },
        {
            "subject_ref": CAM_ORG_ID,
            "candidate_ref": "org-existing-b",
            "signals": ["uei_exact", "identity_conflict"],
            "confidence": 0.95,
            "status": "queued",
            "evidence_record_ids": CAM_RECORD_IDS,
        },
    ]


def test_ein_only_existing_org_never_merges_name_stays_sidecar():
    # USASpending refs carry NO ein, so an ein-only existing org can never
    # match deterministically — even with an identical name, the pair is a
    # queued candidate, never a SAME_AS (name similarity alone NEVER merges).
    existing = [
        {
            "id": "org-existing-cam",
            "display_label": "Community Action Marin",
            "ein": "94-0000000",
        }
    ]
    same_as, candidates = resolve(cam_awards(), existing)
    assert same_as == []
    assert candidates == [
        {
            "subject_ref": CAM_ORG_ID,
            "candidate_ref": "org-existing-cam",
            "signals": ["normalized_name_exact"],
            "confidence": 0.9,
            "status": "queued",
            "evidence_record_ids": CAM_RECORD_IDS,
        }
    ]


# ---------------------------------------------------------------------------
# Real-shaped e2e — today's export carries neither key → ZERO SAME_AS
# ---------------------------------------------------------------------------


def test_no_key_existing_list_e2e_yields_zero_same_as():
    # The real graph export today is `{id, display_label}` only — no ein, no
    # uei. All 20 real awards against it: ZERO SAME_AS (§4.4 enrichment-only
    # in practice); name evidence lands queued in the sidecar.
    existing = [
        {"id": "org-existing-cam", "display_label": "Community Action Marin"},
        {"id": "org-existing-county", "display_label": "County of Marin"},
    ]
    same_as, candidates = resolve(all_grant_awards(), existing)
    assert same_as == []
    assert all(c["status"] == "queued" for c in candidates)
    assert {
        "subject_ref": CAM_ORG_ID,
        "candidate_ref": "org-existing-cam",
        "signals": ["normalized_name_exact"],
        "confidence": 0.9,
        "status": "queued",
        "evidence_record_ids": CAM_RECORD_IDS,
    } in candidates


# ---------------------------------------------------------------------------
# Sidecar shape — §4.3 keys exactly, never node/edge envelopes
# ---------------------------------------------------------------------------


def test_candidates_are_sidecar_shaped_never_envelopes():
    existing = [
        {"id": "org-existing-a", "display_label": "Org A", "uei": CAM_UEI},
        {"id": "org-existing-b", "display_label": "Org B", "uei": CAM_UEI},
        {"id": "org-existing-cam", "display_label": "Community Action Marin"},
    ]
    same_as, candidates = resolve(all_grant_awards(), existing)
    assert candidates  # both lanes below exercised
    for candidate in candidates:
        assert set(candidate) == CANDIDATE_KEYS
        assert not set(candidate) & ENVELOPE_KEYS
