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
import json  # noqa: E402

from enrich_fppc_keys import (  # noqa: E402
    FPPC_ANCHOR_PREFIX,
    _election_year,
    _normalize_committee_id,
    build_committee_attach,
    filer_spine_refs,
    merge_approved_assertions,
    parse_filername,
    register_committee_id_normalizer,
    resolve_committee_ids,
)
from identity_ledger import read_assertions, write_assertions  # noqa: E402
from enrich_fppc_keys import load_filer_spine, roi_preflight  # noqa: E402
from dedup_org_candidates import deterministic_dedup_assertions  # noqa: E402

_LIVE_LEDGER = Path(__file__).resolve().parents[2] / "data" / "identity" / "assertions.jsonl"
_CAMPAIGN_BUNDLE = (
    Path(__file__).resolve().parents[2]
    / "data" / "normalized" / "marin-county-campaign-finance-campaign-finance" / "nodes.jsonl"
)


def _org(org_id, name):
    return {"id": org_id, "node_type": "Organization", "labels": ["Organization"],
            "display_label": name, "properties": {}}


def _reg(committee_id, name, year):
    return {"committee_id": committee_id, "display_label": name,
            "election_year": year, "source": "cal_access"}

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
    assert "LATINO COALITION FOR MARIN 2024" in {r["display_label"] for r in refs}
    assert all(r["source"] == "cal_access" for r in refs)


def test_parse_filername_decodes_cp1252_bytes(tmp_path):
    # The real Cal-Access files are CP1252, not UTF-8 — prove the parser decodes a
    # genuine non-UTF-8 byte (É = 0xC9). Generated to tmp (never committed: a
    # committed non-UTF-8 byte would break the repo-wide UTF-8 text scans).
    f = tmp_path / "filername_cp1252.tsv"
    rows = [
        ["FILER_ID", "NAML", "FILER_TYPE"],
        ["1470900", "COMITÉ LATINO PARA MARIN 2024", "RECIPIENT COMMITTEE"],
    ]
    f.write_bytes(("\n".join("\t".join(r) for r in rows) + "\n").encode("cp1252"))
    assert b"\xc9" in f.read_bytes()  # genuinely non-UTF-8
    refs = parse_filername(f)
    assert refs[0]["display_label"] == "COMITÉ LATINO PARA MARIN 2024"  # decoded, not mojibake


# --------------------------------------------------------------------------
# Unit 4 — year-gated resolution (org name -> committee_id, queued only)
# --------------------------------------------------------------------------

_BONTA_REGISTRY = [
    _reg("1439160", "Bonta for Attorney General 2022", "2022"),
    _reg("1456428", "Bonta for Attorney General 2026", "2026"),
]


def test_year_gate_picks_matching_cycle_only():
    orgs = [_org("org-bonta-for-attorney-general-2022", "Bonta for Attorney General 2022")]
    cands = resolve_committee_ids(orgs, _BONTA_REGISTRY)
    assert len(cands) == 1
    c = cands[0]
    assert c["committee_id"] == "1439160"                          # 2022, NOT 2026
    # convention (matches EIN/sos/County): subject = the key anchor, candidate = the existing org
    assert c["subject_ref"] == FPPC_ANCHOR_PREFIX + "1439160"
    assert c["candidate_ref"] == "org-bonta-for-attorney-general-2022"
    assert c["status"] == "queued"                                 # NEVER auto-attached
    assert c["election_year"] == "2022"


def test_no_year_org_against_yearly_refs_withheld():
    orgs = [_org("org-bonta-for-attorney-general", "Bonta for Attorney General")]  # no year
    assert resolve_committee_ids(orgs, _BONTA_REGISTRY) == []      # cannot disambiguate cycle


def test_perennial_no_year_both_sides_matches():
    reg = [_reg("1352318", "Marin Association of Public Employees PAC", None)]
    orgs = [_org("org-mape-pac", "Marin Association of Public Employees PAC")]
    cands = resolve_committee_ids(orgs, reg)
    assert len(cands) == 1 and cands[0]["committee_id"] == "1352318"


def test_no_name_match_no_candidate():
    orgs = [_org("org-acme-llc", "Acme Plumbing LLC")]
    assert resolve_committee_ids(orgs, _BONTA_REGISTRY) == []


def test_ambiguous_same_year_two_committee_ids_withheld():
    reg = [
        _reg("2000001", "Friends of the Library 2024", "2024"),
        _reg("2000002", "Friends of the Library 2024", "2024"),  # same name+year, different id
    ]
    orgs = [_org("org-friends-of-the-library-2024", "Friends of the Library 2024")]
    assert resolve_committee_ids(orgs, reg) == []                  # >1 committee_id -> withheld


# --------------------------------------------------------------------------
# Unit 5 — read-merge-write ledger helper (Codex r1 blocker) + attach builder
# --------------------------------------------------------------------------

def _assertion(aid, status="approved", basis="operator_approved_committee_id"):
    return {"id": aid, "status": status, "basis": basis, "subject_ref": "s", "target_ref": "t"}


def test_merge_preserves_existing_and_adds_new(tmp_path):
    ledger = tmp_path / "assertions.jsonl"
    write_assertions([_assertion("assertion-aaa"), _assertion("assertion-bbb")], ledger)
    merge_approved_assertions([_assertion("assertion-ccc")], ledger)
    ids = {a["id"] for a in read_assertions(ledger)}
    assert ids == {"assertion-aaa", "assertion-bbb", "assertion-ccc"}


def test_merge_exact_duplicate_is_noop(tmp_path):
    ledger = tmp_path / "assertions.jsonl"
    write_assertions([_assertion("assertion-aaa")], ledger)
    merge_approved_assertions([_assertion("assertion-aaa")], ledger)  # identical -> no-op
    assert len(read_assertions(ledger)) == 1


def test_merge_same_id_different_payload_fails_loud(tmp_path):
    ledger = tmp_path / "assertions.jsonl"
    write_assertions([_assertion("assertion-aaa", status="approved")], ledger)
    with pytest.raises(ValueError, match="assertion-aaa"):
        merge_approved_assertions([_assertion("assertion-aaa", status="rejected_entity_distinct")], ledger)


def test_merge_seeds_live_68_and_all_survive(tmp_path):
    # Codex r1 blocker / Completion 5: the live 68 attach rows survive byte-for-byte
    assert _LIVE_LEDGER.is_file(), "BLOCKED: live ledger missing"
    seeded = tmp_path / "assertions.jsonl"
    original_lines = _LIVE_LEDGER.read_text(encoding="utf-8").splitlines()
    seeded.write_text("\n".join(original_lines) + "\n", encoding="utf-8")
    assert len(original_lines) == 68
    merge_approved_assertions([_assertion("assertion-new-committee")], seeded)
    out_lines = set(seeded.read_text(encoding="utf-8").splitlines())
    assert set(original_lines) <= out_lines        # every one of the 68 survives byte-for-byte
    assert len(out_lines) == 69


def test_build_committee_attach_assertion_and_same_as():
    cand = {"subject_ref": "org-fppc-1439160", "candidate_ref": "org-bonta-for-attorney-general-2022",
            "committee_id": "1439160", "evidence_record_ids": []}
    real = {"id": "org-bonta-for-attorney-general-2022", "display_label": "Bonta for Attorney General 2022"}
    assertion, same_as = build_committee_attach(
        cand, real, reviewer="stuart@eastpeak.cc", decided_at="2026-06-22")
    assert assertion["status"] == "approved"
    assert assertion["basis"] == "operator_approved_committee_id"
    assert assertion["subject_ref"] == "org-fppc-1439160"        # anchor
    assert assertion["target_ref"] == "org-bonta-for-attorney-general-2022"  # real org
    assert same_as["source_id"] == "org-fppc-1439160" and same_as["target_id"] == "org-bonta-for-attorney-general-2022"
    assert same_as["relationship_type"] == "SAME_AS"
    assert same_as["properties"]["basis"] == "operator_approved_committee_id"
    assert same_as["properties"]["assertion_id"] == assertion["id"]


# --------------------------------------------------------------------------
# Unit 8 — ROI preflight + real e2e (executed, not skipped)
# --------------------------------------------------------------------------

def test_e2e_real_filer_spine_coverage_and_resolve_to_dedup_merge():
    assert _CAMPAIGN_BUNDLE.is_file(), "BLOCKED: campaign bundle missing"
    spine = load_filer_spine(_CAMPAIGN_BUNDLE)
    org_nodes = [
        json.loads(l) for l in _CAMPAIGN_BUNDLE.read_text(encoding="utf-8").splitlines()
        if l.strip() and json.loads(l).get("node_type") == "Organization"
    ]
    report = roi_preflight(org_nodes, spine)
    assert report["registry_refs"] == 115           # the in-graph filer spine (tier 1)
    assert report["committee_id_candidates"] >= 50   # real tier-1 coverage (executed)

    cands = resolve_committee_ids(org_nodes, spine)
    # a real name-variant dup pair resolves to the SAME committee_id (the lane's value)
    hilliard = {c["candidate_ref"] for c in cands if c["committee_id"] == "1470249"}
    assert len(hilliard) == 2 and all(c["status"] == "queued" for c in cands)

    # post-approval: those two org refs now carry committee_id 1470249 -> the dedup
    # deterministic tier MERGES them; a different-cycle committee (different id) stays distinct.
    refs = [
        {"id": oid, "display_label": "Cathryn Hilliard for Southern Marin Fire 2024",
         "committee_id": "1470249"} for oid in sorted(hilliard)
    ] + [{"id": "org-other-2026", "display_label": "Someone Else for Office 2026",
          "committee_id": "1456428"}]
    asserts = deterministic_dedup_assertions(refs, reviewer="dedup_pass", policy_version="dedup-v1")
    merged_ids = {a["subject_ref"] for a in asserts} | {a["target_ref"] for a in asserts}
    assert merged_ids == set(sorted(hilliard))        # the pair merges
    assert "org-other-2026" not in merged_ids         # different committee_id never merges
