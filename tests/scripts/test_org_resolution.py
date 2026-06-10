"""Tests for scripts/org_resolution.py — shared cross-source resolver (M2c unit 1).

Extraction of M2b's `propose_org_resolutions` out of `ingest_990.py`,
generalized to `identity_keys: tuple[str, ...] = ("ein",)` so M2c can match
USASpending recipients on UEI. Decision 6 rules pinned here:

- Per-key normalizers — keys are NOT interchangeable through one normalizer.
  A UEI is 12-char alphanumeric WITH letters; the EIN normalizer (digits
  only) would strip every letter and manufacture false merges.
- Match rule — per (new, existing) pair, the FIRST key in tuple order that
  is exactly equal under its normalizer (both sides present) is the match.
- Conflict rule — per new org, collect all key-exact matches FIRST; matches
  targeting >= 2 distinct existing ids emit ZERO SAME_AS and queue each pair
  (contradictory deterministic identity is a human call, never a silent
  double-merge).
- Everything judged (name signals) stays a sidecar candidate — the M2b name
  battery keeps running unchanged through the `ingest_990` re-export; this
  file smoke-tests the shared module directly.

UEI values are real rows from tests/fixtures/usaspending/ (see SOURCES.md).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from org_resolution import (  # noqa: E402
    KEY_NORMALIZERS,
    propose_org_resolutions,
)

# Real UEI — COMMUNITY ACTION MARIN, spending-by-award-grants-p1.json.
REAL_UEI = "JZ9FLAVMPEB9"


def usasp_org(org_id: str, name: str, **keys) -> dict:
    """M2c-shaped resolver input: {id, display_label, <keys>, evidence...}."""
    return {
        "id": org_id,
        "display_label": name,
        "evidence_record_ids": [f"record-usasp-{org_id.split('-')[-1]}"],
        **keys,
    }


# ---------------------------------------------------------------------------
# Per-key normalizers — the M2c blocker class (alpha UEI must survive)
# ---------------------------------------------------------------------------


def test_per_key_normalizer_preserves_alpha_uei():
    # Real alphanumeric UEI: uppercase + strip non-alphanumerics, never digits-only.
    assert KEY_NORMALIZERS["uei"]("jz9flavmpeb9") == REAL_UEI
    assert KEY_NORMALIZERS["uei"](" jz9-flavmpeb9 ") == REAL_UEI
    assert KEY_NORMALIZERS["uei"](REAL_UEI) == REAL_UEI
    # Absent/empty → None (never "").
    assert KEY_NORMALIZERS["uei"](None) is None
    assert KEY_NORMALIZERS["uei"]("") is None
    assert KEY_NORMALIZERS["uei"]("---") is None


def test_ein_normalizer_would_destroy_a_uei():
    # The rationale for per-key normalizers: digits-only normalization
    # reduces this real UEI to "99" — keys must never share a normalizer.
    assert KEY_NORMALIZERS["ein"](REAL_UEI) == "99"
    assert KEY_NORMALIZERS["ein"]("94-3007979") == "943007979"


# ---------------------------------------------------------------------------
# Deterministic auto-SAME_AS — uei key positive case (real UEI)
# ---------------------------------------------------------------------------


def test_uei_exact_match_is_auto_same_as():
    # POSITIVE case: existing side carries the UEI lowercased — per-key
    # normalization must still match, basis names the matched key.
    new = usasp_org(f"org-usasp-uei-{REAL_UEI}", "COMMUNITY ACTION MARIN", uei=REAL_UEI)
    existing = [
        {
            "id": "org-community-action-marin",
            "display_label": "Community Action Marin",
            "uei": "jz9flavmpeb9",
        }
    ]
    same_as, candidates = propose_org_resolutions(
        [new], existing, identity_keys=("ein", "uei")
    )
    assert same_as == [
        {
            "source_id": f"org-usasp-uei-{REAL_UEI}",
            "target_id": "org-community-action-marin",
            "relationship_type": "SAME_AS",
            "properties": {"basis": "uei_exact"},
        }
    ]
    # Deterministic join — nothing queued (the exact-name pair is settled).
    assert candidates == []


def test_default_identity_keys_is_ein_only():
    # M2b call sites pass no identity_keys — a uei-only match must NOT merge
    # under the default ("ein",). Names dissimilar → nothing at all.
    new = usasp_org(f"org-usasp-uei-{REAL_UEI}", "Community Action Marin", uei=REAL_UEI)
    existing = [
        {"id": "org-x", "display_label": "Golden Gate Bridge District", "uei": REAL_UEI}
    ]
    same_as, candidates = propose_org_resolutions([new], existing)
    assert same_as == []
    assert candidates == []


# ---------------------------------------------------------------------------
# Multi-key tuple order — FIRST matching key wins the basis
# ---------------------------------------------------------------------------


def test_multi_key_tuple_order_first_match_wins():
    new = usasp_org(
        "org-990-ein-943007979",
        "Marin Community Foundation",
        ein="94-3007979",
        uei=REAL_UEI,
    )
    existing = [
        {
            "id": "org-marin-community-foundation",
            "display_label": "Marin Community Foundation",
            "ein": "943007979",
            "uei": REAL_UEI,
        }
    ]
    same_as_ein_first, _ = propose_org_resolutions(
        [new], existing, identity_keys=("ein", "uei")
    )
    assert len(same_as_ein_first) == 1
    assert same_as_ein_first[0]["properties"] == {"basis": "ein_exact"}

    same_as_uei_first, _ = propose_org_resolutions(
        [new], existing, identity_keys=("uei", "ein")
    )
    assert len(same_as_uei_first) == 1
    assert same_as_uei_first[0]["properties"] == {"basis": "uei_exact"}


# ---------------------------------------------------------------------------
# Conflict rule — >= 2 distinct targets: ZERO SAME_AS, queue every pair
# ---------------------------------------------------------------------------


def test_identity_conflict_two_targets_zero_same_as():
    # ein matches existing A, uei matches existing B — contradictory
    # deterministic identity is queued for a human, never double-merged.
    new = usasp_org(
        "org-usasp-uei-K9BPKJN51NB1",
        "Marin Community Clinic",
        ein="94-1234567",
        uei="K9BPKJN51NB1",
    )
    existing = [
        {"id": "org-a", "display_label": "Org A", "ein": "941234567"},
        {"id": "org-b", "display_label": "Org B", "uei": "k9bpkjn51nb1"},
    ]
    same_as, candidates = propose_org_resolutions(
        [new], existing, identity_keys=("ein", "uei")
    )
    assert same_as == []
    assert candidates == [
        {
            "subject_ref": "org-usasp-uei-K9BPKJN51NB1",
            "candidate_ref": "org-a",
            "signals": ["ein_exact", "identity_conflict"],
            "confidence": 0.95,
            "status": "queued",
            "evidence_record_ids": ["record-usasp-K9BPKJN51NB1"],
        },
        {
            "subject_ref": "org-usasp-uei-K9BPKJN51NB1",
            "candidate_ref": "org-b",
            "signals": ["uei_exact", "identity_conflict"],
            "confidence": 0.95,
            "status": "queued",
            "evidence_record_ids": ["record-usasp-K9BPKJN51NB1"],
        },
    ]


def test_matches_on_one_target_via_both_keys_is_one_same_as():
    # Both keys agree on the SAME existing id → ONE SAME_AS (first key's
    # basis), no conflict, nothing queued.
    new = usasp_org(
        "org-990-ein-943007979",
        "Marin Community Foundation",
        ein="943007979",
        uei=REAL_UEI,
    )
    existing = [
        {
            "id": "org-marin-community-foundation",
            "display_label": "Marin Community Foundation",
            "ein": "94-3007979",
            "uei": REAL_UEI,
        }
    ]
    same_as, candidates = propose_org_resolutions(
        [new], existing, identity_keys=("ein", "uei")
    )
    assert len(same_as) == 1
    assert same_as[0]["properties"] == {"basis": "ein_exact"}
    assert candidates == []


# ---------------------------------------------------------------------------
# Fail-loud — unregistered identity key
# ---------------------------------------------------------------------------


def test_unregistered_identity_key_fails_loud():
    with pytest.raises(ValueError, match="cage"):
        propose_org_resolutions([], [], identity_keys=("ein", "cage"))


# ---------------------------------------------------------------------------
# Name signals — regression smoke on the shared module (full battery stays
# in test_ingest_990_resolver.py via the re-export)
# ---------------------------------------------------------------------------


def test_name_signals_unchanged_in_shared_module():
    new = usasp_org("org-usasp-rid-abc", "Marin Agricultural Land Trust")
    existing = [
        {"id": "org-malt", "display_label": "Marin Agricultural Land Trust, Inc."}
    ]
    same_as, candidates = propose_org_resolutions([new], existing)
    assert same_as == []
    assert len(candidates) == 1
    assert candidates[0]["signals"] == ["normalized_name_exact"]
    assert candidates[0]["confidence"] == 0.9
    assert candidates[0]["status"] == "queued"


def test_key_disagreement_does_not_suppress_name_candidacy():
    # Different EINs are NOT a match, but the exact-name signal still queues
    # (Decision 6: a key disagreement never suppresses name candidacy).
    new = usasp_org(
        "org-990-ein-943007979", "Marin Community Foundation", ein="943007979"
    )
    existing = [
        {
            "id": "org-marin-community-foundation",
            "display_label": "Marin Community Foundation",
            "ein": "111111111",
        }
    ]
    same_as, candidates = propose_org_resolutions([new], existing)
    assert same_as == []
    assert len(candidates) == 1
    assert candidates[0]["signals"] == ["normalized_name_exact"]


def test_below_threshold_similarity_produces_nothing():
    new = usasp_org("org-usasp-rid-xyz", "Marin Community Foundation")
    existing = [
        {"id": "org-sausalito-foundation", "display_label": "Sausalito Foundation"}
    ]
    same_as, candidates = propose_org_resolutions([new], existing)
    assert same_as == []
    assert candidates == []
