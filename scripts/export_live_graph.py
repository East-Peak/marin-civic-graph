"""Export the full live graph to JSONL for public-substrate baking.

This is read-only against Neo4j. Tests use mocked driver/session objects; the
CLI is the only place that imports the real Neo4j driver and requires network.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Mapping, Any

DEFAULT_OUT_DIR = Path("data/exports/live-graph-export")
REQUIRED_ENV = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE")

NODES_PAGE_Q = (
    "MATCH (n) "
    "WHERE n.id IS NOT NULL "
    "WITH n ORDER BY n.id "
    "SKIP $skip LIMIT $limit "
    "RETURN n.id AS id, labels(n) AS labels, properties(n) AS properties"
)
EDGES_PAGE_Q = (
    "MATCH (s)-[r]->(t) "
    "WHERE s.id IS NOT NULL AND t.id IS NOT NULL "
    "WITH s, r, t ORDER BY s.id, type(r), t.id "
    "SKIP $skip LIMIT $limit "
    "RETURN s.id AS start_id, t.id AS end_id, type(r) AS type, "
    "properties(r) AS properties"
)

COUNT_NODES_Q = "MATCH (n) RETURN count(n) AS c"
COUNT_RELS_Q = "MATCH ()-[r]->() RETURN count(r) AS c"
G1_COUNT_QUERIES = (
    ("Membership", "MATCH (n:Membership) RETURN count(n) AS c"),
    ("EconomicInterest", "MATCH (n:EconomicInterest) RETURN count(n) AS c"),
    (
        "SAME_AS_with_assertion_id",
        "MATCH ()-[r:SAME_AS]->() WHERE r.assertion_id IS NOT NULL RETURN count(r) AS c",
    ),
    ("INTEREST_IN", "MATCH ()-[r:INTEREST_IN]->() RETURN count(r) AS c"),
    ("DISCLOSED_AS", "MATCH ()-[r:DISCLOSED_AS]->() RETURN count(r) AS c"),
    ("MEMBER", "MATCH ()-[r:MEMBER]->() RETURN count(r) AS c"),
    ("MEMBER_OF_ORG", "MATCH ()-[r:MEMBER_OF_ORG]->() RETURN count(r) AS c"),
    (
        "DERIVED_FROM_RECORD",
        "MATCH ()-[r:DERIVED_FROM_RECORD]->() RETURN count(r) AS c",
    ),
)


def _jsonify(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonify(item) for key, item in value.items()}
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return iso()
    return str(value)


def _is_stripped_property(key: str) -> bool:
    return (
        key == "embedding"
        or key == "payload_json"
        or key.startswith("umap")
        or key.endswith("_pending")
    )


def _clean_props(props: Mapping[str, Any] | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (props or {}).items():
        key = str(key)
        if _is_stripped_property(key):
            continue
        clean[key] = _jsonify(value)
    return clean


def _row_get(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row[key]
    return row[key]


def _stable_line(row: Mapping[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_rows_atomically(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)
    count = 0
    try:
        with temp_path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(_stable_line(row) + "\n")
                count += 1
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return count


def _iter_node_page_rows(session: Any, *, batch_size: int, progress: Callable[[str], None]):
    total = 0
    skip = 0
    while True:
        page = list(session.run(NODES_PAGE_Q, skip=skip, limit=batch_size))
        if not page:
            break
        for row in page:
            yield {
                "id": str(_row_get(row, "id")),
                "labels": sorted(str(label) for label in _row_get(row, "labels")),
                "properties": _clean_props(_row_get(row, "properties")),
            }
        total += len(page)
        progress(f"nodes batch skip={skip} wrote={len(page)} total={total}")
        skip += batch_size


def _iter_edge_page_rows(session: Any, *, batch_size: int, progress: Callable[[str], None]):
    total = 0
    skip = 0
    while True:
        page = list(session.run(EDGES_PAGE_Q, skip=skip, limit=batch_size))
        if not page:
            break
        for row in page:
            yield {
                "start_id": str(_row_get(row, "start_id")),
                "end_id": str(_row_get(row, "end_id")),
                "type": str(_row_get(row, "type")),
                "properties": _clean_props(_row_get(row, "properties")),
            }
        total += len(page)
        progress(f"edges batch skip={skip} wrote={len(page)} total={total}")
        skip += batch_size


def export_live_graph(
    driver: Any,
    *,
    database: str,
    out_dir: Path | str = DEFAULT_OUT_DIR,
    batch_size: int = 10_000,
    progress: Callable[[str], None] | None = print,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    progress_fn = progress or (lambda _line: None)
    out = Path(out_dir)
    nodes_path = out / "nodes.jsonl"
    edges_path = out / "edges.jsonl"

    with driver.session(database=database) as session:
        node_count = _write_rows_atomically(
            nodes_path,
            _iter_node_page_rows(session, batch_size=batch_size, progress=progress_fn),
        )
        edge_count = _write_rows_atomically(
            edges_path,
            _iter_edge_page_rows(session, batch_size=batch_size, progress=progress_fn),
        )

    return {
        "database": database,
        "out_dir": out.as_posix(),
        "paths": {
            "nodes": nodes_path.as_posix(),
            "edges": edges_path.as_posix(),
        },
        "totals": {"nodes": node_count, "edges": edge_count},
        "batch_size": batch_size,
    }


def _scalar_count(session: Any, query: str) -> int:
    return int(session.run(query).single()["c"])


def collect_gate_counts(session: Any) -> dict[str, int]:
    counts: dict[str, int] = {
        "total_nodes": _scalar_count(session, COUNT_NODES_Q),
        "total_relationships": _scalar_count(session, COUNT_RELS_Q),
    }
    for key, query in G1_COUNT_QUERIES:
        counts[key] = _scalar_count(session, query)
    return counts


def _print_counts(counts: Mapping[str, int]) -> None:
    print("live graph G1 gate counts:")
    for key, value in counts.items():
        print(f"{key}: {value:,}")


def _require_env(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    missing = [key for key in REQUIRED_ENV if not environ.get(key)]
    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )
    return {key: environ[key] for key in REQUIRED_ENV}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the full Neo4j live graph to "
            "data/exports/live-graph-export/{nodes,edges}.jsonl."
        )
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10_000,
        help="Rows per Neo4j page (default: 10000)",
    )
    parser.add_argument(
        "--counts-only",
        action="store_true",
        help="Print S0/G1 source-of-truth gate counts without writing JSONL.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        env = _require_env()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        env["NEO4J_URI"],
        auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]),
    )
    try:
        if args.counts_only:
            with driver.session(database=env["NEO4J_DATABASE"]) as session:
                _print_counts(collect_gate_counts(session))
        else:
            report = export_live_graph(
                driver,
                database=env["NEO4J_DATABASE"],
                out_dir=args.out_dir,
                batch_size=args.batch_size,
            )
            print("live graph export complete")
            print(f"nodes: {report['totals']['nodes']:,}")
            print(f"edges: {report['totals']['edges']:,}")
            print(f"nodes_jsonl: {report['paths']['nodes']}")
            print(f"edges_jsonl: {report['paths']['edges']}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
