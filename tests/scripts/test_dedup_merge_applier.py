"""Tests for scripts/dedup_merge_applier.py — the reversible merge applier.

Pure bundle/edge-rewrite mode (the loop tests this against in-memory fixtures;
the live-Cypher mode is operator-gated, never run by the loop). A merge repoints
the duplicate's edges onto the canonical, TOMBSTONES the dup via a
`dedup_superseded_by` property (the :Organization label is KEPT — node identity
preserved across reload), and writes a FULL PREIMAGE journal so the merge is
reversible — including the edge-collision case (a repoint landing on a
pre-existing canonical edge, which the loader's `SET r += props` would otherwise
make un-undoable by edge-ids alone).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from dedup_merge_applier import (  # noqa: E402
    apply_accepted,
    apply_component_merge,
    apply_component_merge_live,
    build_merge_cypher,
    canonical_graph,
    rollback_component_merge,
)
from dedup_org_candidates import assemble_components  # noqa: E402


class _FakeSession:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self._calls["statements"].append((cypher, params))
        return None


def _fake_driver_recording_db():
    calls = {"database": "__UNSCOPED__", "statements": []}
    driver = type("D", (), {})()

    def session(**kwargs):
        calls["database"] = kwargs.get("database", "__UNSCOPED__")
        return _FakeSession(calls)

    driver.session = session
    return driver, calls


def _node(node_id, **props):
    return {"id": node_id, "labels": ["Organization"], "properties": dict(props)}


def _node_ref(node_id, **fields):
    return {"id": node_id, "display_label": node_id, **fields}


def _graph(nodes, edges):
    return {
        "nodes": {n["id"]: n for n in nodes},
        "edges": {tuple(k): dict(p) for k, p in edges.items()},
    }


def test_repoint_no_collision_then_rollback_is_byte_identical():
    graph = _graph(
        [_node("org-canon", ein="1", degree=9), _node("org-dup", ein="1", degree=2),
         _node("dept-x")],
        {("dept-x", "FROM_SOURCE", "org-dup"): {"w": 1},
         ("org-dup", "TO_TARGET", "dept-x"): {"amount": 5}},
    )
    original = canonical_graph(copy.deepcopy(graph))
    comp = {"members": ["org-canon", "org-dup"], "canonical": "org-canon"}

    record = apply_component_merge(graph, comp)

    # edges repointed onto the canonical; old dup-edges gone
    assert ("dept-x", "FROM_SOURCE", "org-canon") in graph["edges"]
    assert ("org-canon", "TO_TARGET", "dept-x") in graph["edges"]
    assert ("dept-x", "FROM_SOURCE", "org-dup") not in graph["edges"]
    assert ("org-dup", "TO_TARGET", "dept-x") not in graph["edges"]
    # dup tombstoned by PROPERTY; :Organization label KEPT (Codex r5)
    assert graph["nodes"]["org-dup"]["properties"]["dedup_superseded_by"] == "org-canon"
    assert "Organization" in graph["nodes"]["org-dup"]["labels"]

    rollback_component_merge(graph, record)
    assert canonical_graph(graph) == original


def test_edge_collision_collapse_then_rollback_restores_both_edges_and_props():
    # both dup and canonical have a TO_TARGET edge to dept-x, with DIFFERENT props
    graph = _graph(
        [_node("org-canon", ein="1", degree=9), _node("org-dup", ein="1", degree=2),
         _node("dept-x")],
        {("org-canon", "TO_TARGET", "dept-x"): {"amount": 100, "note": "canon"},
         ("org-dup", "TO_TARGET", "dept-x"): {"amount": 5}},
    )
    original = canonical_graph(copy.deepcopy(graph))
    comp = {"members": ["org-canon", "org-dup"], "canonical": "org-canon"}

    record = apply_component_merge(graph, comp)

    # collapsed onto one canonical edge; loader SET r += props => repointed wins on conflict
    assert ("org-dup", "TO_TARGET", "dept-x") not in graph["edges"]
    merged = graph["edges"][("org-canon", "TO_TARGET", "dept-x")]
    assert merged == {"amount": 5, "note": "canon"}  # dup amount wins; canon note retained

    # the preimage must capture the destination pre-existed + its prior props
    rollback_component_merge(graph, record)
    assert canonical_graph(graph) == original


def test_selfloop_from_dup_canonical_edge_is_dropped_and_restored():
    # a direct dup<->canonical edge becomes a self-loop on merge -> dropped
    graph = _graph(
        [_node("org-canon", ein="1", degree=9), _node("org-dup", ein="1", degree=2)],
        {("org-dup", "SAME_AS", "org-canon"): {"basis": "x"}},
    )
    original = canonical_graph(copy.deepcopy(graph))
    comp = {"members": ["org-canon", "org-dup"], "canonical": "org-canon"}

    record = apply_component_merge(graph, comp)
    assert ("org-canon", "SAME_AS", "org-canon") not in graph["edges"]  # self-loop dropped
    assert ("org-dup", "SAME_AS", "org-canon") not in graph["edges"]

    rollback_component_merge(graph, record)
    assert canonical_graph(graph) == original


def _two_node_graph():
    return _graph(
        [_node("org-canon", ein="1", degree=9), _node("org-dup", ein="1", degree=2),
         _node("x")],
        {("org-dup", "TO_TARGET", "x"): {"amount": 5}},
    )


def test_dry_run_default_reports_plan_with_zero_mutation():
    graph = _two_node_graph()
    before = canonical_graph(copy.deepcopy(graph))
    assembly = {"accepted": [{"members": ["org-canon", "org-dup"], "canonical": "org-canon"}],
                "refused": []}

    result = apply_accepted(graph, assembly)  # dry_run defaults True

    assert result["dry_run"] is True
    assert result["plan"][0]["canonical_id"] == "org-canon"
    assert result["plan"][0]["superseded_ids"] == ["org-dup"]
    assert canonical_graph(graph) == before  # NOTHING mutated


def test_apply_accepted_mutates_only_when_dry_run_false():
    graph = _two_node_graph()
    assembly = {"accepted": [{"members": ["org-canon", "org-dup"], "canonical": "org-canon"}],
                "refused": []}

    result = apply_accepted(graph, assembly, dry_run=False)

    assert result["dry_run"] is False
    assert len(result["merge_records"]) == 1
    assert graph["nodes"]["org-dup"]["properties"]["dedup_superseded_by"] == "org-canon"


def test_egress_gate_both_ways_only_deterministic_or_approved_reach_graph():
    refs = {r["id"]: r for r in [
        _node_ref("org-a", ein="1", degree=9), _node_ref("org-b", ein="1", degree=2),
    ]}
    def fresh_graph():
        return _graph(
            [_node("org-a", ein="1", degree=9), _node("org-b", ein="1", degree=2), _node("x")],
            {("org-b", "TO_TARGET", "x"): {"amount": 5}},
        )

    # queued/rejected -> NO accepted component -> graph unchanged
    g1 = fresh_graph()
    before = canonical_graph(copy.deepcopy(g1))
    queued = assemble_components(
        [{"subject_ref": "org-a", "target_ref": "org-b", "status": "queued",
          "basis": "org_dedup_operator_approved"}], refs)
    apply_accepted(g1, queued, dry_run=False)
    assert canonical_graph(g1) == before  # untouched

    # deterministic -> accepted -> graph mutated
    g2 = fresh_graph()
    det = assemble_components(
        [{"subject_ref": "org-a", "target_ref": "org-b", "status": "deterministic",
          "basis": "org_dedup_key_exact"}], refs)
    apply_accepted(g2, det, dry_run=False)
    assert "dedup_superseded_by" in g2["nodes"]["org-b"]["properties"]


def test_three_node_component_repoints_all_dups():
    graph = _graph(
        [_node("org-a", ein="1", degree=9), _node("org-b", ein="1", degree=2),
         _node("org-c", ein="1", degree=1), _node("x")],
        {("org-b", "TO_TARGET", "x"): {"amount": 1},
         ("org-c", "TO_TARGET", "x"): {"amount": 2}},
    )
    original = canonical_graph(copy.deepcopy(graph))
    comp = {"members": ["org-a", "org-b", "org-c"], "canonical": "org-a"}

    record = apply_component_merge(graph, comp)
    # both b and c collapse onto a single canonical->x edge
    assert ("org-a", "TO_TARGET", "x") in graph["edges"]
    assert graph["nodes"]["org-b"]["properties"]["dedup_superseded_by"] == "org-a"
    assert graph["nodes"]["org-c"]["properties"]["dedup_superseded_by"] == "org-a"

    rollback_component_merge(graph, record)
    assert canonical_graph(graph) == original


# ---------------------------------------------------------------------------
# Unit 5 — live-Cypher mode (operator-gated; fake-session-tested; db-scoped)
# ---------------------------------------------------------------------------

def test_build_merge_cypher_tombstones_and_repoints():
    comp = {"members": ["org-canon", "org-dup"], "canonical": "org-canon"}
    stmts = build_merge_cypher(comp)
    blob = " ".join(s["cypher"] for s in stmts)
    # tombstone via property (label KEPT — no DELETE / no REMOVE :Organization)
    assert "dedup_superseded_by" in blob
    assert "DELETE d" not in blob and "REMOVE" not in blob
    # repoint uses apoc for dynamic rel types; every statement carries the pair
    assert "apoc.merge.relationship" in blob
    assert all(s["params"].get("dup") == "org-dup" for s in stmts)
    assert all(s["params"].get("canonical") == "org-canon" for s in stmts)


def test_live_applier_uses_database_scoped_session():
    driver, calls = _fake_driver_recording_db()
    comp = {"members": ["org-canon", "org-dup"], "canonical": "org-canon"}
    apply_component_merge_live(driver, comp, database="scratchdb", confirm=True)
    assert calls["database"] == "scratchdb"          # never a bare session
    assert len(calls["statements"]) == len(build_merge_cypher(comp))


def test_live_applier_requires_database_and_confirm():
    driver, _ = _fake_driver_recording_db()
    comp = {"members": ["org-canon", "org-dup"], "canonical": "org-canon"}
    with pytest.raises(ValueError):
        apply_component_merge_live(driver, comp, database=None, confirm=True)   # unscoped forbidden
    with pytest.raises(ValueError):
        apply_component_merge_live(driver, comp, database="scratchdb", confirm=False)  # operator gate


def test_no_top_level_neo4j_import():
    src = (Path(__file__).resolve().parents[2] / "scripts" / "dedup_merge_applier.py").read_text()
    for line in src.splitlines():
        stripped = line.strip()
        assert not stripped.startswith(("import neo4j", "from neo4j"))
