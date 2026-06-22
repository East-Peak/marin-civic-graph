"""Tests for scripts/dedup_org_candidates.py — graph-internal Organization dedup
(the pure candidate pass + the merge applier). Intra-graph org<->org dedup built
on the existing resolver + Identity Control A ledger, pointed inward.

Pure code + staged-fixture tests. No DB, no network. The deterministic tier is
GROUP-BY-KEY (NOT the cross-source resolver, which conflict-queues N>=2 same-key
refs); the name tier uses propose_org_resolutions on N=2 pairs. Anchors
(org-bmf-ein-*/org-casos-*/org-usasp-uei-*) and already-tombstoned
(dedup_superseded_by) refs are excluded from candidates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from dedup_org_candidates import (  # noqa: E402
    affiliate_token_divergence,
    deterministic_dedup_assertions,
    is_anchor,
    load_org_refs,
    name_tier_candidates,
    run_dedup_pass,
    structural_class,
)
import org_resolution  # noqa: E402


def _ref(org_id, label, **kw):
    return {"id": org_id, "display_label": label, **kw}


_DET_KW = dict(reviewer="dedup_pass", policy_version="dedup-v1")


# ---------------------------------------------------------------------------
# Cycle 1 — foundational helpers
# ---------------------------------------------------------------------------

def test_is_anchor_flags_synthetic_key_nodes_only():
    assert is_anchor("org-bmf-ein-942689383")
    assert is_anchor("org-casos-1628638")
    assert is_anchor("org-usasp-uei-JZ9FLAVMPEB9")
    assert not is_anchor("org-marin-agricultural-land-trust")
    assert not is_anchor("org-990-ein-942689383")  # a 990-namespace ref is NOT a key anchor


def test_load_org_refs_excludes_anchors_and_tombstoned(tmp_path):
    export = tmp_path / "orgs.json"
    export.write_text(json.dumps([
        {"id": "org-real-a", "display_label": "Real A", "ein": "111111111", "degree": 5},
        {"id": "org-bmf-ein-111111111", "display_label": "BMF anchor", "ein": "111111111"},
        {"id": "org-casos-222", "display_label": "SOS anchor", "sos_id": "222"},
        {"id": "org-merged-dup", "display_label": "Merged Dup", "dedup_superseded_by": "org-real-a"},
        {"id": "org-real-b", "display_label": "Real B", "degree": 2},
    ]), encoding="utf-8")

    refs = load_org_refs(export)

    ids = {r["id"] for r in refs}
    assert ids == {"org-real-a", "org-real-b"}  # anchors + tombstoned dropped


def test_structural_class_committee_vs_organization():
    assert structural_class("Marin Women's Political Action Committee") == "committee"
    assert structural_class("SOME GROUP PAC") == "committee"
    assert structural_class("Marin Builders Association BPAC") == "committee"
    assert structural_class("Citizens BAPAC") == "committee"
    assert structural_class("Marin Builders Association") == "organization"
    assert structural_class("Kiddo! Mill Valley Schools Community Foundation") == "organization"


def test_affiliate_token_divergence_one_sided_only():
    # one side carries an affiliate token, the other does not -> divergent
    assert affiliate_token_divergence("Glenwood School", "Glenwood School Foundation")
    assert affiliate_token_divergence("Marin Symphony", "Friends of Marin Symphony")
    # both carry (or neither carries) -> NOT divergent
    assert not affiliate_token_divergence(
        "Corte Madera Larkspur Schools Foundation", "SPARK Corte Madera Larkspur Foundation"
    )
    assert not affiliate_token_divergence("BHM Construction", "BHM Construction Inc")


# ---------------------------------------------------------------------------
# Cycle 2 — deterministic group-by-key tier
# ---------------------------------------------------------------------------

def test_two_node_ein_cluster_emits_one_deterministic_assertion():
    refs = [
        _ref("org-b-second", "Kiddo Mill Valley", ein="942848305", degree=3),
        _ref("org-a-first", "Mill Valley Schools KIDDO", ein="942848305", degree=9),
    ]
    asserts = deterministic_dedup_assertions(refs, **_DET_KW)
    assert len(asserts) == 1
    a = asserts[0]
    assert a["status"] == "deterministic"
    assert a["basis"] == "org_dedup_key_exact"
    assert a["decided_at"] == "deterministic"
    # pair canonically ordered (subject < target) so (A,B)/(B,A) collapse
    assert a["subject_ref"] == "org-a-first"
    assert a["target_ref"] == "org-b-second"


def test_four_node_same_class_cluster_forms_one_component_via_star():
    refs = [
        _ref("org-mwpac-4", "Marin Women's Political Action Committee PAC", ein="272935125"),
        _ref("org-mwpac-1", "Marin Women's Political Action Committee", ein="272935125"),
        _ref("org-mwpac-3", "Marin Women's Political Action Committee (MWPAC)", ein="272935125"),
        _ref("org-mwpac-2", "Marin Women's Political Action Committee (AKA MWPAC)", ein="272935125"),
    ]
    asserts = deterministic_dedup_assertions(refs, **_DET_KW)
    # star from the lexically-smallest id connects all 4 (N-1 = 3 edges)
    assert len(asserts) == 3
    assert {a["subject_ref"] for a in asserts} == {"org-mwpac-1"}
    assert {a["target_ref"] for a in asserts} == {"org-mwpac-2", "org-mwpac-3", "org-mwpac-4"}


def test_class_mismatch_in_key_group_never_merges():
    # an org and a committee sharing an EIN must NOT merge (Predeclared 4)
    refs = [
        _ref("org-parent", "Marin Builders Association", ein="941415040"),
        _ref("org-pac", "Marin Builders Association BPAC", ein="941415040"),
    ]
    assert deterministic_dedup_assertions(refs, **_DET_KW) == []


def test_singletons_and_no_key_emit_nothing():
    refs = [
        _ref("org-solo", "Solo Org", ein="111111111"),
        _ref("org-nokey", "No Key Org"),
        _ref("org-nokey2", "Another No Key"),
    ]
    assert deterministic_dedup_assertions(refs, **_DET_KW) == []


def test_sos_id_tier_works_and_self_registers_normalizer():
    # Deleting the sos_id normalizer then running proves the pass registers it
    # itself (Predeclared 1) rather than relying on import side effects.
    org_resolution.KEY_NORMALIZERS.pop("sos_id", None)
    refs = [
        _ref("org-ghil-b", "Ghilotti Construction Company", sos_id="1819837"),
        _ref("org-ghil-a", "Ghilotti Construction", sos_id="1819837"),
    ]
    asserts = deterministic_dedup_assertions(refs, **_DET_KW)
    assert len(asserts) == 1
    assert asserts[0]["basis"] == "org_dedup_key_exact"
    assert "sos_id" in org_resolution.KEY_NORMALIZERS  # re-registered


# ---------------------------------------------------------------------------
# Cycle 3 — name tier (resolver on blocked N=2 pairs; queued, NEVER merged)
# ---------------------------------------------------------------------------

def test_name_tier_proposes_queued_candidate_same_class_no_key():
    # real tail dups are exact-name repeats (e.g. Wright Contracting x3) — caught
    # via normalized_name_exact after corporate-suffix stripping.
    refs = [
        _ref("org-wright-2", "Wright Contracting, Inc."),
        _ref("org-wright-1", "Wright Contracting"),
    ]
    cands = name_tier_candidates(refs)
    assert len(cands) == 1
    c = cands[0]
    assert c["status"] == "queued"            # NEVER auto-merged
    assert c["subject_ref"] == "org-wright-1"  # canonical order subject<candidate
    assert c["candidate_ref"] == "org-wright-2"
    assert c["signals"] == ["normalized_name_exact"]
    assert c["review_tier"] == "standard"
    assert c["affiliate_token_divergence"] is False


def test_name_tier_flags_affiliate_divergence_needs_careful_review():
    refs = [
        _ref("org-aud", "Marin Audubon Society"),
        _ref("org-aud-fund", "Marin Audubon Society Fund"),
    ]
    cands = name_tier_candidates(refs)
    assert len(cands) == 1
    assert cands[0]["affiliate_token_divergence"] is True
    assert cands[0]["review_tier"] == "needs_careful_review"
    assert cands[0]["status"] == "queued"


def test_name_tier_excludes_class_mismatch():
    refs = [
        _ref("org-mba", "Marin Builders Association"),
        _ref("org-mba-bpac", "Marin Builders Association BPAC"),
    ]
    assert name_tier_candidates(refs) == []  # committee<->organization never a candidate


# ---------------------------------------------------------------------------
# Cycle 4 — orchestration: SEPARATE dedup ledger file + sidecar; never clobber
# the live assertions.jsonl; deterministic re-runs; anchors excluded.
# ---------------------------------------------------------------------------

def _write_export(path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_run_dedup_pass_writes_separate_files_and_never_touches_live_ledger(tmp_path):
    export = tmp_path / "existing-orgs-enriched.json"
    _write_export(export, [
        _ref("org-kiddo-b", "Kiddo Mill Valley Schools", ein="942848305", degree=3),
        _ref("org-kiddo-a", "Kiddo Mill Valley", ein="942848305", degree=9),
        _ref("org-wright-1", "Wright Contracting"),
        _ref("org-wright-2", "Wright Contracting Inc"),
        _ref("org-bmf-ein-942848305", "ANCHOR — must be excluded", ein="942848305"),
    ])
    # the live attach ledger — must survive byte-for-byte
    live_ledger = tmp_path / "assertions.jsonl"
    live_bytes = b'{"id": "assertion-live-1", "status": "approved"}\n'
    live_ledger.write_bytes(live_bytes)

    dedup_ledger = tmp_path / "dedup-assertions.jsonl"
    sidecar = tmp_path / "dedup-name-candidates.jsonl"
    summary = run_dedup_pass(
        export, dedup_ledger_path=dedup_ledger, sidecar_path=sidecar,
        reviewer="dedup_pass", policy_version="dedup-v1",
    )

    # live ledger untouched
    assert live_ledger.read_bytes() == live_bytes
    # deterministic ledger: the KIDDO pair, basis org_dedup_key_exact, no anchor
    det = [json.loads(l) for l in dedup_ledger.read_text().splitlines() if l.strip()]
    assert len(det) == 1 and det[0]["basis"] == "org_dedup_key_exact"
    refs_in = {det[0]["subject_ref"], det[0]["target_ref"]}
    assert refs_in == {"org-kiddo-a", "org-kiddo-b"}
    assert not any("org-bmf-ein-" in r for r in refs_in)  # anchor excluded
    # sidecar: the Wright name candidate (queued)
    names = [json.loads(l) for l in sidecar.read_text().splitlines() if l.strip()]
    assert len(names) == 1 and names[0]["status"] == "queued"
    assert summary["deterministic_assertions"] == 1
    assert summary["name_candidates"] == 1


def test_run_dedup_pass_is_deterministic_byte_identical(tmp_path):
    export = tmp_path / "orgs.json"
    _write_export(export, [
        _ref("org-a", "Tomales High School Booster", ein="942865901"),
        _ref("org-b", "Tomales High School Booster Club", ein="942865901"),
    ])
    d1, s1 = tmp_path / "d1.jsonl", tmp_path / "s1.jsonl"
    d2, s2 = tmp_path / "d2.jsonl", tmp_path / "s2.jsonl"
    kw = dict(reviewer="dedup_pass", policy_version="dedup-v1")
    run_dedup_pass(export, dedup_ledger_path=d1, sidecar_path=s1, **kw)
    run_dedup_pass(export, dedup_ledger_path=d2, sidecar_path=s2, **kw)
    assert d1.read_bytes() == d2.read_bytes()
    assert s1.read_bytes() == s2.read_bytes()


def test_name_tier_excludes_shared_hard_key_pairs():
    # a shared key is the DETERMINISTIC tier's job — never a name candidate
    refs = [
        _ref("org-k-a", "Kiddo Mill Valley", ein="942848305"),
        _ref("org-k-b", "Kiddo Mill Valley Schools", ein="942848305"),
    ]
    assert name_tier_candidates(refs) == []
