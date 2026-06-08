"""B2 — graph_v2_transforms.py is golden-pinned against migration_mapping.

The v2-native transforms must reproduce today's migration semantics EXACTLY:
 - classify_actor / classify_institution / eid_to_filing reproduce the
   (node_type, labels, id) that migration_mapping.migrate_node assigns;
 - rename_rel reproduces REL_TYPE_MAP;
 - remap_props is SHALLOW (payload_json never recursively remapped);
 - node_to_v2 / edge_to_v2 / cp_to_party_to reproduce
   migrate_node / migrate_edge / case_participation_to_edges over the whole
   committed legacy slice, including CaseParticipation node+edge evidence.

TDD: written before scripts/graph_v2_transforms.py exists.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import migration_mapping as mm
import graph_v2_transforms as gt

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "phase0"


def _load(name):
    return [json.loads(l) for l in (FIXTURES / name).read_text().splitlines() if l.strip()]


SLICE_NODES = _load("legacy_slice_nodes.jsonl")
SLICE_EDGES = _load("legacy_slice_edges.jsonl")


def _id_map(nodes):
    """Reproduce migrate_graph_v2 pass 1: old_id -> new_id where they differ."""
    m = {}
    for n in nodes:
        old = n["id"]
        new = mm.migrate_id(old, n["node_type"], n.get("properties", {}))
        if new != old:
            m[old] = new
    return m


def _cp_evidence(edges):
    """Reproduce migrate_graph_v2 pass 3: casepart- EVIDENCED_BY harvest."""
    ev = {}
    for e in edges:
        if e.get("relationship_type") == "EVIDENCED_BY" and e["source_id"].startswith("casepart-"):
            ev.setdefault(e["source_id"], []).append(e["target_id"])
    return ev


# ---------------------------------------------------------------------------
# Decomposed classifiers — pinned against migrate_node
# ---------------------------------------------------------------------------

def test_classify_actor_matches_legacy_over_all_actor_types():
    base = {"node_type": "Actor", "display_label": "X", "promotion_state": "canonical",
            "source_bundle_ids": [], "source_sections": [], "source_status": None}
    for atype in list(mm._ACTOR_ORG_LABELS) + ["person", "unknown", "", "judge_made_up"]:
        node = {**base, "id": "actor-x", "properties": {"actor_type": atype}}
        legacy = mm.migrate_node(node)
        assert gt.classify_actor("actor-x", atype) == (
            legacy["node_type"], legacy["labels"], legacy["id"]
        ), f"actor_type={atype!r}"


def test_classify_actor_person_default_for_unknown():
    assert gt.classify_actor("actor-y", "")[0] == "Person"
    assert gt.classify_actor("actor-y", "totally_unknown")[0] == "Person"


def test_classify_institution_matches_legacy():
    base = {"node_type": "Institution", "display_label": "I", "promotion_state": "canonical",
            "source_bundle_ids": [], "source_sections": [], "source_status": None}
    for itype in list(mm._GOVERNMENT_INSTITUTION_TYPES) + ["court", "tribunal", ""]:
        node = {**base, "id": "inst-x", "properties": {"institution_type": itype}}
        legacy = mm.migrate_node(node)
        assert gt.classify_institution("inst-x", itype) == (
            legacy["node_type"], legacy["labels"], legacy["id"]
        ), f"institution_type={itype!r}"


def test_eid_to_filing_matches_legacy():
    node = {"id": "eid-x", "node_type": "EconomicInterestDisclosure", "display_label": "E",
            "promotion_state": "canonical", "source_bundle_ids": [], "source_sections": [],
            "source_status": None, "properties": {"disclosure_type": "annual"}}
    legacy = mm.migrate_node(node)
    assert gt.eid_to_filing("eid-x") == (legacy["node_type"], legacy["labels"], legacy["id"])


def test_rename_rel_matches_map_and_identity_for_unmapped():
    for old_rel, new_rel in mm.REL_TYPE_MAP.items():
        assert gt.rename_rel(old_rel) == new_rel
    assert gt.rename_rel("SOME_UNMAPPED_REL") == "SOME_UNMAPPED_REL"


def test_remap_props_is_shallow_and_preserves_payload_json():
    payload = json.dumps({"id": "eid-x", "filer_actor_id": "actor-bar",
                          "institution_id": "inst-foo"}, sort_keys=True)
    props = {"institution_id": "inst-foo", "filer_actor_id": "actor-bar",
             "payload_json": payload}
    id_map = {"actor-bar": "person-bar"}
    assert gt.remap_props(props, id_map) == mm._remap_props(props, id_map)
    out = gt.remap_props(props, id_map)
    assert out["institution_id"] == "org-foo"      # shallow prefix remap
    assert out["filer_actor_id"] == "person-bar"   # id_map remap
    # payload_json is NOT recursively remapped — legacy ids preserved verbatim
    assert out["payload_json"] == payload
    assert "actor-bar" in out["payload_json"] and "inst-foo" in out["payload_json"]


# ---------------------------------------------------------------------------
# Whole-slice equality — node_to_v2 / edge_to_v2 / cp_to_party_to
# ---------------------------------------------------------------------------

def test_node_to_v2_matches_migrate_node_over_slice():
    for n in SLICE_NODES:
        assert gt.node_to_v2(n) == mm.migrate_node(n), f"node {n['id']}"
    # CaseParticipation drops to None in both.
    cps = [n for n in SLICE_NODES if n["node_type"] == "CaseParticipation"]
    assert cps and all(gt.node_to_v2(n) is None for n in cps)


def test_edge_to_v2_matches_migrate_edge_over_slice():
    id_map = _id_map(SLICE_NODES)
    for e in SLICE_EDGES:
        assert gt.edge_to_v2(e, id_map) == mm.migrate_edge(e, id_map), \
            f"edge {e['source_id']}-{e['relationship_type']}-{e['target_id']}"
    # casepart- edges drop to None in both.
    dropped = [e for e in SLICE_EDGES if e["source_id"].startswith("casepart-")
               or e["target_id"].startswith("casepart-")]
    assert dropped and all(gt.edge_to_v2(e, id_map) is None for e in dropped)


def test_cp_to_party_to_matches_legacy_with_evidence():
    id_map = _id_map(SLICE_NODES)
    cp_nodes = [n for n in SLICE_NODES if n["node_type"] == "CaseParticipation"]
    cp_evidence = _cp_evidence(SLICE_EDGES)
    expected = mm.case_participation_to_edges(cp_nodes, cp_evidence, id_map)
    assert gt.cp_to_party_to(cp_nodes, cp_evidence, id_map) == expected
    # Real conversion: PARTY_TO edges, evidence merged from node + harvested edges.
    assert expected and all(e["relationship_type"] == "PARTY_TO" for e in expected)
    assert any(e["properties"]["evidence_record_ids"] for e in expected)
    # Both person-party and org-party CaseParticipations represented.
    src_types = {e["source_node_type"] for e in expected}
    assert {"Person", "Organization"} <= src_types


def test_reuses_legacy_constants_not_re_derived():
    # Guardrail: reuse the constants, don't hand-copy them.
    assert gt._ORG_ACTOR_TYPES is mm._ORG_ACTOR_TYPES
    assert gt._ACTOR_ORG_LABELS is mm._ACTOR_ORG_LABELS
    assert gt.REL_TYPE_MAP is mm.REL_TYPE_MAP
