"""load_edges must use constraint-backed (labeled) endpoint lookups.

Unlabeled `MATCH (s {id: ...})` can't use Neo4j's per-label id constraints and
scans every node per row: the first weekly load (2026-09-28) spent ~49s per
500-edge batch on 51K permit edges. Same root cause as the July restore wedge.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from load_neo4j_v2 import build_edge_batch_query, load_edges  # noqa: E402


class _Result(list):
    def single(self):
        return self[0] if self else None


class FakeSession:
    """Resolves ids against a {label: {ids}} graph; records every query."""

    def __init__(self, graph):
        self.graph = graph
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.queries.append((query, params))
        if query.startswith("SHOW CONSTRAINTS"):
            return _Result([{"labelsOrTypes": [l], "properties": ["id"]} for l in self.graph])
        if "RETURN n.id AS id" in query:
            label = query.split("(n:`")[1].split("`")[0]
            return _Result([{"id": i} for i in params["ids"] if i in self.graph[label]])
        return _Result([])


class FakeDriver:
    def __init__(self, graph):
        self.s = FakeSession(graph)

    def session(self, **kw):
        return self.s


GRAPH = {"Project": {"permit-1", "permit-2"}, "Place": {"place-san-rafael"}}


def _edges(*pairs, rel="IN_JURISDICTION"):
    return [{"source_id": s, "target_id": t, "relationship_type": rel} for s, t in pairs]


def test_every_edge_write_matches_labeled_endpoints():
    driver = FakeDriver(GRAPH)
    load_edges(driver, _edges(("permit-1", "place-san-rafael"), ("permit-2", "place-san-rafael")))
    writes = [q for q, _ in driver.s.queries if "MERGE" in q]
    assert writes, "expected edge writes"
    for q in writes:
        assert "MATCH (s {id" not in q and "MATCH (t {id" not in q
        assert "MATCH (s:`Project` {id: row.source_id})" in q
        assert "MATCH (t:`Place` {id: row.target_id})" in q


def test_label_resolution_queries_are_labeled_too():
    driver = FakeDriver(GRAPH)
    load_edges(driver, _edges(("permit-1", "place-san-rafael")))
    lookups = [q for q, _ in driver.s.queries if "RETURN n.id AS id" in q]
    assert lookups and all("(n:`" in q for q in lookups)


def test_unresolved_endpoints_are_skipped_and_counted_not_silently_dropped():
    driver = FakeDriver(GRAPH)
    counts = load_edges(driver, _edges(("permit-1", "place-san-rafael"), ("permit-404", "place-san-rafael")))
    assert counts["IN_JURISDICTION"] == 1
    assert counts["unresolved_endpoint"] == 1


def test_unlabeled_builder_still_available_for_compatibility():
    assert "MATCH (s {id: row.source_id})" in build_edge_batch_query("CAST_VOTE")
    labeled = build_edge_batch_query("CAST_VOTE", "Person", "Decision")
    assert "MATCH (s:`Person` {id: row.source_id})" in labeled
    assert "MATCH (t:`Decision` {id: row.target_id})" in labeled
