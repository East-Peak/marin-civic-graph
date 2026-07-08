"""Tests for the public substrate bake skeleton.

The fixture mirrors the graph-v2 + attach-overlay JSONL shape but stays tiny so
the S0 TDD loop can stay targeted.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
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
    graph_node_types = {
        node_type: {
            "searchable": True,
            "outbound_eligible": True,
        }
        for node_type in [
            "Organization",
            "Person",
            "Membership",
            "EconomicInterest",
            "Filing",
            "Place",
            "Decision",
            "MoneyFlow",
            "Agreement",
            "Proceeding",
            "Record",
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "graph_node_types": graph_node_types,
                "support_labels": ["ValidationCheck"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _set_mtime_date(paths: list[Path], ymd: str) -> None:
    ts = datetime.fromisoformat(f"{ymd}T12:00:00+00:00").timestamp()
    for path in paths:
        os.utime(path, (ts, ts))


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


def _browse_fixture(tmp_path: Path) -> tuple[list[Path], list[Path], Path, Path, Path]:
    nodes_path = _write_jsonl(
        tmp_path / "graph-v2/nodes.jsonl",
        [
            {
                "id": "person-alice",
                "node_type": "Person",
                "labels": ["Person"],
                "properties": {
                    "name": "Alice Person",
                    "current_seat_display": "Mayor",
                    "jurisdiction_name": "San Rafael",
                },
            },
            {
                "id": "filing-700-alice",
                "node_type": "Filing",
                "labels": ["Filing"],
                "properties": {
                    "search_label": "Alice Form 700",
                    "filing_type": "form_700",
                    "signed_at": "2026-04-02",
                    "period_start": "2025-01-01",
                },
            },
            {
                "id": "economicinterest-alice-a1",
                "node_type": "EconomicInterest",
                "labels": ["EconomicInterest"],
                "properties": {
                    "interest_type": "income",
                    "counterparty_name_raw": "Acme LLC",
                    "amount_band": "$10,001-$100,000",
                    "amount": 42000,
                },
            },
            {
                "id": "place-san-rafael",
                "node_type": "Place",
                "labels": ["Place"],
                "properties": {"name": "San Rafael", "place_type": "city"},
            },
            {
                "id": "place-sun-valley",
                "node_type": "Place",
                "labels": ["Place"],
                "properties": {"name": "Sun Valley", "place_type": "neighborhood"},
            },
        ],
    )
    edges_path = _write_jsonl(tmp_path / "graph-v2/edges.jsonl", [])
    _set_mtime_date([nodes_path, edges_path], "2026-07-06")
    registry = _write_registry(tmp_path / "registry/node-types.json")
    sqlite_path = tmp_path / "public-substrate.sqlite"
    report_path = tmp_path / "substrate-bake-report.json"
    return [nodes_path], [edges_path], registry, sqlite_path, report_path


def _search_fixture(tmp_path: Path) -> tuple[list[Path], list[Path], Path, Path, Path]:
    nodes_path = _write_jsonl(
        tmp_path / "graph-v2/nodes.jsonl",
        [
            {
                "id": "person-kate-colin",
                "node_type": "Person",
                "labels": ["Person"],
                "properties": {
                    "name": "Kate Colin",
                    "search_rank": 25,
                    "search_key_fact": "Former San Rafael mayor",
                    "search_last_activity": "2024-11-05",
                    "jurisdiction_name": "San Rafael",
                },
            },
            {
                "id": "org-terms-only",
                "node_type": "Organization",
                "labels": ["Organization"],
                "properties": {
                    "search_terms": "transit oversight climate",
                    "jurisdiction_name": "Marin County",
                },
            },
            {
                "id": "record-colin-staff-report",
                "node_type": "Record",
                "labels": ["Record"],
                "properties": {
                    "name": "Colin staff report",
                    "search_terms": "agenda packet",
                    "captured_at": "2026-06-15T10:30:00Z",
                },
            },
            {
                "id": "decision-title-only",
                "node_type": "Decision",
                "labels": ["Decision"],
                "properties": {
                    "title": "Title-only browse label",
                    "decided_at": "2026-07-01",
                },
            },
        ],
    )
    edges_path = _write_jsonl(tmp_path / "graph-v2/edges.jsonl", [])
    _set_mtime_date([nodes_path, edges_path], "2026-07-06")
    registry = _write_registry(tmp_path / "registry/node-types.json")
    sqlite_path = tmp_path / "public-substrate.sqlite"
    report_path = tmp_path / "substrate-bake-report.json"
    return [nodes_path], [edges_path], registry, sqlite_path, report_path


def _identity_money_fixture(
    tmp_path: Path,
) -> tuple[list[Path], list[Path], Path, Path, Path]:
    def org(org_id: str, name: str) -> dict:
        return {
            "id": org_id,
            "node_type": "Organization",
            "labels": ["Organization"],
            "properties": {"name": name},
        }

    def flow(flow_id: str, amount: object) -> dict:
        return {
            "id": flow_id,
            "node_type": "MoneyFlow",
            "labels": ["MoneyFlow"],
            "properties": {"amount": amount},
        }

    nodes_path = _write_jsonl(
        tmp_path / "graph-v2/nodes.jsonl",
        [
            org("org-direct", "Direct Vendor"),
            org("org-vendor", "Verified Vendor"),
            org("org-anchor", "Verified Vendor Anchor"),
            org("org-legacy-anchor", "Legacy Anchor"),
            org("org-minimal-a", "Minimal A"),
            org("org-minimal-b", "Minimal B"),
            org("org-county", "County of Marin"),
            org("org-recipient", "Recipient Org"),
            org("org-null-source", "Null Source"),
            org("org-big", "Big Counterparty"),
            org("org-med", "Medium Counterparty"),
            org("org-out2", "Outbound Two"),
            org("org-small", "Small Counterparty"),
            org("org-tiny", "Tiny Counterparty"),
            flow("flow-direct-in", 100),
            flow("flow-direct-null", None),
            flow("flow-direct-out", 25),
            flow("flow-anchor-in", 300),
            flow("flow-anchor-in-2", "250.50"),
            flow("flow-vendor-in", 120),
            flow("flow-vendor-out", 70),
            flow("flow-vendor-out-2", 80),
            flow("flow-vendor-in-small", 10),
            flow("flow-vendor-out-tiny", 5),
        ],
    )
    edges_path = _write_jsonl(
        tmp_path / "graph-v2/edges.jsonl",
        [
            {
                "source_id": "org-anchor",
                "relationship_type": "SAME_AS",
                "target_id": "org-vendor",
                "properties": {
                    "assertion_id": "assertion-verified-vendor",
                    "basis": "operator_approved_sos",
                    "decided_at": "2026-07-03T12:34:56Z",
                    "reviewer": "research-fleet-v1",
                },
            },
            {
                "source_id": "org-legacy-anchor",
                "relationship_type": "SAME_AS",
                "target_id": "org-vendor",
                "properties": {
                    "basis": "legacy-pre-assertion",
                    "decided_at": "2026-01-01T00:00:00Z",
                },
            },
            {
                "source_id": "org-minimal-a",
                "relationship_type": "SAME_AS",
                "target_id": "org-minimal-b",
                "properties": {"assertion_id": "assertion-minimal"},
            },
            {
                "source_id": "flow-direct-in",
                "relationship_type": "FROM_SOURCE",
                "target_id": "org-county",
                "properties": {},
            },
            {
                "source_id": "flow-direct-in",
                "relationship_type": "TO_TARGET",
                "target_id": "org-direct",
                "properties": {},
            },
            {
                "source_id": "flow-direct-null",
                "relationship_type": "FROM_SOURCE",
                "target_id": "org-null-source",
                "properties": {},
            },
            {
                "source_id": "flow-direct-null",
                "relationship_type": "TO_TARGET",
                "target_id": "org-direct",
                "properties": {},
            },
            {
                "source_id": "flow-direct-out",
                "relationship_type": "FROM_SOURCE",
                "target_id": "org-direct",
                "properties": {},
            },
            {
                "source_id": "flow-direct-out",
                "relationship_type": "TO_TARGET",
                "target_id": "org-recipient",
                "properties": {},
            },
            {
                "source_id": "flow-anchor-in",
                "relationship_type": "FROM_SOURCE",
                "target_id": "org-county",
                "properties": {},
            },
            {
                "source_id": "flow-anchor-in",
                "relationship_type": "TO_TARGET",
                "target_id": "org-anchor",
                "properties": {},
            },
            {
                "source_id": "flow-anchor-in-2",
                "relationship_type": "FROM_SOURCE",
                "target_id": "org-big",
                "properties": {},
            },
            {
                "source_id": "flow-anchor-in-2",
                "relationship_type": "TO_TARGET",
                "target_id": "org-anchor",
                "properties": {},
            },
            {
                "source_id": "flow-vendor-in",
                "relationship_type": "FROM_SOURCE",
                "target_id": "org-med",
                "properties": {},
            },
            {
                "source_id": "flow-vendor-in",
                "relationship_type": "TO_TARGET",
                "target_id": "org-vendor",
                "properties": {},
            },
            {
                "source_id": "flow-vendor-out",
                "relationship_type": "FROM_SOURCE",
                "target_id": "org-vendor",
                "properties": {},
            },
            {
                "source_id": "flow-vendor-out",
                "relationship_type": "TO_TARGET",
                "target_id": "org-recipient",
                "properties": {},
            },
            {
                "source_id": "flow-vendor-out-2",
                "relationship_type": "FROM_SOURCE",
                "target_id": "org-vendor",
                "properties": {},
            },
            {
                "source_id": "flow-vendor-out-2",
                "relationship_type": "TO_TARGET",
                "target_id": "org-out2",
                "properties": {},
            },
            {
                "source_id": "flow-vendor-in-small",
                "relationship_type": "FROM_SOURCE",
                "target_id": "org-small",
                "properties": {},
            },
            {
                "source_id": "flow-vendor-in-small",
                "relationship_type": "TO_TARGET",
                "target_id": "org-vendor",
                "properties": {},
            },
            {
                "source_id": "flow-vendor-out-tiny",
                "relationship_type": "FROM_SOURCE",
                "target_id": "org-vendor",
                "properties": {},
            },
            {
                "source_id": "flow-vendor-out-tiny",
                "relationship_type": "TO_TARGET",
                "target_id": "org-tiny",
                "properties": {},
            },
        ],
    )
    registry = _write_registry(tmp_path / "registry/node-types.json")
    sqlite_path = tmp_path / "public-substrate.sqlite"
    report_path = tmp_path / "substrate-bake-report.json"
    return [nodes_path], [edges_path], registry, sqlite_path, report_path


def _live_export_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    live_dir = tmp_path / "live-graph-export"
    attach_dir = tmp_path / "attach"
    registry = _write_registry(tmp_path / "registry/node-types.json")
    sqlite_path = tmp_path / "public-substrate.sqlite"
    report_path = tmp_path / "substrate-bake-report.json"

    _write_jsonl(
        live_dir / "nodes.jsonl",
        [
            {
                "id": "org-target",
                "labels": ["Business", "Organization"],
                "properties": {
                    "name": "Target Org",
                    "display_label": "Target Org",
                    "embedding": [0.1],
                    "umap_x": 1.2,
                    "search_pending": True,
                    "payload_json": "{}",
                },
            },
            {
                "id": "org-anchor-shared",
                "labels": ["Organization"],
                "properties": {"name": "Shared Anchor"},
            },
            {
                "id": "org-anchor-live-only",
                "labels": ["Organization"],
                "properties": {"name": "Live Only Anchor"},
            },
            {
                "id": "org-anchor-legacy",
                "labels": ["Organization"],
                "properties": {"name": "Legacy Anchor"},
            },
        ],
    )
    _write_jsonl(
        live_dir / "edges.jsonl",
        [
            {
                "start_id": "org-anchor-shared",
                "end_id": "org-target",
                "type": "SAME_AS",
                "properties": {
                    "assertion_id": "assertion-live-stale",
                    "basis": "live-stale",
                },
            },
            {
                "start_id": "org-anchor-live-only",
                "end_id": "org-target",
                "type": "SAME_AS",
                "properties": {
                    "assertion_id": "assertion-live-only",
                    "basis": "live-only",
                },
            },
            {
                "start_id": "org-anchor-legacy",
                "end_id": "org-target",
                "type": "SAME_AS",
                "properties": {},
            },
            {
                "start_id": "org-target",
                "end_id": "org-anchor-legacy",
                "type": "DERIVED_FROM_RECORD",
                "properties": {},
            },
        ],
    )
    _write_jsonl(
        attach_dir / "nodes.jsonl",
        [
            {
                "id": "org-anchor-overlay-only",
                "node_type": "Organization",
                "labels": ["Organization"],
                "display_label": "Overlay Only Anchor",
                "properties": {"name": "Overlay Only Anchor"},
            }
        ],
    )
    _write_jsonl(
        attach_dir / "edges.jsonl",
        [
            {
                "source_id": "org-anchor-shared",
                "relationship_type": "SAME_AS",
                "target_id": "org-target",
                "properties": {
                    "assertion_id": "assertion-overlay-authoritative",
                    "basis": "overlay-authoritative",
                },
            },
            {
                "source_id": "org-anchor-overlay-only",
                "relationship_type": "SAME_AS",
                "target_id": "org-target",
                "properties": {
                    "assertion_id": "assertion-overlay-only",
                    "basis": "overlay-only",
                },
            },
        ],
    )
    return live_dir, attach_dir, registry, sqlite_path, report_path


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


def test_live_export_mode_composes_export_with_overlay_authoritative_same_as(
    tmp_path: Path,
) -> None:
    live_dir, attach_dir, registry, sqlite_path, report_path = _live_export_fixture(
        tmp_path
    )

    report = bake_substrate(
        registry_path=registry,
        sqlite_path=sqlite_path,
        report_path=report_path,
        source="live-export",
        live_export_dir=live_dir,
        attach_overlay_dir=attach_dir,
    )

    with sqlite3.connect(sqlite_path) as conn:
        same_as_rows = conn.execute(
            "SELECT source, rel, target FROM edges WHERE rel = 'SAME_AS' "
            "ORDER BY source, target"
        ).fetchall()

    assert same_as_rows == [
        ("org-anchor-legacy", "SAME_AS", "org-target"),
        ("org-anchor-overlay-only", "SAME_AS", "org-target"),
        ("org-anchor-shared", "SAME_AS", "org-target"),
    ]
    assert report["gate_counts"]["SAME_AS_with_assertion_id"] == 2
    assert report["same_as_overlay_drift"] == {
        "live_stamped_count": 2,
        "overlay_stamped_count": 2,
        "overlay_rows_missing_live_count": 1,
        "overlay_rows_missing_live_sample": [
            {
                "source": "org-anchor-overlay-only",
                "rel": "SAME_AS",
                "target": "org-target",
            }
        ],
        "live_stamped_rows_missing_overlay_count": 1,
        "live_stamped_rows_missing_overlay_sample": [
            {
                "source": "org-anchor-live-only",
                "rel": "SAME_AS",
                "target": "org-target",
            }
        ],
        "legacy_unstamped_count": 1,
    }
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_live_export_mode_infers_types_and_strips_live_properties(
    tmp_path: Path,
) -> None:
    live_dir, attach_dir, registry, sqlite_path, report_path = _live_export_fixture(
        tmp_path
    )

    bake_substrate(
        registry_path=registry,
        sqlite_path=sqlite_path,
        report_path=report_path,
        source="live-export",
        live_export_dir=live_dir,
        attach_overlay_dir=attach_dir,
    )

    with sqlite3.connect(sqlite_path) as conn:
        node_type, props_json = conn.execute(
            "SELECT type, props FROM nodes WHERE id = 'org-target'"
        ).fetchone()
    props = json.loads(props_json)

    assert node_type == "Organization"
    assert props["name"] == "Target Org"
    assert props["display_label"] == "Target Org"
    assert "embedding" not in props
    assert "umap_x" not in props
    assert "search_pending" not in props
    assert "payload_json" not in props


def test_live_export_bake_is_byte_deterministic(tmp_path: Path) -> None:
    live_dir, attach_dir, registry, sqlite_path, report_path = _live_export_fixture(
        tmp_path
    )

    bake_substrate(
        registry_path=registry,
        sqlite_path=sqlite_path,
        report_path=report_path,
        source="live-export",
        live_export_dir=live_dir,
        attach_overlay_dir=attach_dir,
    )
    first_sqlite = sqlite_path.read_bytes()
    first_report = report_path.read_bytes()

    bake_substrate(
        registry_path=registry,
        sqlite_path=sqlite_path,
        report_path=report_path,
        source="live-export",
        live_export_dir=live_dir,
        attach_overlay_dir=attach_dir,
    )

    assert sqlite_path.read_bytes() == first_sqlite
    assert report_path.read_bytes() == first_report


def test_identity_links_membership_fields_and_indexes(tmp_path: Path) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = (
        _identity_money_fixture(tmp_path)
    )

    report = bake_substrate(
        node_sources, edge_sources, registry, sqlite_path, report_path
    )

    with sqlite3.connect(sqlite_path) as conn:
        identity_links = conn.execute(
            """
            SELECT source, target, assertion_id, basis, decided_at, reviewer
            FROM identity_links
            ORDER BY assertion_id
            """
        ).fetchall()
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'identity_links'"
        ).fetchone()[0]
        indexes = {
            name: sql
            for name, sql in conn.execute(
                """
                SELECT name, sql
                FROM sqlite_master
                WHERE type = 'index'
                  AND tbl_name = 'identity_links'
                """
            )
        }

    assert identity_links == [
        (
            "org-minimal-a",
            "org-minimal-b",
            "assertion-minimal",
            None,
            None,
            None,
        ),
        (
            "org-anchor",
            "org-vendor",
            "assertion-verified-vendor",
            "operator_approved_sos",
            "2026-07-03T12:34:56Z",
            "research-fleet-v1",
        ),
    ]
    assert "assertion_id TEXT NOT NULL" in ddl
    assert "idx_identity_links_source" in indexes
    assert "ON identity_links(source)" in indexes["idx_identity_links_source"]
    assert "idx_identity_links_target" in indexes
    assert "ON identity_links(target)" in indexes["idx_identity_links_target"]
    assert report["side_table_counts"]["identity_links"] == 2


def test_money_rollups_include_direct_flows_and_null_amounts(tmp_path: Path) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = (
        _identity_money_fixture(tmp_path)
    )

    report = bake_substrate(
        node_sources, edge_sources, registry, sqlite_path, report_path
    )

    with sqlite3.connect(sqlite_path) as conn:
        row = conn.execute(
            """
            SELECT
                org_id,
                flows_in_count,
                money_in_total,
                flows_out_count,
                money_out_total,
                top_counterparties
            FROM money_rollups
            WHERE org_id = 'org-direct'
            """
        ).fetchone()
        money_rollup_count = conn.execute(
            "SELECT COUNT(*) FROM money_rollups"
        ).fetchone()[0]

    assert row[:5] == ("org-direct", 2, 100.0, 1, 25.0)
    assert json.loads(row[5]) == [
        {"id": "org-county", "label": "County of Marin", "total": 100.0},
        {"id": "org-recipient", "label": "Recipient Org", "total": 25.0},
        {"id": "org-null-source", "label": "Null Source", "total": 0.0},
    ]
    assert report["side_table_counts"]["money_rollups"] == money_rollup_count


def test_money_rollups_expand_across_verified_identity_links_and_order_counterparties(
    tmp_path: Path,
) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = (
        _identity_money_fixture(tmp_path)
    )

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)

    with sqlite3.connect(sqlite_path) as conn:
        row = conn.execute(
            """
            SELECT
                flows_in_count,
                money_in_total,
                flows_out_count,
                money_out_total,
                top_counterparties
            FROM money_rollups
            WHERE org_id = 'org-vendor'
            """
        ).fetchone()

    assert row[:4] == (4, 680.5, 3, 155.0)
    assert json.loads(row[4]) == [
        {"id": "org-county", "label": "County of Marin", "total": 300.0},
        {"id": "org-big", "label": "Big Counterparty", "total": 250.5},
        {"id": "org-med", "label": "Medium Counterparty", "total": 120.0},
        {"id": "org-out2", "label": "Outbound Two", "total": 80.0},
        {"id": "org-recipient", "label": "Recipient Org", "total": 70.0},
    ]


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


def test_browse_rows_materialize_authoritative_columns_for_representative_types(
    tmp_path: Path,
) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _browse_fixture(
        tmp_path
    )

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)

    with sqlite3.connect(sqlite_path) as conn:
        rows = {
            row[0]: row[1:]
            for row in conn.execute(
                """
                SELECT id, search_label, col1_key, col1_value, col2_key, col2_value
                FROM browse_rows
                ORDER BY id
                """
            )
        }

    assert rows["person-alice"] == (
        "Alice Person",
        "current_seat_display",
        '"Mayor"',
        "jurisdiction_name",
        '"San Rafael"',
    )
    assert rows["filing-700-alice"] == (
        "Alice Form 700",
        "filing_type",
        '"form_700"',
        "signed_at",
        '"2026-04-02"',
    )
    assert rows["economicinterest-alice-a1"] == (
        "economicinterest-alice-a1",
        "interest_type",
        '"income"',
        "counterparty_name_raw",
        '"Acme LLC"',
    )


def test_economic_interest_amount_fact_maps_to_amount_band() -> None:
    from bake_public_substrate import _prop_key_for_fact_label

    assert _prop_key_for_fact_label("EconomicInterest", "Amount") == "amount_band"


def test_browse_rows_label_lower_supports_case_insensitive_substring_search(
    tmp_path: Path,
) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _browse_fixture(
        tmp_path
    )

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)

    with sqlite3.connect(sqlite_path) as conn:
        row = conn.execute(
            """
            SELECT id, label_lower
            FROM browse_rows
            WHERE type = 'Person'
              AND label_lower LIKE '%' || lower(?) || '%'
            """,
            ("ICE per",),
        ).fetchone()
        indexes = {
            index_name
            for (index_name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }

    assert row == ("person-alice", "alice person")
    assert "idx_browse_rows_type_id" in indexes
    assert "idx_browse_rows_label_lower" in indexes


def test_search_fts_is_contentless_and_joins_back_to_nodes_by_rowid(
    tmp_path: Path,
) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _search_fixture(
        tmp_path
    )

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)

    with sqlite3.connect(sqlite_path) as conn:
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'search_fts'"
        ).fetchone()[0]
        rows = {
            row[0]: row[1:]
            for row in conn.execute(
                """
                SELECT n.id, n.search_label, json_extract(n.props, '$.search_terms')
                FROM search_fts
                JOIN nodes n ON n.rowid = search_fts.rowid
                ORDER BY n.id
                """
            )
        }
        raw_fts_rows = conn.execute(
            """
            SELECT search_fts.rowid, search_fts.search_label, search_fts.search_terms
            FROM search_fts
            ORDER BY search_fts.rowid
            """
        ).fetchall()
        matches = conn.execute(
            """
            SELECT n.id, n.type, n.search_label, json_extract(n.props, '$.search_rank')
            FROM search_fts
            JOIN nodes n ON n.rowid = search_fts.rowid
            WHERE search_fts MATCH ?
            ORDER BY bm25(search_fts), n.id
            """,
            ("colin",),
        ).fetchall()
        search_term_match = conn.execute(
            """
            SELECT n.id
            FROM search_fts
            JOIN nodes n ON n.rowid = search_fts.rowid
            WHERE search_fts MATCH ?
            ORDER BY n.id
            """,
            ("climate",),
        ).fetchall()
        fallback_label_match = conn.execute(
            """
            SELECT n.id
            FROM search_fts
            JOIN nodes n ON n.rowid = search_fts.rowid
            WHERE search_fts MATCH ?
            ORDER BY n.id
            """,
            ("title",),
        ).fetchall()
        ranked = conn.execute(
            """
            SELECT n.id, bm25(search_fts)
            FROM search_fts
            JOIN nodes n ON n.rowid = search_fts.rowid
            WHERE search_fts MATCH ?
            ORDER BY bm25(search_fts), n.id
            """,
            ("colin",),
        ).fetchall()

    assert "content=''" in ddl
    assert "tokenize='unicode61'" in ddl
    assert rows == {
        "org-terms-only": ("org-terms-only", "transit oversight climate"),
        "decision-title-only": ("Title-only browse label", None),
        "person-kate-colin": ("Kate Colin", None),
        "record-colin-staff-report": ("Colin staff report", "agenda packet"),
    }
    assert {row[0] for row in raw_fts_rows} == {1, 2, 3, 4}
    assert all(search_label is None for _, search_label, _ in raw_fts_rows)
    assert all(search_terms is None for _, _, search_terms in raw_fts_rows)
    assert ("person-kate-colin", "Person", "Kate Colin", 25) in matches
    assert ("record-colin-staff-report", "Record", "Colin staff report", None) in matches
    assert search_term_match == [("org-terms-only",)]
    assert fallback_label_match == [("decision-title-only",)]
    assert all(isinstance(score, float) for _, score in ranked)


def test_search_meta_is_absent_and_envelope_fields_resolve_from_node_props(
    tmp_path: Path,
) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _search_fixture(
        tmp_path
    )

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)

    with sqlite3.connect(sqlite_path) as conn:
        search_meta = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE name = 'search_meta'
            """
        ).fetchall()
        row = conn.execute(
            """
            SELECT
                n.id,
                n.type,
                n.search_label,
                json_extract(n.props, '$.search_rank'),
                json_extract(n.props, '$.search_key_fact'),
                json_extract(n.props, '$.search_last_activity'),
                json_extract(n.props, '$.jurisdiction_name'),
                json_extract(n.props, '$.captured_at')
            FROM search_fts
            JOIN nodes n ON n.rowid = search_fts.rowid
            WHERE search_fts MATCH ?
            ORDER BY bm25(search_fts), n.id
            LIMIT 1
            """,
            ("colin",),
        ).fetchone()

    assert search_meta == []
    assert row == (
        "person-kate-colin",
        "Person",
        "Kate Colin",
        25,
        "Former San Rafael mayor",
        "2024-11-05",
        "San Rafael",
        None,
    )


def test_meta_manifest_and_catalog_use_export_mtime_as_of_date(
    tmp_path: Path,
) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _browse_fixture(
        tmp_path
    )

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)

    with sqlite3.connect(sqlite_path) as conn:
        meta = dict(conn.execute("SELECT key, value FROM meta ORDER BY key"))

    status_manifest = json.loads(
        (sqlite_path.parent / "status_manifest.json").read_text(encoding="utf-8")
    )
    catalog = json.loads(
        (sqlite_path.parent / "catalog.json").read_text(encoding="utf-8")
    )

    assert meta["as_of_date"] == "2026-07-06"
    assert meta["bake_version"] == "S2a-2"
    assert status_manifest == {
        "as_of_date": "2026-07-06",
        "bake_version": "S2a-2",
        "edge_count": 0,
        "jurisdiction_count": 1,
        "node_count": 5,
        "per_type_counts": {
            "EconomicInterest": 1,
            "Filing": 1,
            "Person": 1,
            "Place": 2,
        },
    }
    assert catalog["as_of_date"] == "2026-07-06"
    assert catalog["built_at"] == "2026-07-06"
    assert catalog["counts"] == status_manifest["per_type_counts"]
    assert catalog["jurisdiction_count"] == 1


def test_data_query_support_indexes_are_created(tmp_path: Path) -> None:
    node_sources, edge_sources, registry, sqlite_path, report_path = _browse_fixture(
        tmp_path
    )

    bake_substrate(node_sources, edge_sources, registry, sqlite_path, report_path)

    with sqlite3.connect(sqlite_path) as conn:
        index_sql = {
            name: sql
            for name, sql in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index'"
            )
        }

    assert "idx_nodes_decision_data_query" in index_sql
    assert (
        "json_extract(props, '$.decided_at')"
        in index_sql["idx_nodes_decision_data_query"]
    )
    assert (
        "json_extract(props, '$.institution_id')"
        in index_sql["idx_nodes_decision_data_query"]
    )
    assert "idx_nodes_moneyflow_data_query" in index_sql
    assert (
        "json_extract(props, '$.flow_date')"
        in index_sql["idx_nodes_moneyflow_data_query"]
    )
    assert (
        "json_extract(props, '$.amount')"
        in index_sql["idx_nodes_moneyflow_data_query"]
    )
    assert (
        "json_extract(props, '$.flow_type')"
        in index_sql["idx_nodes_moneyflow_data_query"]
    )
    assert "idx_nodes_filing_data_query" in index_sql
    assert "idx_nodes_agreement_data_query" in index_sql
    assert "idx_nodes_proceeding_data_query" in index_sql
    assert "idx_nodes_record_data_query" in index_sql
    # Deliberately absent (§6 size budget): serving paths never enter edges
    # rel-first, and browse/search read browse_rows/FTS — not a nodes(type,
    # search_label) index.
    assert "idx_edges_rel_source_target" not in index_sql
    assert "idx_nodes_type_search_label_id" not in index_sql


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


def test_money_rollup_handles_county_edge_orientation(tmp_path: Path) -> None:
    """County-contract loads point (dept)-[FROM_SOURCE]->(flow), the reverse
    of campaign data. The vendor's rollup must still see the department as
    its counterparty, and the department must see money OUT."""
    nodes = [
        {"id": "org-dept-hhs", "node_type": "Organization", "labels": ["Organization"],
         "properties": {"name": "Dept HHS"}},
        {"id": "org-vendor", "node_type": "Organization", "labels": ["Organization"],
         "properties": {"name": "Vendor"}},
        {"id": "moneyflow-c1", "node_type": "MoneyFlow", "labels": ["MoneyFlow"],
         "properties": {"amount": 1000}},
    ]
    edges = [
        {"source_id": "org-dept-hhs", "relationship_type": "FROM_SOURCE",
         "target_id": "moneyflow-c1", "properties": {}},
        {"source_id": "moneyflow-c1", "relationship_type": "TO_TARGET",
         "target_id": "org-vendor", "properties": {}},
    ]
    nodes_path = _write_jsonl(tmp_path / "graph-v2/nodes.jsonl", nodes)
    edges_path = _write_jsonl(tmp_path / "graph-v2/edges.jsonl", edges)
    _set_mtime_date([nodes_path, edges_path], "2026-07-06")
    registry = _write_registry(tmp_path / "registry/node-types.json")
    sqlite_path = tmp_path / "public-substrate.sqlite"
    bake_substrate([nodes_path], [edges_path], registry, sqlite_path,
                   tmp_path / "report.json")
    conn = sqlite3.connect(sqlite_path)
    vendor = conn.execute(
        "SELECT flows_in_count, money_in_total, top_counterparties "
        "FROM money_rollups WHERE org_id='org-vendor'").fetchone()
    dept = conn.execute(
        "SELECT flows_out_count, money_out_total, top_counterparties "
        "FROM money_rollups WHERE org_id='org-dept-hhs'").fetchone()
    assert vendor[0] == 1 and vendor[1] == 1000
    assert json.loads(vendor[2])[0]["id"] == "org-dept-hhs"
    assert dept[0] == 1 and dept[1] == 1000
    assert json.loads(dept[2])[0]["id"] == "org-vendor"
