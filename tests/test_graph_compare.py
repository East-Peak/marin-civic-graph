import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from graph_compare import compare_graphs, VOLATILE_PROPS

BASE_NODES = [{"id": "person-a", "labels": ["Person"], "props": {"name": "A", "ingested_at": "t1"}}]
BASE_RELS  = [{"source": "person-a", "target": "filing-1", "type": "FILED_BY", "props": {}}]


def test_identical_graphs_are_equivalent():
    r = compare_graphs(BASE_NODES, BASE_RELS, BASE_NODES, BASE_RELS)
    assert r.equivalent and not r.diffs


def test_volatile_prop_difference_is_ignored():
    other = [{"id": "person-a", "labels": ["Person"], "props": {"name": "A", "ingested_at": "t2"}}]
    assert compare_graphs(BASE_NODES, BASE_RELS, other, BASE_RELS).equivalent


def test_real_prop_mutation_fails():   # MUTATION TEST — must catch silent corruption
    other = [{"id": "person-a", "labels": ["Person"], "props": {"name": "B", "ingested_at": "t1"}}]
    assert not compare_graphs(BASE_NODES, BASE_RELS, other, BASE_RELS).equivalent


def test_missing_node_fails():
    assert not compare_graphs(BASE_NODES, BASE_RELS, [], BASE_RELS).equivalent


def test_rel_prop_mutation_fails():
    other = [{"source": "person-a", "target": "filing-1", "type": "FILED_BY", "props": {"role": "x"}}]
    assert not compare_graphs(BASE_NODES, BASE_RELS, BASE_NODES, other).equivalent


def test_missing_rel_fails():
    assert not compare_graphs(BASE_NODES, BASE_RELS, BASE_NODES, []).equivalent


def test_rels_compared_as_order_insensitive_multiset():
    # Neo4j export order isn't stable, so identical rels in a different order
    # must still be equivalent (multiset, not an order-sensitive index).
    r1 = {"source": "p", "target": "f1", "type": "FILED_BY", "props": {}}
    r2 = {"source": "p", "target": "f2", "type": "FILED_BY", "props": {}}
    assert compare_graphs([], [r1, r2], [], [r2, r1]).equivalent


def test_rels_multiset_counts_duplicates():
    # A rel present twice in base but once in new is NOT equivalent — a set
    # would wrongly pass this; the comparison must be a multiset.
    r = {"source": "p", "target": "f1", "type": "FILED_BY", "props": {}}
    assert not compare_graphs([], [r, r], [], [r]).equivalent


def test_denylist_is_small_and_fixed():
    assert VOLATILE_PROPS == frozenset({"ingested_at", "captured_at", "run_id", "_loaded_at"})
