"""Tests for migrate_graph_v2.py — migration orchestrator.

TDD: tests written first, implementation follows.

Covers:
  - All 4 output files are created
  - Node count: 5 input → 4 output (CaseParticipation dropped)
  - Edge count: 4 input → 3 output (2 remapped + 1 new PARTY_TO, 2 casepart edges dropped)
  - ID map: actor- and inst- prefixes remapped, unchanged IDs absent
  - Second-pass actor-ref remap in node properties
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from migrate_graph_v2 import run_migration


# ---------------------------------------------------------------------------
# Fixture: mini_graph
# ---------------------------------------------------------------------------

@pytest.fixture
def mini_graph(tmp_path):
    """Write small JSONL files to tmp_path and return (nodes_path, edges_path, output_dir)."""
    nodes = [
        {
            "id": "actor-kate-colin",
            "node_type": "Actor",
            "display_label": "Kate Colin",
            "promotion_state": "canonical",
            "source_bundle_ids": ["test"],
            "source_sections": ["actor_candidates"],
            "source_status": None,
            "properties": {
                "actor_type": "person",
                "name": "Kate Colin",
                "observed_labels": ["Kate Colin"],
                "payload_json": "{}",
            },
        },
        {
            "id": "inst-san-rafael-city-council",
            "node_type": "Institution",
            "display_label": "San Rafael City Council",
            "promotion_state": "canonical",
            "source_bundle_ids": ["test"],
            "source_sections": ["institution_candidates"],
            "source_status": None,
            "properties": {
                "institution_type": "council",
                "name": "San Rafael City Council",
                "payload_json": "{}",
            },
        },
        {
            "id": "decision-2024-08-19-resolution-15336",
            "node_type": "Decision",
            "display_label": "Resolution 15336",
            "promotion_state": "promoted",
            "source_bundle_ids": ["test"],
            "source_sections": ["decision_candidates"],
            "source_status": None,
            "properties": {
                "decided_at": "2024-08-19",
                "institution_id": "inst-san-rafael-city-council",
                "payload_json": "{}",
            },
        },
        {
            "id": "casepart-boyd-city-defendant",
            "node_type": "CaseParticipation",
            "display_label": "casepart-boyd-city-defendant",
            "promotion_state": "promoted",
            "source_bundle_ids": ["test"],
            "source_sections": ["case_participation_candidates"],
            "source_status": None,
            "properties": {
                "case_id": "case-boyd",
                "institution_id": "inst-san-rafael-city-council",
                "role": "defendant",
                "payload_json": "{}",
            },
        },
        {
            "id": "case-boyd",
            "node_type": "Case",
            "display_label": "Boyd v. City of San Rafael",
            "promotion_state": "promoted",
            "source_bundle_ids": ["test"],
            "source_sections": ["case_candidates"],
            "source_status": None,
            "properties": {
                "case_type": "civil",
                "payload_json": "{}",
            },
        },
    ]
    edges = [
        {
            "source_id": "actor-kate-colin",
            "source_node_type": "Actor",
            "target_id": "decision-2024-08-19-resolution-15336",
            "target_node_type": "Decision",
            "relationship_type": "CAST_VOTE_ON",
            "source_bundle_ids": ["test"],
            "source_fields": ["votes"],
            "properties": {"vote": "yes"},
        },
        {
            "source_id": "decision-2024-08-19-resolution-15336",
            "source_node_type": "Decision",
            "target_id": "inst-san-rafael-city-council",
            "target_node_type": "Institution",
            "relationship_type": "DECIDED_BY_INSTITUTION",
            "source_bundle_ids": ["test"],
            "source_fields": ["institution_id"],
            "properties": {},
        },
        {
            "source_id": "casepart-boyd-city-defendant",
            "source_node_type": "CaseParticipation",
            "target_id": "case-boyd",
            "target_node_type": "Case",
            "relationship_type": "PART_OF_CASE",
            "source_bundle_ids": ["test"],
            "source_fields": ["case_id"],
            "properties": {},
        },
        {
            "source_id": "casepart-boyd-city-defendant",
            "source_node_type": "CaseParticipation",
            "target_id": "record-dismissal",
            "target_node_type": "Record",
            "relationship_type": "EVIDENCED_BY",
            "source_bundle_ids": ["test"],
            "source_fields": ["evidence_record_ids"],
            "properties": {},
        },
    ]

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    nodes_path = input_dir / "nodes.jsonl"
    edges_path = input_dir / "edges.jsonl"

    nodes_path.write_text("\n".join(json.dumps(n) for n in nodes) + "\n")
    edges_path.write_text("\n".join(json.dumps(e) for e in edges) + "\n")

    return nodes_path, edges_path, output_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMigrationOutputFiles:
    """All 4 output files are created."""

    def test_migration_output_files(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        assert (output_dir / "nodes.jsonl").exists(), "nodes.jsonl not created"
        assert (output_dir / "edges.jsonl").exists(), "edges.jsonl not created"
        assert (output_dir / "id-map.json").exists(), "id-map.json not created"
        assert (output_dir / "migration-report.json").exists(), "migration-report.json not created"


class TestMigrationNodeCounts:
    """5 input nodes → 4 output nodes (CaseParticipation dropped)."""

    def test_migration_node_counts(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        nodes = _read_jsonl(output_dir / "nodes.jsonl")
        assert len(nodes) == 4, f"Expected 4 nodes, got {len(nodes)}"

    def test_no_case_participation_in_output(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        nodes = _read_jsonl(output_dir / "nodes.jsonl")
        node_types = {n["node_type"] for n in nodes}
        assert "CaseParticipation" not in node_types

    def test_report_records_source_node_count(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        report = run_migration(nodes_path, edges_path, output_dir)

        assert report["source_node_count"] == 5
        assert report["migrated_node_count"] == 4


class TestMigrationEdgeCounts:
    """4 input edges → 3 output edges (2 remapped + 1 PARTY_TO, 2 casepart edges dropped)."""

    def test_migration_edge_counts(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        edges = _read_jsonl(output_dir / "edges.jsonl")
        assert len(edges) == 3, f"Expected 3 edges, got {len(edges)}"

    def test_party_to_edge_present(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        edges = _read_jsonl(output_dir / "edges.jsonl")
        rel_types = {e["relationship_type"] for e in edges}
        assert "PARTY_TO" in rel_types

    def test_no_part_of_case_edges_in_output(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        edges = _read_jsonl(output_dir / "edges.jsonl")
        rel_types = {e["relationship_type"] for e in edges}
        assert "PART_OF_CASE" not in rel_types

    def test_no_evidenced_by_from_casepart(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        edges = _read_jsonl(output_dir / "edges.jsonl")
        for e in edges:
            assert not e["source_id"].startswith("casepart-"), (
                f"casepart- source survived in edge: {e}"
            )

    def test_report_records_edge_counts(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        report = run_migration(nodes_path, edges_path, output_dir)

        assert report["source_edge_count"] == 4
        assert report["migrated_edge_count"] == 3


class TestMigrationIdMap:
    """actor- and inst- IDs remapped; unchanged IDs absent from map."""

    def test_actor_remapped_in_id_map(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        id_map = json.loads((output_dir / "id-map.json").read_text())
        assert id_map.get("actor-kate-colin") == "person-kate-colin"

    def test_institution_remapped_in_id_map(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        id_map = json.loads((output_dir / "id-map.json").read_text())
        assert id_map.get("inst-san-rafael-city-council") == "org-san-rafael-city-council"

    def test_unchanged_ids_not_in_map(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        id_map = json.loads((output_dir / "id-map.json").read_text())
        assert "decision-2024-08-19-resolution-15336" not in id_map
        assert "case-boyd" not in id_map


class TestMigrationActorRefSecondPass:
    """Decision with institution_id pointing to inst- gets it remapped in final output."""

    def test_decision_institution_id_remapped_in_output(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        nodes = _read_jsonl(output_dir / "nodes.jsonl")
        decisions = [n for n in nodes if n["node_type"] == "Decision"]
        assert len(decisions) == 1
        assert decisions[0]["properties"]["institution_id"] == "org-san-rafael-city-council"

    def test_cast_vote_source_remapped(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        edges = _read_jsonl(output_dir / "edges.jsonl")
        cast_vote_edges = [e for e in edges if e["relationship_type"] == "CAST_VOTE"]
        assert len(cast_vote_edges) == 1
        assert cast_vote_edges[0]["source_id"] == "person-kate-colin"

    def test_decided_by_target_remapped(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        edges = _read_jsonl(output_dir / "edges.jsonl")
        decided_edges = [e for e in edges if e["relationship_type"] == "DECIDED_BY"]
        assert len(decided_edges) == 1
        assert decided_edges[0]["target_id"] == "org-san-rafael-city-council"


class TestMigrationReport:
    """Migration report contains expected keys and values."""

    def test_report_has_required_keys(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        report = run_migration(nodes_path, edges_path, output_dir)

        required = {
            "source_node_count",
            "migrated_node_count",
            "source_edge_count",
            "migrated_edge_count",
            "dropped_node_count",
            "dropped_edge_count",
            "conversion_count",
            "nodes_by_type",
            "edges_by_type",
        }
        assert required.issubset(set(report.keys()))

    def test_report_dropped_node_count(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        report = run_migration(nodes_path, edges_path, output_dir)

        # 1 CaseParticipation dropped
        assert report["dropped_node_count"] == 1

    def test_report_dropped_edge_count(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        report = run_migration(nodes_path, edges_path, output_dir)

        # 2 casepart edges dropped (PART_OF_CASE + EVIDENCED_BY from casepart-)
        assert report["dropped_edge_count"] == 2

    def test_report_conversion_count(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        report = run_migration(nodes_path, edges_path, output_dir)

        # 1 CaseParticipation converted to PARTY_TO edge
        assert report["conversion_count"] == 1

    def test_report_written_to_disk(self, mini_graph):
        nodes_path, edges_path, output_dir = mini_graph
        run_migration(nodes_path, edges_path, output_dir)

        report_path = output_dir / "migration-report.json"
        assert report_path.exists()
        on_disk = json.loads(report_path.read_text())
        assert on_disk["source_node_count"] == 5
