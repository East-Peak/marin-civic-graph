"""B1 — the committed legacy-slice fixture covers every migration case.

The full golden (data/projected/phase0-bcore/golden-current/) is captured by
running the current pipeline and is gitignored.  What we commit is a small,
representative slice of the LEGACY (pre-migration) graph that exercises every
migration case; B2 pins graph_v2_transforms against migration_mapping over it.

This test guards that slice: it exists, is non-empty, covers each node/edge
transform case, and migrates to ONLY settled labels.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import migration_mapping as mm
from verify_phase0_consolidation import assert_no_legacy_labels

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "phase0"
NODES_PATH = FIXTURES / "legacy_slice_nodes.jsonl"
EDGES_PATH = FIXTURES / "legacy_slice_edges.jsonl"


def _load(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_fixture_files_exist_and_non_empty():
    assert NODES_PATH.exists() and EDGES_PATH.exists()
    assert _load(NODES_PATH), "legacy slice nodes must be non-empty"
    assert _load(EDGES_PATH), "legacy slice edges must be non-empty"


def test_slice_covers_every_node_case():
    nodes = _load(NODES_PATH)
    node_types = {n["node_type"] for n in nodes}
    # Every node-transform branch must be represented.
    for required in ("Actor", "Institution", "EconomicInterestDisclosure",
                     "CaseParticipation"):
        assert required in node_types, f"missing {required} in slice"
    # At least one pass-through type (Case/Decision/Record/Meeting/...).
    assert node_types - {"Actor", "Institution", "EconomicInterestDisclosure",
                         "CaseParticipation"}, "no pass-through node in slice"

    actors = [n for n in nodes if n["node_type"] == "Actor"]
    actor_types = {a["properties"].get("actor_type", "") for a in actors}
    # Both org-like and person-like (incl. empty default) Actors present.
    assert actor_types & mm._ORG_ACTOR_TYPES, "no org-like Actor in slice"
    assert actor_types & {"person", ""}, "no person/default Actor in slice"
    assert any("observed_labels" in a["properties"] for a in actors), \
        "no Actor with observed_labels (-> aliases) in slice"

    insts = [n for n in nodes if n["node_type"] == "Institution"]
    inst_types = {i["properties"].get("institution_type", "") for i in insts}
    assert "court" in inst_types, "no court Institution in slice"
    assert inst_types & mm._GOVERNMENT_INSTITUTION_TYPES, "no government Institution in slice"


def test_slice_covers_every_edge_case():
    edges = _load(EDGES_PATH)
    rel_types = {e["relationship_type"] for e in edges}
    # A REL_TYPE_MAP-renamed relationship must be present.
    assert rel_types & set(mm.REL_TYPE_MAP), "no renamed relationship in slice"
    # CaseParticipation evidence harvest: an EVIDENCED_BY edge from a casepart- node.
    assert any(e["relationship_type"] == "EVIDENCED_BY"
               and e["source_id"].startswith("casepart-") for e in edges), \
        "no casepart EVIDENCED_BY edge in slice"
    # A relationship_passthrough survivor (RECORD_* edge).
    assert any(e["relationship_type"].startswith("RECORD_") for e in edges), \
        "no relationship_passthrough RECORD_* edge in slice"


def test_slice_migrates_to_settled_labels_only():
    nodes = _load(NODES_PATH)
    migrated = [m for m in (mm.migrate_node(n) for n in nodes) if m is not None]
    # CaseParticipation nodes drop to None; everything else carries settled labels.
    assert migrated
    assert_no_legacy_labels(migrated)  # raises AssertionError if any legacy label
