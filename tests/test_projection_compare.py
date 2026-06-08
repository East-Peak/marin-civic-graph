"""B3 — projection_compare.py: a full-field-set, multiset projection comparator.

This is NOT graph_compare.compare_graphs (which is for DB exports and KeyErrors
on source_id/relationship_type). It compares the FULL projection dicts
field-for-field as multisets, ignoring no field. Nodes compare labels
order-insensitively; everything else (including edge id / source_bundle_ids /
source_fields) is compared exactly.

TDD: written before scripts/projection_compare.py exists.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from projection_compare import compare_projection, projection_digest


def _node(**over):
    n = {
        "id": "person-a", "node_type": "Person", "labels": ["Person"],
        "display_label": "A", "promotion_state": "canonical",
        "source_bundle_ids": ["b1"], "source_sections": ["s1"],
        "source_status": None, "properties": {"x": 1, "payload_json": "{}"},
        "qa_lane": False,
    }
    n.update(over)
    return n


def _edge(**over):
    e = {
        "source_id": "person-a", "source_node_type": "Person",
        "target_id": "org-b", "target_node_type": "Organization",
        "relationship_type": "HELD_BY", "source_bundle_ids": ["b1"],
        "source_fields": ["actor_id"], "properties": {"k": "v"},
    }
    e.update(over)
    return e


def test_identical_projections_are_equivalent():
    n = [_node()]
    e = [_edge()]
    result = compare_projection(n, e, [dict(_node())], [dict(_edge())])
    assert result.equivalent
    assert not result.node_only_in_golden and not result.node_only_in_candidate
    assert not result.edge_only_in_golden and not result.edge_only_in_candidate


def test_node_field_difference_is_detected():
    result = compare_projection([_node()], [], [_node(display_label="DIFFERENT")], [])
    assert not result.equivalent
    assert result.node_only_in_golden and result.node_only_in_candidate


def test_node_property_difference_is_detected():
    result = compare_projection([_node()], [], [_node(properties={"x": 2, "payload_json": "{}"})], [])
    assert not result.equivalent


def test_label_order_is_ignored():
    g = [_node(labels=["Organization", "Court"])]
    c = [_node(labels=["Court", "Organization"])]
    assert compare_projection(g, c, g, c) is not None  # smoke
    result = compare_projection(g, [], c, [])
    assert result.equivalent, "labels must compare order-insensitively"


def test_missing_edge_is_detected_as_multiset():
    g = [_edge(), _edge(target_id="org-c")]
    c = [_edge()]
    result = compare_projection([], g, [], c)
    assert not result.equivalent
    assert len(result.edge_only_in_golden) == 1
    assert not result.edge_only_in_candidate


def test_duplicate_count_mismatch_is_detected():
    g = [_edge(), _edge()]   # same edge twice
    c = [_edge()]            # only once
    result = compare_projection([], g, [], c)
    assert not result.equivalent
    assert len(result.edge_only_in_golden) == 1  # one surplus in golden


def test_edge_id_field_not_ignored():
    # PARTY_TO-style edges carry an id + no source_bundle_ids; the id must matter.
    g = [{"id": "edge-x", "relationship_type": "PARTY_TO", "source_id": "person-a",
          "target_id": "case-1", "source_node_type": "Person",
          "target_node_type": "Case", "properties": {}}]
    c = [{"id": "edge-DIFFERENT", "relationship_type": "PARTY_TO", "source_id": "person-a",
          "target_id": "case-1", "source_node_type": "Person",
          "target_node_type": "Case", "properties": {}}]
    result = compare_projection([], g, [], c)
    assert not result.equivalent, "edge id must not be silently ignored"


def test_source_fields_not_ignored():
    result = compare_projection([], [_edge()], [], [_edge(source_fields=["other_field"])])
    assert not result.equivalent


def test_summary_is_human_readable_string():
    result = compare_projection([_node()], [], [_node(display_label="Z")], [])
    assert isinstance(result.summary, str)
    assert "node" in result.summary.lower()


# ---------------------------------------------------------------------------
# projection_digest — canonical (sorted-key JSON, NOT raw bytes) regression hash
# ---------------------------------------------------------------------------

def test_projection_digest_reports_counts_and_two_hashes():
    digest = projection_digest([_node(), _node(id="person-b")], [_edge()])
    assert digest["node_count"] == 2
    assert digest["edge_count"] == 1
    assert isinstance(digest["nodes_sha256"], str) and len(digest["nodes_sha256"]) == 64
    assert isinstance(digest["edges_sha256"], str) and len(digest["edges_sha256"]) == 64


def test_projection_digest_is_row_order_insensitive():
    # Same multiset of rows in a different order -> identical digest. This is
    # the whole point of a CANONICAL digest: it tracks compare_projection's
    # multiset equivalence, not raw file byte order.
    a = projection_digest([_node(id="person-a"), _node(id="person-b")], [_edge()])
    b = projection_digest([_node(id="person-b"), _node(id="person-a")], [_edge()])
    assert a == b


def test_projection_digest_is_label_order_insensitive():
    a = projection_digest([_node(labels=["Organization", "Court"])], [])
    b = projection_digest([_node(labels=["Court", "Organization"])], [])
    assert a["nodes_sha256"] == b["nodes_sha256"]


def test_projection_digest_detects_value_change():
    base = projection_digest([_node()], [_edge()])
    changed_node = projection_digest([_node(display_label="DIFFERENT")], [_edge()])
    changed_edge = projection_digest([_node()], [_edge(source_fields=["other"])])
    assert base["nodes_sha256"] != changed_node["nodes_sha256"]
    assert base["edges_sha256"] != changed_edge["edges_sha256"]
