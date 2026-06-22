"""Tests for scripts/enrich_fppc_keys.py — Identity Enrichment Lane 3 (FPPC
committee_id). Unit 1: the strict committee_id normalizer + idempotent,
non-clobbering runtime registration into the shared resolver (org_resolution.py
stays byte-identical). Tests snapshot/restore KEY_NORMALIZERS so a lane
registration never leaks across tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from org_resolution import KEY_NORMALIZERS  # noqa: E402
from enrich_fppc_keys import (  # noqa: E402
    _election_year,
    _normalize_committee_id,
    filer_spine_refs,
    parse_filername,
    register_committee_id_normalizer,
)

_FILERNAME_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "fppc" / "filername_slice.tsv"
)


def _committee(node_id, name, filer_id, committee_type="CTL"):
    return {
        "id": node_id, "node_type": "Committee", "labels": ["Committee"],
        "display_label": name,
        "properties": {"name": name, "netfile_filer_id": filer_id,
                       "committee_type": committee_type},
    }


@pytest.fixture(autouse=True)
def _restore_key_normalizers():
    snapshot = dict(KEY_NORMALIZERS)
    try:
        yield
    finally:
        KEY_NORMALIZERS.clear()
        KEY_NORMALIZERS.update(snapshot)


# --------------------------------------------------------------------------
# _normalize_committee_id — strict numeric FPPC id (Predeclared 1, Codex r1/r2)
# --------------------------------------------------------------------------

def test_normalize_accepts_clean_numeric_ids():
    assert _normalize_committee_id("1352318") == "1352318"
    assert _normalize_committee_id(1419944) == "1419944"          # int
    assert _normalize_committee_id("  1392466  ") == "1392466"    # whitespace stripped
    assert _normalize_committee_id("123456789") == "123456789"    # 9 digits ok (CAL allows <=9)


def test_normalize_rejects_pending_unknown_empty_and_none():
    for bad in ("Pending", "PENDING", "Unknown", "", "   ", None):
        assert _normalize_committee_id(bad) is None


def test_normalize_rejects_overlength_and_alphanumeric_garbage():
    assert _normalize_committee_id("1234567890") is None   # 10 digits — overlength
    assert _normalize_committee_id("abc123") is None       # letters — not a clean id
    assert _normalize_committee_id("C1352318") is None     # SOS-style prefix is not an FPPC id
    assert _normalize_committee_id("1352318.0") is None    # float-ish garbage


# --------------------------------------------------------------------------
# register_committee_id_normalizer — idempotent, non-clobbering (Lane-2 pattern)
# --------------------------------------------------------------------------

def test_register_adds_committee_id_normalizer():
    KEY_NORMALIZERS.pop("committee_id", None)
    register_committee_id_normalizer()
    assert KEY_NORMALIZERS["committee_id"] is _normalize_committee_id


def test_register_is_idempotent():
    register_committee_id_normalizer()
    register_committee_id_normalizer()  # second call must not raise
    assert KEY_NORMALIZERS["committee_id"] is _normalize_committee_id


def test_register_refuses_to_clobber_a_foreign_registration():
    KEY_NORMALIZERS["committee_id"] = lambda v: "foreign"
    with pytest.raises(RuntimeError, match="committee_id"):
        register_committee_id_normalizer()


# --------------------------------------------------------------------------
# Unit 2 — filer-spine extractor (tier 1, from the on-disk campaign bundle)
# --------------------------------------------------------------------------

def test_election_year_single_token_else_none():
    assert _election_year("Committee to Elect Anna Pletcher District Attorney 2018") == "2018"
    assert _election_year("Stay Green, Keep SMART 2020 - Yes on I") == "2020"
    assert _election_year("Marin Association of Public Employees PAC") is None  # no year
    assert _election_year("Bonta for AG 2022 2026") is None  # ambiguous (2 distinct years)


def test_filer_spine_refs_keys_committees_skips_pending_and_non_committees():
    nodes = [
        _committee("committee-netfile-1392466",
                   "Committee to Elect Anna Pletcher District Attorney 2018", 1392466),
        _committee("committee-netfile-1352318",
                   "Marin Association of Public Employees PAC", 1352318, committee_type="GPC"),
        _committee("committee-netfile-Pending", "Brand New Committee", "Pending"),
        {"id": "org-some-org", "node_type": "Organization", "labels": ["Organization"],
         "display_label": "Some Org", "properties": {}},  # ignored
    ]
    refs = filer_spine_refs(nodes)
    by_id = {r["committee_id"]: r for r in refs}
    assert set(by_id) == {"1392466", "1352318"}  # Pending + non-committee dropped
    assert by_id["1392466"]["election_year"] == "2018"
    assert by_id["1392466"]["committee_type"] == "CTL"
    assert by_id["1352318"]["election_year"] is None
    assert by_id["1392466"]["display_label"].startswith("Committee to Elect Anna Pletcher")


# --------------------------------------------------------------------------
# Unit 3 — Cal-Access FILERNAME_CD parser (tier 2): CP1252, FILER_TYPE
# allowlist (+ negatives), preserve ALL aliases per FILER_ID.
# --------------------------------------------------------------------------

def test_parse_filername_cp1252_allowlist_and_aliases():
    refs = parse_filername(_FILERNAME_FIXTURE)
    by_id = {}
    for r in refs:
        by_id.setdefault(r["committee_id"], []).append(r)

    # lobbying + individual rows excluded (allowlist, not denylist)
    assert "9990001" not in by_id and "9990002" not in by_id
    # Bonta-2022 (1439160) and Bonta-2026 (1456428) are DISTINCT committee_ids
    assert "1439160" in by_id and "1456428" in by_id
    # all aliases preserved: FILER_ID 1439160 has TWO name rows -> two refs
    assert len(by_id["1439160"]) == 2
    names_2022 = {r["display_label"] for r in by_id["1439160"]}
    assert "BONTA FOR ATTORNEY GENERAL 2022" in names_2022
    assert "BONTA FOR CALIFORNIA ATTORNEY GENERAL 2022" in names_2022
    # election_year derived from the name token
    assert all(r["election_year"] == "2022" for r in by_id["1439160"])
    assert by_id["1456428"][0]["election_year"] == "2026"
    # CP1252 decoding: the accented committee name round-trips (not mojibake)
    assert "COMITÉ LATINO PARA MARIN 2024" in {r["display_label"] for r in refs}
    assert all(r["source"] == "cal_access" for r in refs)
