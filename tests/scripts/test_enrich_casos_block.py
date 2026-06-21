"""Tests for scripts/enrich_casos_keys.py — Lane 2 Unit 2: token-block + candidates.

The 9.44M-row file is streamed and reduced by a recall-oriented significant-token
pre-block; within each per-existing bucket, candidates are the UNION of two
queued-only paths (Codex r2 #1 — the resolver's 0.85 gate alone misses the real
cases):
  (a) the shared resolver (normalized-name-exact / difflib>=0.85), and
  (b) a `significant_token_overlap` path (>=2 shared significant tokens or subset),
      for the sub-0.85 cases ("Ghilotti Construction" 0.75, "Ghilotti Bros
      Contractors" 0.667).
Pinned against the REAL export labels + the staged Ghilotti/Miller/Cumming rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from org_resolution import KEY_NORMALIZERS  # noqa: E402
from enrich_casos_keys import (  # noqa: E402
    block_casos_against_existing,
    significant_tokens,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "identity_enrichment_casos"
FILINGS_SLICE = FIXTURES / "filings_slice.csv"


@pytest.fixture(autouse=True)
def _restore_key_normalizers():
    snapshot = dict(KEY_NORMALIZERS)
    try:
        yield
    finally:
        KEY_NORMALIZERS.clear()
        KEY_NORMALIZERS.update(snapshot)


# Real export labels (the for-profit vendor nodes this lane keys).
EXISTING = [
    {"id": "org-ghilotti-construction-company", "display_label": "Ghilotti Construction Company"},
    {"id": "org-ghilotti-construction", "display_label": "Ghilotti Construction"},
    {"id": "org-ghilotti-bros-contractors", "display_label": "Ghilotti Bros Contractors"},
    {"id": "org-miller-pacific-engineering-group", "display_label": "Miller Pacific Engineering Group"},
    {"id": "org-cummings-management-group-inc", "display_label": "Cummings Management Group, Inc"},
    {"id": "org-conflict-entity", "display_label": "Conflict Entity Alpha"},
]


def _lines():
    return FILINGS_SLICE.read_text().splitlines()


def _cands_for(result, existing_id):
    return [c for c in result["candidates"] if c["candidate_ref"] == existing_id]


def test_significant_tokens_drop_corporate_stopwords():
    assert significant_tokens("Ghilotti Construction Company") == {"ghilotti", "construction"}
    assert significant_tokens("Miller Pacific Engineering Group") == {"miller", "pacific", "engineering"}
    assert significant_tokens("Cummings Management Group, Inc") == {"cummings", "management"}


def test_resolver_path_surfaces_exact_and_high_similarity():
    result = block_casos_against_existing(_lines(), EXISTING)
    # exact normalized name (resolver, high signal)
    gcc = _cands_for(result, "org-ghilotti-construction-company")
    assert any(c["sos_id"] == "1819837" for c in gcc)
    # the right Miller Pacific (Novato 1628638) is an exact resolver match
    mp = _cands_for(result, "org-miller-pacific-engineering-group")
    mp_1628638 = [c for c in mp if c["sos_id"] == "1628638"]
    assert mp_1628638 and mp_1628638[0]["signal_strength"] >= 0.9
    # Cummings (typo variant) clears difflib 0.85 against Cumming Management Group
    cmg = _cands_for(result, "org-cummings-management-group-inc")
    assert any(c["sos_id"] == "2976512" for c in cmg)


def test_token_overlap_path_surfaces_sub_threshold_cases():
    """The cases the resolver's 0.85 gate misses must still surface via token
    overlap (queued, lower signal)."""
    result = block_casos_against_existing(_lines(), EXISTING)
    gc = _cands_for(result, "org-ghilotti-construction")
    gc_1819837 = [c for c in gc if c["sos_id"] == "1819837"]
    assert gc_1819837, "Ghilotti Construction must surface 1819837 via token overlap"
    assert "significant_token_overlap" in gc_1819837[0]["signals"]
    # Ghilotti Bros Contractors -> 0257045 (difflib 0.667, token overlap saves it)
    gbc = _cands_for(result, "org-ghilotti-bros-contractors")
    assert any(c["sos_id"] == "0257045" for c in gbc)


def test_miller_false_friend_ranks_below_the_novato_match():
    """1539723 (Stockton) may surface as a low-signal token-overlap candidate, but
    1628638 (Novato) outranks it."""
    result = block_casos_against_existing(_lines(), EXISTING)
    mp = _cands_for(result, "org-miller-pacific-engineering-group")
    by_num = {c["sos_id"]: c for c in mp}
    assert "1628638" in by_num
    if "1539723" in by_num:
        assert by_num["1628638"]["signal_strength"] > by_num["1539723"]["signal_strength"]


def test_all_candidates_queued_never_auto_merged():
    result = block_casos_against_existing(_lines(), EXISTING)
    assert result["candidates"]
    assert all(c["status"] == "queued" for c in result["candidates"])


def test_byte_identical_duplicate_collapses_in_bucket():
    result = block_casos_against_existing(_lines(), EXISTING)
    gcc = _cands_for(result, "org-ghilotti-construction-company")
    assert sum(1 for c in gcc if c["sos_id"] == "1819837") == 1


def test_same_number_conflict_is_withheld_and_recorded():
    result = block_casos_against_existing(_lines(), EXISTING)
    # 9990001 (CONFLICT ENTITY ALPHA/BETA) buckets to org-conflict-entity, conflicts, withheld
    assert all(c["sos_id"] != "9990001" for c in result["candidates"])
    assert any(c["sos_id"] == "9990001" and c["reason"] == "casos_row_conflict" for c in result["conflicts"])


def test_cap_limits_candidates_per_existing_and_records_it():
    result = block_casos_against_existing(_lines(), EXISTING, cap=1)
    for existing in EXISTING:
        assert len(_cands_for(result, existing["id"])) <= 1
    # at least one existing org had more than 1 candidate, so the cap fired
    assert result["capped"]
