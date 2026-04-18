"""Tests for load_neo4j_v2.py — batched Neo4j loader with UNWIND writes.

TDD: tests written first, implementation follows.

Covers pure functions only — no actual Neo4j connection required:
  - chunk_list: even split, remainder, empty
  - build_node_batch_query: single label, multi-label
  - build_edge_batch_query: basic query structure
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from load_neo4j_v2 import (
    build_edge_batch_query,
    build_node_batch_query,
    chunk_list,
    validate_edge_endpoints,
)


class TestChunkList:
    """chunk_list splits a list into successive chunks of the given size."""

    def test_even_split(self):
        result = list(chunk_list([1, 2, 3, 4], 2))
        assert result == [[1, 2], [3, 4]]

    def test_remainder(self):
        result = list(chunk_list([1, 2, 3], 2))
        assert result == [[1, 2], [3]]

    def test_empty(self):
        result = list(chunk_list([], 2))
        assert result == []

    def test_chunk_larger_than_list(self):
        result = list(chunk_list([1, 2], 10))
        assert result == [[1, 2]]

    def test_chunk_size_one(self):
        result = list(chunk_list([1, 2, 3], 1))
        assert result == [[1], [2], [3]]

    def test_single_item(self):
        result = list(chunk_list([42], 5))
        assert result == [[42]]


class TestBuildNodeBatchQuery:
    """build_node_batch_query returns a MERGE+SET Cypher query for UNWIND batches."""

    def test_single_label_returns_tuple(self):
        result = build_node_batch_query("Decision", ["Decision"])
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_single_label_unwind(self):
        query, params = build_node_batch_query("Decision", ["Decision"])
        assert "UNWIND $batch AS row" in query

    def test_single_label_merge(self):
        query, params = build_node_batch_query("Decision", ["Decision"])
        assert "MERGE (n:Decision {id: row.id})" in query

    def test_single_label_set_props(self):
        query, params = build_node_batch_query("Decision", ["Decision"])
        assert "SET n += row.props" in query

    def test_single_label_set_display_label(self):
        query, params = build_node_batch_query("Decision", ["Decision"])
        assert "SET n.display_label = row.display_label" in query

    def test_single_label_set_promotion_state(self):
        query, params = build_node_batch_query("Decision", ["Decision"])
        assert "SET n.promotion_state = row.promotion_state" in query

    def test_single_label_set_label(self):
        query, params = build_node_batch_query("Decision", ["Decision"])
        assert "SET n:Decision" in query

    def test_multi_label_merge_uses_primary(self):
        query, params = build_node_batch_query("Organization", ["Organization", "Government"])
        assert "MERGE (n:Organization {id: row.id})" in query

    def test_multi_label_set_all_labels(self):
        query, params = build_node_batch_query("Organization", ["Organization", "Government"])
        assert "SET n:Organization:Government" in query

    def test_multi_label_set_props(self):
        query, params = build_node_batch_query("Organization", ["Organization", "Government"])
        assert "SET n += row.props" in query

    def test_params_is_dict(self):
        query, params = build_node_batch_query("Decision", ["Decision"])
        assert isinstance(params, dict)

    def test_person_single_label(self):
        query, params = build_node_batch_query("Person", ["Person"])
        assert "MERGE (n:Person {id: row.id})" in query
        assert "SET n:Person" in query


class TestBuildEdgeBatchQuery:
    """build_edge_batch_query returns a MERGE+SET Cypher query for UNWIND batches."""

    def test_returns_string(self):
        query = build_edge_batch_query("CAST_VOTE")
        assert isinstance(query, str)

    def test_unwind(self):
        query = build_edge_batch_query("CAST_VOTE")
        assert "UNWIND $batch AS row" in query

    def test_match_source(self):
        query = build_edge_batch_query("CAST_VOTE")
        assert "MATCH (s {id: row.source_id})" in query

    def test_match_target(self):
        query = build_edge_batch_query("CAST_VOTE")
        assert "MATCH (t {id: row.target_id})" in query

    def test_merge_relationship(self):
        query = build_edge_batch_query("CAST_VOTE")
        assert "MERGE (s)-[r:CAST_VOTE]->(t)" in query

    def test_set_props(self):
        query = build_edge_batch_query("CAST_VOTE")
        assert "SET r += row.props" in query

    def test_different_rel_type(self):
        query = build_edge_batch_query("PARTY_TO")
        assert "MERGE (s)-[r:PARTY_TO]->(t)" in query

    def test_decided_by(self):
        query = build_edge_batch_query("DECIDED_BY")
        assert "MERGE (s)-[r:DECIDED_BY]->(t)" in query
        assert "MATCH (s {id: row.source_id})" in query
        assert "MATCH (t {id: row.target_id})" in query


class TestValidateEdgeEndpoints:
    """validate_edge_endpoints detects edges pointing to missing nodes."""

    def test_all_valid_returns_empty(self):
        node_ids = {"node-1", "node-2", "node-3"}
        edges = [
            {"source_id": "node-1", "target_id": "node-2", "relationship_type": "LINKS"},
            {"source_id": "node-2", "target_id": "node-3", "relationship_type": "LINKS"},
        ]
        result = validate_edge_endpoints(node_ids, edges)
        assert result["missing_sources"] == []
        assert result["missing_targets"] == []
        assert result["total_broken"] == 0

    def test_detects_missing_source(self):
        node_ids = {"node-1", "node-2"}
        edges = [
            {"source_id": "node-gone", "target_id": "node-2", "relationship_type": "LINKS"},
        ]
        result = validate_edge_endpoints(node_ids, edges)
        assert len(result["missing_sources"]) == 1
        assert result["missing_sources"][0]["source_id"] == "node-gone"
        assert result["total_broken"] == 1

    def test_detects_missing_target(self):
        node_ids = {"node-1", "node-2"}
        edges = [
            {"source_id": "node-1", "target_id": "node-gone", "relationship_type": "LINKS"},
        ]
        result = validate_edge_endpoints(node_ids, edges)
        assert len(result["missing_targets"]) == 1
        assert result["missing_targets"][0]["target_id"] == "node-gone"

    def test_both_endpoints_missing(self):
        node_ids = {"node-1"}
        edges = [
            {"source_id": "gone-a", "target_id": "gone-b", "relationship_type": "LINKS"},
        ]
        result = validate_edge_endpoints(node_ids, edges)
        assert len(result["missing_sources"]) == 1
        assert len(result["missing_targets"]) == 1
        assert result["total_broken"] == 1

    def test_groups_by_relationship_type(self):
        node_ids = {"node-1"}
        edges = [
            {"source_id": "node-1", "target_id": "gone-a", "relationship_type": "EVIDENCED_BY"},
            {"source_id": "node-1", "target_id": "gone-b", "relationship_type": "EVIDENCED_BY"},
            {"source_id": "gone-c", "target_id": "node-1", "relationship_type": "FROM_SOURCE"},
        ]
        result = validate_edge_endpoints(node_ids, edges)
        assert result["total_broken"] == 3
        assert "EVIDENCED_BY" in result["by_relationship"]
        assert result["by_relationship"]["EVIDENCED_BY"] == 2
        assert result["by_relationship"]["FROM_SOURCE"] == 1

    def test_empty_edges(self):
        result = validate_edge_endpoints({"node-1"}, [])
        assert result["total_broken"] == 0

    def test_empty_nodes(self):
        edges = [
            {"source_id": "a", "target_id": "b", "relationship_type": "X"},
        ]
        result = validate_edge_endpoints(set(), edges)
        assert result["total_broken"] == 1
