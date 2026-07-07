"""Bake the local public serving substrate from composed graph-v2 inputs.

S0 intentionally stays small: it mirrors the live load inputs that currently
reach Aura (graph-v2 projection plus the operator attach overlay), strips
vector/staging properties, writes the SQLite skeleton, and emits a source of
truth count report.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

DEFAULT_NODE_SOURCES = (
    Path("data/projected/graph-v2/nodes.jsonl"),
    Path("data/review/attach/nodes.jsonl"),
)
DEFAULT_EDGE_SOURCES = (
    Path("data/projected/graph-v2/edges.jsonl"),
    Path("data/review/attach/edges.jsonl"),
)
DEFAULT_REGISTRY_PATH = Path("registry/node-types.json")
DEFAULT_SQLITE_PATH = Path("data/exports/public-substrate.sqlite")
DEFAULT_REPORT_PATH = Path("data/exports/substrate-bake-report.json")
SQLITE_BUDGET_BYTES = 250 * 1024 * 1024

NODE_GATE_TYPES = ("Membership", "EconomicInterest")
EDGE_GATE_RELS = (
    "INTEREST_IN",
    "DISCLOSED_AS",
    "MEMBER",
    "MEMBER_OF_ORG",
    "DERIVED_FROM_RECORD",
)


@dataclass
class BakedNode:
    id: str
    type: str
    search_label: str
    props: dict
    labels: set[str] = field(default_factory=set)


@dataclass
class BakedEdge:
    source: str
    rel: str
    target: str
    props: dict = field(default_factory=dict)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"JSONL input not found: {path}")
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_no}: {exc}") from exc
            rows.append(row)
    return rows


def _load_known_types(registry_path: Path) -> set[str]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    known = set(registry.get("graph_node_types", {}))
    known.update(registry.get("support_labels", []))
    return known


def _is_stripped_property(key: str) -> bool:
    return (
        key == "payload_json"
        or key == "embedding"
        or key == "umap"
        or key.startswith("umap_")
        or key.endswith("_pending")
    )


def _clean_props(props: dict | None) -> dict:
    clean: dict = {}
    for key, value in (props or {}).items():
        if _is_stripped_property(key):
            continue
        clean[key] = value
    return clean


def _node_live_props(row: dict) -> dict:
    props = _clean_props(row.get("properties"))
    # load_neo4j_v2 sets these as top-level Neo4j properties outside row.props.
    props["display_label"] = row.get("display_label", "")
    props["promotion_state"] = row.get("promotion_state", "")
    return props


def _edge_live_props(row: dict) -> dict:
    return _clean_props(row.get("properties"))


def _json_dumps_stable(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _search_label(row: dict, props: dict) -> str:
    for key in (
        "search_label",
        "display_label",
        "name",
        "title",
        "caption",
        "record_title",
        "label",
    ):
        value = row.get(key)
        if value:
            return str(value)
        value = props.get(key)
        if value:
            return str(value)
    return str(row["id"])


def _validate_node_types(rows: Iterable[dict], known_types: set[str]) -> None:
    unknown = sorted(
        {
            str(row.get("node_type"))
            for row in rows
            if row.get("node_type") not in known_types
        }
    )
    if unknown:
        raise ValueError(
            "Unknown node_type values not present in registry/node-types.json: "
            + ", ".join(unknown)
        )


def _group_nodes_like_loader(rows: list[dict]) -> OrderedDict[tuple[str, ...], list[dict]]:
    by_labels: OrderedDict[tuple[str, ...], list[dict]] = OrderedDict()
    for row in rows:
        labels = tuple(row.get("labels") or [row["node_type"]])
        by_labels.setdefault(labels, []).append(row)
    return by_labels


def _compose_nodes(rows: list[dict]) -> tuple[dict[str, BakedNode], dict]:
    final: dict[str, BakedNode] = {}
    input_counts = Counter(str(row["id"]) for row in rows)
    duplicate_ids = {
        node_id: count for node_id, count in sorted(input_counts.items()) if count > 1
    }

    for labels, group in _group_nodes_like_loader(rows).items():
        for row in group:
            node_id = str(row["id"])
            props = _node_live_props(row)
            if node_id not in final:
                final[node_id] = BakedNode(
                    id=node_id,
                    type=str(row["node_type"]),
                    search_label=_search_label(row, props),
                    props={},
                    labels=set(),
                )
            baked = final[node_id]
            baked.labels.update(labels)
            baked.props.update(props)
            baked.type = str(row["node_type"])
            baked.search_label = _search_label(row, baked.props)

    return final, {
        "input_duplicate_node_ids": len(duplicate_ids),
        "input_duplicate_node_rows": sum(duplicate_ids.values()) - len(duplicate_ids),
        "merged_duplicate_node_ids_sample": list(duplicate_ids)[:20],
    }


def _compose_edges(rows: list[dict]) -> tuple[dict[tuple[str, str, str], BakedEdge], dict]:
    final: dict[tuple[str, str, str], BakedEdge] = {}
    input_counts: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        key = (
            str(row["source_id"]),
            str(row["relationship_type"]),
            str(row["target_id"]),
        )
        input_counts[key] += 1
        if key not in final:
            final[key] = BakedEdge(source=key[0], rel=key[1], target=key[2], props={})
        final[key].props.update(_edge_live_props(row))

    duplicate_edges = {key: count for key, count in input_counts.items() if count > 1}
    return final, {
        "input_duplicate_edge_triples": len(duplicate_edges),
        "input_duplicate_edge_rows": sum(duplicate_edges.values()) - len(duplicate_edges),
    }


def _missing_endpoint_report(
    node_ids: set[str],
    edges: Iterable[BakedEdge],
) -> dict:
    by_rel: Counter[str] = Counter()
    total = 0
    sample: list[dict] = []
    for edge in edges:
        source_missing = edge.source not in node_ids
        target_missing = edge.target not in node_ids
        if not source_missing and not target_missing:
            continue
        total += 1
        by_rel[edge.rel] += 1
        if len(sample) < 20:
            sample.append({
                "source": edge.source,
                "rel": edge.rel,
                "target": edge.target,
                "source_missing": source_missing,
                "target_missing": target_missing,
            })
    return {
        "total": total,
        "by_rel": dict(sorted(by_rel.items())),
        "sample": sample,
    }


def _gate_counts(nodes: dict[str, BakedNode], edges: dict[tuple[str, str, str], BakedEdge]) -> dict:
    node_type_counts = Counter(node.type for node in nodes.values())
    edge_rel_counts = Counter(edge.rel for edge in edges.values())
    counts = {
        "SAME_AS_with_assertion_id": sum(
            1
            for edge in edges.values()
            if edge.rel == "SAME_AS" and edge.props.get("assertion_id")
        ),
    }
    for node_type in NODE_GATE_TYPES:
        counts[node_type] = node_type_counts.get(node_type, 0)
    for rel in EDGE_GATE_RELS:
        counts[rel] = edge_rel_counts.get(rel, 0)
    return counts


def _write_sqlite(
    sqlite_path: Path,
    nodes: dict[str, BakedNode],
    edges: dict[tuple[str, str, str], BakedEdge],
) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{sqlite_path.name}.",
        suffix=".tmp",
        dir=str(sqlite_path.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with sqlite3.connect(temp_path) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute("PRAGMA page_size=4096")
            conn.executescript(
                """
                CREATE TABLE nodes (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    search_label TEXT NOT NULL,
                    props TEXT NOT NULL CHECK (json_valid(props))
                );
                CREATE TABLE edges (
                    source TEXT NOT NULL,
                    rel TEXT NOT NULL,
                    target TEXT NOT NULL
                );
                CREATE INDEX idx_edges_source_rel_target
                    ON edges(source, rel, target);
                CREATE INDEX idx_edges_target_rel_source
                    ON edges(target, rel, source);
                CREATE INDEX idx_nodes_type_search_label_id
                    ON nodes(type, search_label, id);
                """
            )
            conn.executemany(
                "INSERT INTO nodes(id, type, search_label, props) VALUES (?, ?, ?, ?)",
                [
                    (
                        node.id,
                        node.type,
                        node.search_label,
                        _json_dumps_stable(node.props),
                    )
                    for node in sorted(nodes.values(), key=lambda item: item.id)
                ],
            )
            conn.executemany(
                "INSERT INTO edges(source, rel, target) VALUES (?, ?, ?)",
                [
                    (edge.source, edge.rel, edge.target)
                    for edge in sorted(
                        edges.values(),
                        key=lambda item: (item.source, item.rel, item.target),
                    )
                ],
            )
            conn.execute("PRAGMA optimize")
        os.replace(temp_path, sqlite_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _source_strings(paths: Iterable[Path]) -> list[str]:
    return [path.as_posix() for path in paths]


def _write_report(report_path: Path, report: dict) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{report_path.name}.",
        suffix=".tmp",
        dir=str(report_path.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, report_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def bake_substrate(
    node_sources: Iterable[Path | str] = DEFAULT_NODE_SOURCES,
    edge_sources: Iterable[Path | str] = DEFAULT_EDGE_SOURCES,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
    sqlite_path: Path | str = DEFAULT_SQLITE_PATH,
    report_path: Path | str = DEFAULT_REPORT_PATH,
) -> dict:
    node_paths = [Path(path) for path in node_sources]
    edge_paths = [Path(path) for path in edge_sources]
    registry = Path(registry_path)
    sqlite_out = Path(sqlite_path)
    report_out = Path(report_path)

    node_rows: list[dict] = []
    edge_rows: list[dict] = []
    for path in node_paths:
        node_rows.extend(_read_jsonl(path))
    for path in edge_paths:
        edge_rows.extend(_read_jsonl(path))

    known_types = _load_known_types(registry)
    _validate_node_types(node_rows, known_types)
    nodes, node_validation = _compose_nodes(node_rows)
    edges, edge_validation = _compose_edges(edge_rows)

    _write_sqlite(sqlite_out, nodes, edges)
    sqlite_size = sqlite_out.stat().st_size
    node_counts = Counter(node.type for node in nodes.values())
    edge_counts = Counter(edge.rel for edge in edges.values())
    validation = {
        **node_validation,
        **edge_validation,
        "unknown_node_types": [],
        "missing_endpoint_edges": _missing_endpoint_report(set(nodes), edges.values()),
    }
    report = {
        "inputs": {
            "node_sources": _source_strings(node_paths),
            "edge_sources": _source_strings(edge_paths),
            "registry": registry.as_posix(),
            "composition_note": (
                "Mirrors scripts/load_neo4j_v2.py plus data/review/run_load.py "
                "attach overlay; no network or production writes."
            ),
        },
        "totals": {
            "nodes": len(nodes),
            "edges": len(edges),
        },
        "node_counts_by_type": dict(sorted(node_counts.items())),
        "edge_counts_by_rel": dict(sorted(edge_counts.items())),
        "gate_counts": _gate_counts(nodes, edges),
        "sqlite": {
            "size_bytes": sqlite_size,
            "size_mib": round(sqlite_size / (1024 * 1024), 6),
            "budget_bytes": SQLITE_BUDGET_BYTES,
            "budget_mib": 250,
            "within_budget": sqlite_size <= SQLITE_BUDGET_BYTES,
        },
        "validation": validation,
    }
    _write_report(report_out, report)
    return report


def _print_summary(report: dict, sqlite_path: Path, report_path: Path) -> None:
    print("Public substrate bake complete")
    print(f"nodes: {report['totals']['nodes']:,}")
    print(f"edges: {report['totals']['edges']:,}")
    print("gate counts:")
    for key, value in report["gate_counts"].items():
        print(f"  {key}: {value:,}")
    sqlite = report["sqlite"]
    print(
        "sqlite size: "
        f"{sqlite['size_bytes']:,} bytes "
        f"({sqlite['size_mib']:.3f} MiB) / "
        f"{sqlite['budget_mib']} MiB budget "
        f"=> {'OK' if sqlite['within_budget'] else 'OVER BUDGET'}"
    )
    missing = report["validation"]["missing_endpoint_edges"]["total"]
    dup_nodes = report["validation"]["input_duplicate_node_ids"]
    dup_edges = report["validation"]["input_duplicate_edge_triples"]
    if dup_nodes:
        print(f"input duplicate node ids merged with loader MERGE semantics: {dup_nodes:,}")
    if dup_edges:
        print(f"input duplicate edge triples merged with loader MERGE semantics: {dup_edges:,}")
    if missing:
        print(f"missing endpoint edge rows reported: {missing:,}")
    print(f"sqlite: {sqlite_path}")
    print(f"report: {report_path}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bake data/exports/public-substrate.sqlite from composed graph-v2 inputs."
    )
    parser.add_argument(
        "--node-source",
        action="append",
        type=Path,
        dest="node_sources",
        help="Node JSONL input. Repeat to override defaults.",
    )
    parser.add_argument(
        "--edge-source",
        action="append",
        type=Path,
        dest="edge_sources",
        help="Edge JSONL input. Repeat to override defaults.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help=f"Node-type registry path (default: {DEFAULT_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=DEFAULT_SQLITE_PATH,
        help=f"SQLite output path (default: {DEFAULT_SQLITE_PATH})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"JSON report output path (default: {DEFAULT_REPORT_PATH})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    node_sources = args.node_sources or list(DEFAULT_NODE_SOURCES)
    edge_sources = args.edge_sources or list(DEFAULT_EDGE_SOURCES)
    try:
        report = bake_substrate(
            node_sources=node_sources,
            edge_sources=edge_sources,
            registry_path=args.registry,
            sqlite_path=args.sqlite,
            report_path=args.report,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_summary(report, args.sqlite, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
