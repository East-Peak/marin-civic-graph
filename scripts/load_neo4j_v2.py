"""load_neo4j_v2.py — Batched Neo4j loader for the Marin Civic Graph.

Reads migrated graph-v2 JSONL files and loads them into Neo4j AuraDB using
the neo4j Python driver with batched UNWIND writes for efficiency.

Usage:
  python scripts/load_neo4j_v2.py
  python scripts/load_neo4j_v2.py --input-dir data/projected/graph-v2 \\
                                   --uri bolt://localhost:7687 \\
                                   --user neo4j \\
                                   --password secret
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Pure functions (testable without a Neo4j connection)
# ---------------------------------------------------------------------------


def chunk_list(lst: list, size: int) -> Iterator[list]:
    """Yield successive chunks of `size` from `lst`."""
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def build_node_batch_query(node_type: str, labels: list[str]) -> tuple[str, dict]:
    """Build a MERGE+SET Cypher query for batched node creation.

    Returns (query_string, empty_params_dict).
    Query uses $batch parameter with UNWIND.

    For a single label ["Decision"]:
        UNWIND $batch AS row
        MERGE (n:Decision {id: row.id})
        SET n:Decision
        SET n += row.props
        SET n.display_label = row.display_label
        SET n.promotion_state = row.promotion_state

    For multi-label ["Organization", "Government"]:
        MERGE uses the primary (first) label; the SET line includes all labels.
    """
    primary = labels[0]
    label_expr = ":".join(labels)

    query = "\n".join([
        "UNWIND $batch AS row",
        f"MERGE (n:{primary} {{id: row.id}})",
        f"SET n:{label_expr}",
        "SET n += row.props",
        "SET n.display_label = row.display_label",
        "SET n.promotion_state = row.promotion_state",
    ])

    return query, {}


def build_edge_batch_query(relationship_type: str) -> str:
    """Build a MERGE+SET Cypher query for batched edge creation.

    Query uses $batch parameter with UNWIND.

    Example for CAST_VOTE:
        UNWIND $batch AS row
        MATCH (s {id: row.source_id})
        MATCH (t {id: row.target_id})
        MERGE (s)-[r:CAST_VOTE]->(t)
        SET r += row.props
    """
    return "\n".join([
        "UNWIND $batch AS row",
        "MATCH (s {id: row.source_id})",
        "MATCH (t {id: row.target_id})",
        f"MERGE (s)-[r:{relationship_type}]->(t)",
        "SET r += row.props",
    ])


def validate_edge_endpoints(
    node_ids: set[str],
    edges: list[dict],
) -> dict:
    """Check that all edge source/target IDs exist in the node set.

    Returns a summary dict with:
        missing_sources: list of edges with missing source nodes
        missing_targets: list of edges with missing target nodes
        by_relationship: broken edge counts keyed by relationship_type
        total_broken: count of edges with at least one missing endpoint
    """
    missing_sources: list[dict] = []
    missing_targets: list[dict] = []
    by_rel: dict[str, int] = {}
    broken_count = 0

    for edge in edges:
        src_missing = edge["source_id"] not in node_ids
        tgt_missing = edge["target_id"] not in node_ids
        if src_missing:
            missing_sources.append({
                "source_id": edge["source_id"],
                "target_id": edge["target_id"],
                "relationship_type": edge["relationship_type"],
            })
        if tgt_missing:
            missing_targets.append({
                "source_id": edge["source_id"],
                "target_id": edge["target_id"],
                "relationship_type": edge["relationship_type"],
            })
        if src_missing or tgt_missing:
            broken_count += 1
            rel = edge["relationship_type"]
            by_rel[rel] = by_rel.get(rel, 0) + 1

    return {
        "missing_sources": missing_sources,
        "missing_targets": missing_targets,
        "by_relationship": by_rel,
        "total_broken": broken_count,
    }


def validate_and_filter_edges(
    node_ids: set[str],
    edges: list[dict],
) -> tuple[list[dict], dict]:
    """Validate edges and return only those with valid endpoints.

    Returns (clean_edges, report) where report is from validate_edge_endpoints.
    """
    report = validate_edge_endpoints(node_ids, edges)
    if report["total_broken"] == 0:
        return edges, report

    clean = [
        e for e in edges
        if e["source_id"] in node_ids and e["target_id"] in node_ids
    ]
    return clean, report


# ---------------------------------------------------------------------------
# Neo4j I/O functions (require a live driver)
# ---------------------------------------------------------------------------


def apply_schema(driver, schema_path: Path) -> None:
    """Read and apply Cypher schema file (constraints + indexes).

    Splits on semicolons, skips comment-only or empty segments, and executes
    each statement in its own transaction.
    """
    schema_text = schema_path.read_text(encoding="utf-8")
    statements = schema_text.split(";")

    with driver.session() as session:
        for raw in statements:
            # Strip whitespace and skip empty or comment-only blocks
            lines = [
                ln for ln in raw.splitlines()
                if ln.strip() and not ln.strip().startswith("//")
            ]
            if not lines:
                continue
            stmt = "\n".join(lines).strip()
            if not stmt:
                continue
            session.run(stmt)


def load_nodes(driver, nodes: list[dict], batch_size: int = 500) -> Counter:
    """Group nodes by label tuple, load in batches using UNWIND.

    Each batch row carries:
        id, props (node properties minus payload_json), display_label, promotion_state

    Returns a Counter of written nodes keyed by node_type.
    """
    # Group by frozenset-ordered tuple of labels for deterministic grouping
    by_labels: dict[tuple, list[dict]] = {}
    for node in nodes:
        key = tuple(node["labels"])
        by_labels.setdefault(key, []).append(node)

    counts: Counter = Counter()

    with driver.session() as session:
        for labels, group in by_labels.items():
            node_type = group[0]["node_type"]
            query, _ = build_node_batch_query(node_type, list(labels))

            for chunk in chunk_list(group, batch_size):
                batch = [
                    {
                        "id": n["id"],
                        "props": {
                            k: v
                            for k, v in n.get("properties", {}).items()
                            if k != "payload_json"
                        },
                        "display_label": n.get("display_label", ""),
                        "promotion_state": n.get("promotion_state", ""),
                    }
                    for n in chunk
                ]
                session.run(query, batch=batch)
                counts[node_type] += len(chunk)

    return counts


def load_edges(driver, edges: list[dict], batch_size: int = 500) -> Counter:
    """Group edges by relationship_type, load in batches using UNWIND.

    Each batch row carries:
        source_id, target_id, props (edge properties)

    Returns a Counter of written edges keyed by relationship_type.
    """
    by_rel: dict[str, list[dict]] = {}
    for edge in edges:
        rel = edge["relationship_type"]
        by_rel.setdefault(rel, []).append(edge)

    counts: Counter = Counter()

    with driver.session() as session:
        for rel_type, group in by_rel.items():
            query = build_edge_batch_query(rel_type)

            for chunk in chunk_list(group, batch_size):
                batch = [
                    {
                        "source_id": e["source_id"],
                        "target_id": e["target_id"],
                        "props": e.get("properties", {}),
                    }
                    for e in chunk
                ]
                session.run(query, batch=batch)
                counts[rel_type] += len(chunk)

    return counts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file into a list of dicts, skipping blank lines."""
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load the projected graph-v2 JSONL files into Neo4j AuraDB."
    )
    parser.add_argument(
        "--input-dir",
        default="data/projected/graph-v2",
        help="Directory containing nodes.jsonl and edges.jsonl (default: data/projected/graph-v2)",
    )
    parser.add_argument(
        "--schema",
        default="registry/neo4j-schema.cypher",
        help="Path to Neo4j schema Cypher file (default: registry/neo4j-schema.cypher)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of nodes/edges per UNWIND batch (default: 500)",
    )
    parser.add_argument(
        "--uri",
        default=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        help="Neo4j connection URI",
    )
    parser.add_argument(
        "--user",
        default=os.getenv("NEO4J_USER", "neo4j"),
        help="Neo4j username",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("NEO4J_PASSWORD"),
        help="Neo4j password (or set NEO4J_PASSWORD env var)",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("NEO4J_DATABASE", "neo4j"),
        help="Neo4j database name",
    )
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="Skip schema application (constraints + indexes)",
    )
    args = parser.parse_args()

    if not args.password:
        print("ERROR: NEO4J_PASSWORD is required (--password or NEO4J_PASSWORD env var).", file=sys.stderr)
        sys.exit(1)

    # Lazy import so tests don't require neo4j installed in minimal envs
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("ERROR: neo4j Python driver is not installed. Run: pip install neo4j", file=sys.stderr)
        sys.exit(1)

    input_dir = Path(args.input_dir)
    nodes_path = input_dir / "nodes.jsonl"
    edges_path = input_dir / "edges.jsonl"
    schema_path = Path(args.schema)

    if not nodes_path.exists():
        print(f"ERROR: nodes file not found: {nodes_path}", file=sys.stderr)
        sys.exit(1)
    if not edges_path.exists():
        print(f"ERROR: edges file not found: {edges_path}", file=sys.stderr)
        sys.exit(1)
    if not args.skip_schema and not schema_path.exists():
        print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to Neo4j: {args.uri} (database={args.database})")
    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))

    try:
        driver.verify_connectivity()
        print("  Connection verified.")

        if not args.skip_schema:
            print(f"Applying schema from: {schema_path}")
            apply_schema(driver, schema_path)
            print("  Schema applied.")

        print(f"Reading nodes from: {nodes_path}")
        nodes = _read_jsonl(nodes_path)
        print(f"  {len(nodes):,} nodes loaded.")

        print(f"Reading edges from: {edges_path}")
        edges = _read_jsonl(edges_path)
        print(f"  {len(edges):,} edges loaded.")

        # Validate edge endpoints before loading
        node_ids = {n["id"] for n in nodes}
        clean_edges, edge_report = validate_and_filter_edges(node_ids, edges)
        if edge_report["total_broken"] > 0:
            print(f"  WARNING: {edge_report['total_broken']} edges have missing endpoints:")
            for rel, count in edge_report["by_relationship"].items():
                print(f"    {rel}: {count} broken")
            print(f"  Filtered to {len(clean_edges):,} valid edges.")

        print(f"Loading nodes into Neo4j (batch_size={args.batch_size}) ...")
        node_counts = load_nodes(driver, nodes, batch_size=args.batch_size)
        total_nodes = sum(node_counts.values())
        print(f"  {total_nodes:,} nodes written.")
        for ntype, count in sorted(node_counts.items()):
            print(f"    {ntype:30s} {count:6,d}")

        print(f"Loading edges into Neo4j (batch_size={args.batch_size}) ...")
        edge_counts = load_edges(driver, clean_edges, batch_size=args.batch_size)
        total_edges = sum(edge_counts.values())
        print(f"  {total_edges:,} edges written.")
        for rel, count in sorted(edge_counts.items(), key=lambda x: -x[1])[:20]:
            print(f"    {rel:40s} {count:6,d}")

        print()
        print("Load complete.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
