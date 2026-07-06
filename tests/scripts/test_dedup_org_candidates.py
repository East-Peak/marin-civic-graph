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
    assemble_components,
    choose_canonical,
    deterministic_dedup_assertions,
    is_anchor,
    load_org_refs,
    name_tier_candidates,
    run_dedup_pass,
    structural_class,
)


def _merge(subject, target, status="approved", basis="org_dedup_operator_approved"):
    return {"subject_ref": subject, "target_ref": target, "status": status, "basis": basis}
import org_resolution  # noqa: E402
import dedup_org_candidates as _doc  # noqa: E402


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


# ---------------------------------------------------------------------------
# Unit 2 — canonical-node selection (Predeclared 3: hard-key -> degree -> id)
# ---------------------------------------------------------------------------

def test_choose_canonical_hard_key_beats_no_key():
    # (a) a node carrying a hard key wins over one without — even at lower degree
    refs = [
        _ref("org-keyed", "Keyed Org", ein="111111111", degree=1),
        _ref("org-bare", "Bare Org", degree=100),
    ]
    assert choose_canonical(refs) == "org-keyed"


def test_choose_canonical_same_key_picks_highest_degree():
    # (b) deterministic tier: all share the key -> the best-connected real org wins
    refs = [
        _ref("org-thin", "KIDDO thin", ein="942848305", degree=3),
        _ref("org-fat", "KIDDO fat", ein="942848305", degree=9),
    ]
    assert choose_canonical(refs) == "org-fat"


def test_choose_canonical_degree_tie_breaks_on_lexical_id():
    refs = [
        _ref("org-zzz", "Z", ein="1", degree=5),
        _ref("org-aaa", "A", ein="1", degree=5),
    ]
    assert choose_canonical(refs) == "org-aaa"


def test_choose_canonical_null_degree_sorts_as_zero():
    # a missing/null degree (e.g. a thin anchor) loses to any positive degree
    refs = [
        _ref("org-anchorish", "no degree", ein="1"),          # degree absent -> 0
        _ref("org-real", "real", ein="1", degree=1),
    ]
    assert choose_canonical(refs) == "org-real"
    refs2 = [_ref("org-x", "x", ein="1", degree=None), _ref("org-y", "y", ein="1", degree=2)]
    assert choose_canonical(refs2) == "org-y"


# ---------------------------------------------------------------------------
# Unit 3 — approved-component assembly + SPLIT guard + key-conflict/anchor refusal
# ---------------------------------------------------------------------------

def test_transitive_chain_merges_all_three():
    refs = {r["id"]: r for r in [
        _ref("org-a", "Org A", ein="1", degree=2),
        _ref("org-b", "Org B", ein="1", degree=9),
        _ref("org-c", "Org C", ein="1", degree=1),
    ]}
    asserts = [_merge("org-a", "org-b"), _merge("org-b", "org-c")]
    out = assemble_components(asserts, refs)
    assert len(out["accepted"]) == 1 and out["refused"] == []
    comp = out["accepted"][0]
    assert comp["members"] == ["org-a", "org-b", "org-c"]
    assert comp["canonical"] == "org-b"  # highest degree


def test_split_guard_refuses_component_with_rejected_pair():
    refs = {r["id"]: r for r in [
        _ref("org-a", "A", ein="1"), _ref("org-b", "B", ein="1"), _ref("org-c", "C", ein="1"),
    ]}
    asserts = [
        _merge("org-a", "org-b"), _merge("org-b", "org-c"),
        _merge("org-a", "org-c", status="rejected_entity_distinct"),
    ]
    out = assemble_components(asserts, refs)
    assert out["accepted"] == []
    assert len(out["refused"]) == 1
    assert "rejected_pair" in out["refused"][0]["reasons"]


def test_hard_key_conflict_refuses_component():
    # an A-B-C chain whose ends carry DIFFERENT EINs must not silently merge
    refs = {r["id"]: r for r in [
        _ref("org-a", "A", ein="111"), _ref("org-b", "B"), _ref("org-c", "C", ein="222"),
    ]}
    asserts = [_merge("org-a", "org-b"), _merge("org-b", "org-c")]
    out = assemble_components(asserts, refs)
    assert out["accepted"] == []
    assert any(r.startswith("hard_key_conflict") for r in out["refused"][0]["reasons"])


def test_assemble_reads_only_dedup_basis_ignores_attach_assertions():
    # the live 78-row attach ledger (status approved, basis operator_approved_ein,
    # linking an org-bmf-ein-* anchor to a real org) must be IGNORED by assembly —
    # NOT consumed as a merge (Predeclared 10).
    refs = {r["id"]: r for r in [_ref("org-real", "Real Org", ein="1")]}
    attach = [{
        "subject_ref": "org-bmf-ein-1", "target_ref": "org-real",
        "status": "approved", "basis": "operator_approved_ein",
    }]
    out = assemble_components(attach, refs)
    assert out["accepted"] == [] and out["refused"] == []  # ignored, not a dedup assertion


def test_anchor_containing_component_refused():
    refs = {r["id"]: r for r in [_ref("org-real", "Real", ein="1")]}
    asserts = [_merge("org-real", "org-bmf-ein-1")]
    out = assemble_components(asserts, refs)
    assert out["accepted"] == []
    assert "contains_anchor" in out["refused"][0]["reasons"]


def test_unapproved_pair_does_not_ride_transitivity():
    # a `queued` (B,C) is NOT a merge — C must not join {A,B}
    refs = {r["id"]: r for r in [
        _ref("org-a", "A", ein="1"), _ref("org-b", "B", ein="1"), _ref("org-c", "C", ein="1"),
    ]}
    asserts = [_merge("org-a", "org-b"), _merge("org-b", "org-c", status="queued")]
    out = assemble_components(asserts, refs)
    assert len(out["accepted"]) == 1
    assert out["accepted"][0]["members"] == ["org-a", "org-b"]  # C excluded


def test_name_tier_excludes_shared_hard_key_pairs():
    # a shared key is the DETERMINISTIC tier's job — never a name candidate
    refs = [
        _ref("org-k-a", "Kiddo Mill Valley", ein="942848305"),
        _ref("org-k-b", "Kiddo Mill Valley Schools", ein="942848305"),
    ]
    assert name_tier_candidates(refs) == []


# ---------------------------------------------------------------------------
# Unit 6 — real keyed e2e (Completion 7). EXECUTED over the live enriched
# export, never skipped; BLOCKS (fails loud) if the export is genuinely absent.
# ---------------------------------------------------------------------------

import copy as _copy  # noqa: E402
from dedup_merge_applier import (  # noqa: E402
    apply_component_merge,
    canonical_graph,
    rollback_component_merge,
)

_REAL_EXPORT = Path(__file__).resolve().parents[2] / "data/exports/existing-orgs-enriched.json"


def test_e2e_real_export_deterministic_clusters_and_reversible_merge():
    assert _REAL_EXPORT.is_file(), (
        "BLOCKED: real enriched org export missing — "
        "data/exports/existing-orgs-enriched.json"
    )
    refs = load_org_refs(_REAL_EXPORT)
    refs_by_id = {r["id"]: r for r in refs}
    # anchors excluded from the candidate input
    assert not any(is_anchor(r["id"]) for r in refs)
    assert len(refs) == 1346

    det = deterministic_dedup_assertions(refs, reviewer="dedup_pass", policy_version="dedup-v1")
    assert all(a["basis"] == "org_dedup_key_exact" for a in det)
    assert all(a["status"] == "deterministic" for a in det)

    assembly = assemble_components(det, refs_by_id)
    assert assembly["refused"] == []                       # no anchor/conflict/rejected
    accepted = assembly["accepted"]
    assert len(accepted) == 6                              # the 6 deterministic clusters
    sizes = sorted(len(c["members"]) for c in accepted)
    assert sizes == [2, 2, 2, 2, 3, 4]                     # 15 nodes total
    assert sum(sizes) == 15
    # the MWPAC x4 cluster is present and all-committee (merges into one)
    mwpac = next(c for c in accepted if len(c["members"]) == 4)
    assert all("political-action-committee" in m for m in mwpac["members"])
    # every canonical is the highest-degree real member of its cluster
    for comp in accepted:
        best = max(comp["members"], key=lambda m: (refs_by_id[m].get("degree") or 0, ))
        assert comp["canonical"] == choose_canonical([refs_by_id[m] for m in comp["members"]])
        assert (refs_by_id[comp["canonical"]].get("degree") or 0) == (refs_by_id[best].get("degree") or 0)

    # name tier: unkeyed tail -> queued; affiliate divergences -> needs_careful_review
    names = name_tier_candidates(refs)
    assert names and all(c["status"] == "queued" for c in names)
    assert any(c["review_tier"] == "needs_careful_review" for c in names)

    # constructed reversible merge of ONE real cluster (KIDDO x2) on a fixture graph
    kiddo = next(c for c in accepted
                 if any("kiddo" in m for m in c["members"]))
    canon = kiddo["canonical"]
    dup = next(m for m in kiddo["members"] if m != canon)
    graph = {
        "nodes": {
            canon: {"id": canon, "labels": ["Organization"], "properties": {"ein": "942848305"}},
            dup: {"id": dup, "labels": ["Organization"], "properties": {"ein": "942848305"}},
            "dept": {"id": "dept", "labels": ["Organization"], "properties": {}},
        },
        "edges": {(dup, "TO_TARGET", "dept"): {"amount": 7}},
    }
    before = canonical_graph(_copy.deepcopy(graph))
    record = apply_component_merge(graph, kiddo)
    assert (canon, "TO_TARGET", "dept") in graph["edges"]            # repointed onto canonical
    assert graph["nodes"][dup]["properties"]["dedup_superseded_by"] == canon
    assert "Organization" in graph["nodes"][dup]["labels"]           # label kept
    rollback_component_merge(graph, record)
    assert canonical_graph(graph) == before                          # byte-identical


def test_fppc_committee_id_in_dedup_keys_and_anchor_prefix():
    assert "committee_id" in _doc._DEDUP_KEYS
    assert "org-fppc-" in _doc.ANCHOR_PREFIXES
    assert is_anchor("org-fppc-1439160")  # excluded from candidates


def test_committee_id_cluster_merges_overriding_name_class():
    # both share committee_id 1439160; name-derived class differs (org vs committee)
    # — committee_id presence overrides class so they STILL merge (Predeclared 7c).
    refs = [
        _ref("org-bonta-ag-2022", "Bonta for Attorney General 2022",
             committee_id="1439160"),                                  # name -> organization
        _ref("org-bonta-ag-cmte-2022", "Bonta for AG Committee 2022",
             committee_id="1439160"),                                  # name -> committee
    ]
    asserts = deterministic_dedup_assertions(refs, **_DET_KW)
    assert len(asserts) == 1 and asserts[0]["basis"] == "org_dedup_key_exact"


def test_committee_id_different_ids_never_merge():
    refs = [
        _ref("org-bonta-2022", "Bonta for Attorney General 2022", committee_id="1439160"),
        _ref("org-bonta-2026", "Bonta for Attorney General 2026", committee_id="1456428"),
    ]
    assert deterministic_dedup_assertions(refs, **_DET_KW) == []  # distinct ids -> no group


def test_committee_id_same_id_different_year_refused_cycle_guard():
    # the rare rename-reuse-across-cycles: SAME committee_id, different name-years
    # -> cycle guard refuses the merge (Predeclared 7d / Codex r2).
    refs = [
        _ref("org-x-2022", "Reuse Committee 2022", committee_id="9999999"),
        _ref("org-x-2026", "Reuse Committee 2026", committee_id="9999999"),
    ]
    assert deterministic_dedup_assertions(refs, **_DET_KW) == []


def test_dedup_self_registers_committee_id_normalizer():
    org_resolution.KEY_NORMALIZERS.pop("committee_id", None)
    refs = [
        _ref("org-a", "Same Committee 2024", committee_id="2222222"),
        _ref("org-b", "Same Committee 2024 Variant", committee_id="2222222"),
    ]
    asserts = deterministic_dedup_assertions(refs, **_DET_KW)
    assert len(asserts) == 1
    assert "committee_id" in org_resolution.KEY_NORMALIZERS  # re-registered


def test_e2e_real_ledger_yields_zero_anchor_merges():
    # Completion 1b: over the CURRENT live attach ledger (operator_approved_*
    # rows linking org-bmf-ein-*/org-casos-* anchors to real orgs) PLUS the dedup
    # deterministic assertions, assembly produces ZERO anchor-into-org merges.
    assert _REAL_EXPORT.is_file(), "BLOCKED: real enriched org export missing"
    ledger = Path(__file__).resolve().parents[2] / "data/identity/assertions.jsonl"
    assert ledger.is_file(), "BLOCKED: live attach ledger missing"
    import identity_ledger  # noqa: E402

    attach = identity_ledger.read_assertions(ledger)
    assert attach
    assert all(not str(a.get("basis", "")).startswith("org_dedup") for a in attach)

    refs = load_org_refs(_REAL_EXPORT)
    refs_by_id = {r["id"]: r for r in refs}
    det = deterministic_dedup_assertions(refs, reviewer="dedup_pass", policy_version="dedup-v1")

    expected = assemble_components(det, refs_by_id)
    out = assemble_components(attach + det, refs_by_id)
    assert out == expected
    # attach rows are IGNORED (non-dedup basis) -> zero anchor in any component
    for comp in out["accepted"] + out["refused"]:
        assert not any(is_anchor(m) for m in comp["members"])
