"""Restore a live-graph JSONL export into a local Neo4j target.

The loader mirrors scripts/export_live_graph.py's JSONL shape:
nodes.jsonl rows are {id, labels, properties}; edges.jsonl rows are
{start_id, end_id, type, properties}. Neo4j driver creation is CLI-only so unit
tests can inject a fake driver and never touch a real database.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

DEFAULT_EXPORT_DIR = Path("data/exports/live-graph-export")
REQUIRED_ENV = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE")

SUMMARY_NODES_Q = "MATCH (n) RETURN count(n) AS nodes"
SUMMARY_RELS_Q = "MATCH ()-[r]->() RETURN count(r) AS relationships"
COUNT_NODES_Q = "MATCH (n) RETURN count(n) AS c"
WIPE_BATCH_Q = "MATCH (n) WITH n LIMIT $limit DETACH DELETE n"


def _progress_fn(progress: Callable[[str], None] | None) -> Callable[[str], None]:
    return progress or (lambda _line: None)


def _quote_cypher_identifier(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("Cypher labels and relationship types must be non-empty strings")
    return f"`{name.replace('`', '``')}`"


def _stable_label_key(labels: Iterable[Any]) -> tuple[str, ...]:
    clean = tuple(str(label) for label in labels)
    if not clean:
        raise ValueError("node labels must be non-empty")
    return clean


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no} is not a JSON object")
            rows.append(row)
    return rows


def _chunks(rows: list[dict[str, Any]], size: int):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def _load_export(export_dir: Path | str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base = Path(export_dir)
    return _read_jsonl(base / "nodes.jsonl"), _read_jsonl(base / "edges.jsonl")


def _primary_labels(nodes: Iterable[Mapping[str, Any]]) -> set[str]:
    labels: set[str] = set()
    for node in nodes:
        label_key = _stable_label_key(node.get("labels", ()))
        labels.add(label_key[0])
    return labels


def _build_constraint_query(primary_label: str) -> str:
    label = _quote_cypher_identifier(primary_label)
    return f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"


def _build_node_query(labels: tuple[str, ...]) -> str:
    primary = _quote_cypher_identifier(labels[0])
    label_expr = ":".join(_quote_cypher_identifier(label) for label in labels)
    return "\n".join(
        [
            "UNWIND $batch AS row",
            f"MERGE (n:{primary} {{id: row.id}})",
            f"SET n:{label_expr}",
            "SET n += row.properties",
            "SET n.id = row.id",
        ]
    )


def _build_relationship_query(
    start_label: str, relationship_type: str, end_label: str
) -> str:
    # Label-qualified endpoint matches so the per-label id uniqueness
    # constraints back every lookup. Unlabeled `MATCH (s {id: ...})` cannot
    # use any index in Neo4j and full-scans the node store per row — the
    # first restore of the 169K-edge export wedged for 30+ minutes on
    # exactly that (2026-07-08).
    rel_type = _quote_cypher_identifier(relationship_type)
    s_label = _quote_cypher_identifier(start_label)
    e_label = _quote_cypher_identifier(end_label)
    return "\n".join(
        [
            "UNWIND $batch AS row",
            f"MATCH (s:{s_label} {{id: row.start_id}})",
            f"MATCH (t:{e_label} {{id: row.end_id}})",
            f"MERGE (s)-[r:{rel_type}]->(t)",
            "SET r += row.properties",
        ]
    )


def _node_batch_row(node: Mapping[str, Any]) -> dict[str, Any]:
    if "id" not in node:
        raise ValueError("node row missing id")
    return {
        "id": str(node["id"]),
        "properties": dict(node.get("properties") or {}),
    }


def _edge_batch_row(edge: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("start_id", "end_id", "type"):
        if key not in edge:
            raise ValueError(f"edge row missing {key}")
    return {
        "start_id": str(edge["start_id"]),
        "end_id": str(edge["end_id"]),
        "properties": dict(edge.get("properties") or {}),
    }


def _group_nodes_by_labels(nodes: Iterable[Mapping[str, Any]]) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        groups[_stable_label_key(node.get("labels", ()))].append(_node_batch_row(node))
    return dict(groups)


def _primary_label_by_id(nodes: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    return {
        str(node["id"]): _stable_label_key(node.get("labels", ()))[0]
        for node in nodes
        if node.get("labels")
    }


def _group_edges_by_signature(
    edges: Iterable[Mapping[str, Any]], label_by_id: Mapping[str, str]
) -> tuple[dict[tuple[str, str, str], list[dict[str, Any]]], int]:
    """Group edges by (start_label, rel_type, end_label); returns (groups,
    dangling_count) where dangling edges reference ids absent from the node
    export and are skipped loudly rather than half-matched."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    dangling = 0
    for edge in edges:
        if "type" not in edge:
            raise ValueError("edge row missing type")
        row = _edge_batch_row(edge)
        s_label = label_by_id.get(row["start_id"])
        e_label = label_by_id.get(row["end_id"])
        if s_label is None or e_label is None:
            dangling += 1
            continue
        groups[(s_label, str(edge["type"]), e_label)].append(row)
    return dict(groups), dangling


def _scalar(session: Any, query: str, key: str) -> int:
    return int(session.run(query).single()[key])


def assert_local_target(uri: str, *, override: bool = False) -> None:
    lower = uri.lower()
    if override:
        return
    if "neo4j.io" in lower or "aura" in lower:
        raise ValueError(
            "Refusing to restore into non-local Neo4j URI. "
            "Use --i-know-this-is-not-local only after independently verifying the target."
        )


def _wipe_database(session: Any, *, batch_size: int, progress: Callable[[str], None]) -> int:
    existing = _scalar(session, COUNT_NODES_Q, "c")
    progress(f"wipe requested; existing nodes={existing}")
    batches = math.ceil(existing / batch_size) if existing else 0
    for batch_no in range(1, batches + 1):
        session.run(WIPE_BATCH_Q, limit=batch_size)
        progress(f"wipe batch {batch_no}/{batches} limit={batch_size}")
    return existing


def restore_neo4j_local(
    driver: Any,
    *,
    database: str,
    export_dir: Path | str = DEFAULT_EXPORT_DIR,
    batch_size: int = 10_000,
    wipe: bool = False,
    progress: Callable[[str], None] | None = print,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    progress_line = _progress_fn(progress)
    nodes, edges = _load_export(export_dir)
    node_groups = _group_nodes_by_labels(nodes)
    label_by_id = _primary_label_by_id(nodes)
    edge_groups, dangling_edges = _group_edges_by_signature(edges, label_by_id)
    if dangling_edges:
        progress_line(f"WARNING: skipped {dangling_edges} dangling edges (endpoint ids not in node export)")

    with driver.session(database=database) as session:
        wiped_nodes = _wipe_database(session, batch_size=batch_size, progress=progress_line) if wipe else 0

        for primary_label in sorted(_primary_labels(nodes)):
            session.run(_build_constraint_query(primary_label))

        restored_nodes = 0
        for labels in sorted(node_groups):
            group = node_groups[labels]
            for batch_no, batch in enumerate(_chunks(group, batch_size), start=1):
                session.run(_build_node_query(labels), batch=batch)
                restored_nodes += len(batch)
                progress_line(
                    f"nodes labels={','.join(labels)} batch={batch_no} "
                    f"wrote={len(batch)} total={restored_nodes}"
                )

        restored_relationships = 0
        for signature in sorted(edge_groups):
            start_label, relationship_type, end_label = signature
            group = edge_groups[signature]
            for batch_no, batch in enumerate(_chunks(group, batch_size), start=1):
                session.run(
                    _build_relationship_query(start_label, relationship_type, end_label),
                    batch=batch,
                )
                restored_relationships += len(batch)
                progress_line(
                    f"relationships {start_label}-{relationship_type}->{end_label} "
                    f"batch={batch_no} wrote={len(batch)} total={restored_relationships}"
                )

        database_counts = {
            "nodes": _scalar(session, SUMMARY_NODES_Q, "nodes"),
            "relationships": _scalar(session, SUMMARY_RELS_Q, "relationships"),
        }

    report = {
        "database": database,
        "export_dir": Path(export_dir).as_posix(),
        "wiped_nodes": wiped_nodes,
        "restored": {
            "nodes": restored_nodes,
            "relationships": restored_relationships,
        },
        "database_counts": database_counts,
        "batch_size": batch_size,
    }
    progress_line("restore complete")
    progress_line(f"loaded nodes: {restored_nodes:,}")
    progress_line(f"loaded relationships: {restored_relationships:,}")
    progress_line(f"database nodes: {database_counts['nodes']:,}")
    progress_line(f"database relationships: {database_counts['relationships']:,}")
    return report


def _require_env(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    missing = [key for key in REQUIRED_ENV if not environ.get(key)]
    if missing:
        raise ValueError("Missing required environment variables: " + ", ".join(missing))
    return {key: environ[key] for key in REQUIRED_ENV}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore data/exports/live-graph-export into local Docker Neo4j."
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=DEFAULT_EXPORT_DIR,
        help=f"Export directory (default: {DEFAULT_EXPORT_DIR})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10_000,
        help="Rows per write batch (default: 10000)",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Delete existing graph data before restoring.",
    )
    parser.add_argument(
        "--i-know-this-is-not-local",
        action="store_true",
        help="Override the Aura/neo4j.io URI guard.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        env = _require_env()
        assert_local_target(
            env["NEO4J_URI"],
            override=args.i_know_this_is_not_local,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    from neo4j import GraphDatabase

    usage = (
        "usage: NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j "
        "NEO4J_PASSWORD=... NEO4J_DATABASE=neo4j "
        "python scripts/restore_neo4j_local.py [--export-dir "
        f"{args.export_dir}] [--wipe]"
    )
    print(usage)

    driver = GraphDatabase.driver(
        env["NEO4J_URI"],
        auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]),
    )
    try:
        restore_neo4j_local(
            driver,
            database=env["NEO4J_DATABASE"],
            export_dir=args.export_dir,
            batch_size=args.batch_size,
            wipe=args.wipe,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
