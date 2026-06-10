"""Tests for scripts/ingest_990.py — resolver unit (M2b).

`propose_org_resolutions(new_orgs, existing_orgs)` — pure functions, no graph
access; `existing_orgs` is an injected fixture list (the operator later feeds
a real export). Decision 6: deterministic auto-SAME_AS on exact normalized-EIN
equality ONLY; everything else is bounded stdlib-only name signals that land
in §4.3-shaped ResolutionCandidate dicts (JSONL sidecar, never nodes/edges).
The negative tests are the point: name similarity alone never merges.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from ingest_990 import (  # noqa: E402
    build_org_node,
    parse_return_file,
    propose_org_resolutions,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "990"
MCF_2022 = FIXTURES / "202421369349304932.xml"
MCF_2023 = FIXTURES / "202541349349313719.xml"
MALT_2022 = FIXTURES / "202421309349304522.xml"


def org_ref(path: Path) -> dict:
    """New-org resolver input from a REAL fixture return's built org node."""
    parsed = parse_return_file(path)
    node = build_org_node(parsed)
    return {
        "id": node["id"],
        "display_label": node["display_label"],
        "ein": node["properties"]["ein"],
        "evidence_record_ids": [
            f"record-990-{parsed['ein']}-{parsed['tax_year']}"
        ],
    }


# Real-shaped existing-org list — today's graph truth carries NO ein fields.
EXISTING_NO_EIN = [
    {"id": "org-county-of-marin", "display_label": "County of Marin"},
    {"id": "org-city-of-novato", "display_label": "City of Novato"},
    {"id": "org-marin-community-foundation", "display_label": "Marin Community Foundation"},
    {"id": "org-golden-gate-bridge-district", "display_label": "Golden Gate Bridge District"},
]


# ---------------------------------------------------------------------------
# Deterministic auto-SAME_AS — exact normalized-EIN equality ONLY
# ---------------------------------------------------------------------------


def test_exact_ein_match_is_auto_same_as():
    # POSITIVE case (required): the existing org carries a hyphenated EIN —
    # normalization (digits only) must still match.
    existing = [
        {
            "id": "org-marin-community-foundation",
            "display_label": "Marin Community Foundation",
            "ein": "94-3007979",
        }
    ]
    same_as, candidates = propose_org_resolutions([org_ref(MCF_2022)], existing)
    assert same_as == [
        {
            "source_id": "org-990-ein-943007979",
            "target_id": "org-marin-community-foundation",
            "relationship_type": "SAME_AS",
            "properties": {"basis": "ein_exact"},
        }
    ]
    # The join is deterministic — nothing queued for review.
    assert candidates == []


def test_ein_match_wins_regardless_of_name():
    # EIN equality alone is sufficient — display label disagreement is fine
    # (legal renames happen; the EIN is the identity).
    existing = [
        {
            "id": "org-foundation-of-marin",
            "display_label": "The Foundation of Marin",
            "ein": "943007979",
        }
    ]
    same_as, candidates = propose_org_resolutions([org_ref(MCF_2022)], existing)
    assert len(same_as) == 1
    assert same_as[0]["target_id"] == "org-foundation-of-marin"
    assert candidates == []


def test_no_ein_on_existing_side_never_auto_merges():
    # Same display label, but the existing org has no ein → never SAME_AS.
    same_as, candidates = propose_org_resolutions(
        [org_ref(MCF_2022)], EXISTING_NO_EIN
    )
    assert same_as == []
    # ...the exact-name match lands in the review queue instead.
    assert len(candidates) == 1


def test_different_eins_are_not_a_match():
    existing = [
        {
            "id": "org-other-foundation",
            "display_label": "Other Foundation",
            "ein": "111111111",
        }
    ]
    same_as, candidates = propose_org_resolutions([org_ref(MCF_2022)], existing)
    assert same_as == []
    assert candidates == []  # name isn't similar either


# ---------------------------------------------------------------------------
# ResolutionCandidate — §4.3 shape, bounded stdlib-only signals
# ---------------------------------------------------------------------------


def test_exact_normalized_name_candidate_shape():
    same_as, candidates = propose_org_resolutions(
        [org_ref(MCF_2022)], EXISTING_NO_EIN
    )
    assert same_as == []
    assert candidates == [
        {
            "subject_ref": "org-990-ein-943007979",
            "candidate_ref": "org-marin-community-foundation",
            "signals": ["normalized_name_exact"],
            "confidence": 0.9,
            "status": "queued",
            "evidence_record_ids": ["record-990-943007979-2022"],
        }
    ]


def test_trailing_corporate_suffix_strips_to_exact_match():
    existing = [
        {
            "id": "org-malt",
            "display_label": "Marin Agricultural Land Trust, Inc.",
        }
    ]
    _, candidates = propose_org_resolutions([org_ref(MALT_2022)], existing)
    assert len(candidates) == 1
    assert candidates[0]["signals"] == ["normalized_name_exact"]
    assert candidates[0]["confidence"] == 0.9


def test_similarity_at_or_above_085_is_a_candidate():
    # SequenceMatcher("marin community foundation", "marin community fund")
    # = 0.869565… → signal name_similarity:0.87, confidence 0.87.
    existing = [
        {"id": "org-marin-community-fund", "display_label": "Marin Community Fund"}
    ]
    same_as, candidates = propose_org_resolutions([org_ref(MCF_2022)], existing)
    assert same_as == []
    assert candidates == [
        {
            "subject_ref": "org-990-ein-943007979",
            "candidate_ref": "org-marin-community-fund",
            "signals": ["name_similarity:0.87"],
            "confidence": 0.87,
            "status": "queued",
            "evidence_record_ids": ["record-990-943007979-2022"],
        }
    ]


def test_similarity_below_threshold_produces_nothing():
    # ratio("marin community foundation", "sausalito foundation") = 0.65.
    existing = [
        {"id": "org-sausalito-foundation", "display_label": "Sausalito Foundation"}
    ]
    same_as, candidates = propose_org_resolutions([org_ref(MCF_2022)], existing)
    assert same_as == []
    assert candidates == []


def test_candidates_are_never_edges_or_nodes():
    # A candidate dict must not carry the graph envelopes' identifying keys.
    _, candidates = propose_org_resolutions([org_ref(MCF_2022)], EXISTING_NO_EIN)
    for candidate in candidates:
        assert "relationship_type" not in candidate
        assert "source_id" not in candidate
        assert "labels" not in candidate
        assert "node_type" not in candidate
        assert candidate["status"] == "queued"


# ---------------------------------------------------------------------------
# End-to-end — real fixtures vs the no-ein existing list: ZERO SAME_AS
# ---------------------------------------------------------------------------


def test_e2e_no_ein_existing_list_yields_zero_same_as():
    new_orgs = [org_ref(MCF_2022), org_ref(MCF_2023), org_ref(MALT_2022)]
    same_as, candidates = propose_org_resolutions(new_orgs, EXISTING_NO_EIN)
    assert same_as == []
    # Everything that matched by name is queued for HUMAN review, not merged.
    assert all(c["status"] == "queued" for c in candidates)
    # Both MCF years propose the same join (subject/candidate pair recurs).
    mcf_pairs = {
        (c["subject_ref"], c["candidate_ref"]) for c in candidates
    }
    assert ("org-990-ein-943007979", "org-marin-community-foundation") in mcf_pairs
