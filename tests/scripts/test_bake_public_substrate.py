"""Tests for the public substrate bake skeleton.

The fixture mirrors the graph-v2 + attach-overlay JSONL shape but stays tiny so
the S0 TDD loop can stay targeted.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from bake_public_substrate import bake_substrate  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _write_registry(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "graph_node_types": {
                    "Organization": {
                        "searchable": True,
                        "outbound_eligible": True,
                    },
                    "Person": {
                        "searchable": True,
                        "outbound_eligible": True,
                    },
                    "Membership": {
                        "searchable": False,
                        "outbound_eligible": True,
                    },
                    "EconomicInterest": {
                        "searchable": False,
                        "outbound_eligible": True,
                    },
                },
                "support_labels": ["ValidationCheck"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _fixture(tmp_path: Path) -> tuple[list[Path], list[Path], Path, Path, Path]:
    projection_nodes = [
        {
            "id": "org-target",
            "node_type": "Organization",
            "labels": ["Organization"],
            "display_label": "Target Org",
            "promotion_state": "promoted",
            "properties": {
                "name": "Target Org",
                "embedding": [0.1, 0.2],
                "umap_x": 12.3,
                "search_pending": True,
                "payload_json": "{\"private\":\"loader-strips-this\"}",
            },
        },
        {
            "id": "person-a",
            "node_type": "Person",
            "labels": ["Person"],
            "display_label": "Person A",
            "promotion_state": "promoted",
            "properties": {"name": "Person A"},
        },
    ]
    projection_edges = [
        {
            "source_id": "person-a",
            "relationship_type": "MEMBER",
            "target_id": "org-target",
            "properties": {},
        },
        {
            "source_id": "org-target",
            "relationship_type": "DERIVED_FROM_RECORD",
            "target_id": "person-a",
            "properties": {},
        },
    ]
    attach_nodes = [
        {
            "id": "org-bmf-ein-123456789",
            "node_type": "Organization",
            "labels": ["Organization"],
            "display_label": "Target Org IRS Key",
            "properties": {
                "name": "Target Org IRS Key",
                "ein": "123456789",
            },
        }
    ]
    attach_edges = [
        {
            "source_id": "org-bmf-ein-123456789",
            "relationship_type": "SAME_AS",
            "target_id": "org-target",
            "properties": {
                "assertion_id": "assertion-test",
                "basis": "operator_approved_ein",
            },
        }
    ]
    registry = _write_registry(tmp_path / "registry/node-types.json")
    sqlite_path = tmp_path / "public-substrate.sqlite"
    report_path = tmp_path / "substrate-bake-report.json"
    return (
        [
            _write_jsonl(tmp_path / "graph-v2/nodes.jsonl", projection_nodes),
            _write_jsonl(tmp_path / "attach/nodes.jsonl", attach_nodes),
        ],
        [
            _write_jsonl(tmp_path / "graph-v2/edges.jsonl", projection_edges),
            _write_jsonl(tmp_path / "attach/edges.jsonl", attach_edges),
        ],
        registry,
        sqlite_path,
        report_path,
    )


def test_bake_is_byte_deterministic(tmp_path: Path) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _fixture(tmp_path)

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)
    first_sqlite = sqlite_path.read_bytes()
    first_report = report_path.read_bytes()

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)

    assert sqlite_path.read_bytes() == first_sqlite
    assert report_path.read_bytes() == first_report


def test_attach_same_as_assertion_rows_are_composed_and_reported(
    tmp_path: Path,
) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _fixture(tmp_path)

    report = bake_substrate(
        node_sources, edge_sources, registry, sqlite_path, report_path
    )

    with sqlite3.connect(sqlite_path) as conn:
        rows = conn.execute(
            "SELECT source, rel, target FROM edges WHERE rel = 'SAME_AS'"
        ).fetchall()

    assert rows == [("org-bmf-ein-123456789", "SAME_AS", "org-target")]
    assert report["gate_counts"]["SAME_AS_with_assertion_id"] == 1
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_embedding_umap_pending_and_payload_json_properties_are_stripped(
    tmp_path: Path,
) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _fixture(tmp_path)

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)

    with sqlite3.connect(sqlite_path) as conn:
        props_json = conn.execute(
            "SELECT props FROM nodes WHERE id = 'org-target'"
        ).fetchone()[0]
    props = json.loads(props_json)

    assert props["name"] == "Target Org"
    assert props["display_label"] == "Target Org"
    assert "embedding" not in props
    assert "umap_x" not in props
    assert "search_pending" not in props
    assert "payload_json" not in props


def test_report_is_redaction_scan_clean(tmp_path: Path) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _fixture(tmp_path)

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)
    text = report_path.read_text(encoding="utf-8")

    assert not re.search(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", text)
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", text)
    assert not re.search(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b", text)


def test_node_bench_script_reports_load_metrics(tmp_path: Path) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _fixture(tmp_path)
    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)

    result = subprocess.run(
        ["node", "scripts/bench_substrate_load.mjs", str(sqlite_path)],
        check=True,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
    )
    metrics = json.loads(result.stdout)

    assert metrics["edge_count"] == 3
    assert metrics["adjacency_sources"] == 3
    assert metrics["wall_ms"] >= 0
    assert metrics["memory_usage"]["rss"] > 0
    assert metrics["backend"] in {"better-sqlite3", "sqlite3-cli"}
