"""Bake the local public serving substrate from composed graph inputs.

S0b supports both the old projection-sized bake and the full live-graph export
source. Live-export mode composes the full export with the operator attach
overlay, strips vector/staging properties, writes the SQLite skeleton, and
emits a source-of-truth count/drift report.
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
from datetime import datetime, timezone
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
DEFAULT_LIVE_EXPORT_DIR = Path("data/exports/live-graph-export")
DEFAULT_ATTACH_OVERLAY_DIR = Path("data/review/attach")
DEFAULT_REGISTRY_PATH = Path("registry/node-types.json")
DEFAULT_SQLITE_PATH = Path("data/exports/public-substrate.sqlite")
DEFAULT_REPORT_PATH = Path("data/exports/substrate-bake-report.json")
SQLITE_BUDGET_BYTES = 250 * 1024 * 1024
BAKE_VERSION = "S1b-1"
JURISDICTION_PLACE_TYPES = frozenset(("city", "town", "county"))

NODE_GATE_TYPES = ("Membership", "EconomicInterest")
EDGE_GATE_RELS = (
    "INTEREST_IN",
    "DISCLOSED_AS",
    "MEMBER",
    "MEMBER_OF_ORG",
    "DERIVED_FROM_RECORD",
)

# Python mirror of browse-queries.ts columnsForType + propKeyForFactLabel.
# Keep this self-contained so the bake can run without the TS app toolchain.
BROWSE_FACT_LABELS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "Person": ("Name", "Current seat", "Jurisdiction", "Aliases"),
    "Decision": ("Decided", "Institution", "Vote", "Status"),
    "Project": ("Name", "Status", "Address", "Jurisdiction"),
    "Program": ("Name", "Status", "Type", "Jurisdiction"),
    "Case": ("Caption", "Docket", "Filed", "Closed", "Status"),
    "Meeting": ("Title", "Date", "Institution", "Type"),
    "Filing": ("Type", "Signed", "Period", "Filer"),
    "Committee": ("Name", "FPPC ID", "Treasurer", "Candidate"),
    "Organization": ("Name", "Subtype", "Jurisdiction", "Website"),
    "MoneyFlow": ("Amount", "Date", "Type", "Schedule"),
    "Seat": ("Title", "Institution", "Jurisdiction"),
    "SeatService": ("Seat", "Person", "Start", "End"),
    "Election": ("Title", "Date", "Type", "Jurisdiction"),
    "Candidacy": ("Candidate", "Seat", "Election", "Outcome"),
    "AgendaItem": ("Heading", "Meeting", "Date", "Item"),
    "Proceeding": ("Title", "Date", "Case", "Type"),
    "Agreement": ("Title", "Type", "Effective", "Parties"),
    "Amendment": ("Title", "Parent", "Effective"),
    "Record": ("Record type", "Captured", "Artifact", "Public URL"),
    "Place": ("Name", "Type", "Parent"),
    "Issue": ("Name", "Description"),
    "Membership": ("Person", "Organization", "Role", "Period", "Source"),
    "EconomicInterest": (
        "Interest type",
        "Counterparty",
        "Amount",
        "Position",
        "Schedule",
    ),
}

BROWSE_PROP_KEY_MAP: dict[str, dict[str, str]] = {
    "Person": {
        "current seat": "current_seat_display",
        "jurisdiction": "jurisdiction_name",
        "aliases": "aliases",
    },
    "Decision": {
        "decided": "decided_at",
        "institution": "institution_name",
        "vote": "vote_summary",
        "status": "status",
    },
    "Project": {
        "status": "status",
        "address": "address",
        "jurisdiction": "jurisdiction_name",
    },
    "Program": {
        "status": "status",
        "type": "program_type",
        "jurisdiction": "jurisdiction_name",
    },
    "Case": {
        "caption": "caption",
        "docket": "docket_number",
        "filed": "filed_at",
        "closed": "closed_at",
        "status": "status",
    },
    "Meeting": {
        "title": "title",
        "date": "meeting_date",
        "institution": "institution_name",
        "type": "meeting_type",
    },
    "Filing": {
        "type": "filing_type",
        "signed": "signed_at",
        "period": "period_start",
        "filer": "filed_by_name",
    },
    "Committee": {
        "fppc id": "fppc_id",
        "treasurer": "treasurer",
        "candidate": "candidate_name",
    },
    "Organization": {
        "subtype": "subtype",
        "jurisdiction": "jurisdiction_name",
        "website": "website",
    },
    "MoneyFlow": {
        "amount": "amount",
        "date": "flow_date",
        "type": "flow_type",
        "schedule": "source_schedule",
    },
    "Seat": {
        "title": "title",
        "institution": "institution_name",
        "jurisdiction": "jurisdiction_name",
    },
    "SeatService": {
        "seat": "seat_title",
        "person": "person_name",
        "start": "started_at",
        "end": "ended_at",
    },
    "Election": {
        "title": "name",
        "date": "election_date",
        "type": "election_type",
        "jurisdiction": "jurisdiction_name",
    },
    "Candidacy": {
        "candidate": "person_name",
        "seat": "seat_title",
        "election": "election_name",
        "outcome": "outcome",
    },
    "AgendaItem": {
        "heading": "heading",
        "meeting": "meeting_title",
        "date": "meeting_date",
        "item": "item_number",
    },
    "Proceeding": {
        "title": "title",
        "date": "occurred_at",
        "case": "case_caption",
        "type": "proceeding_type",
    },
    "Agreement": {
        "title": "title",
        "type": "agreement_type",
        "effective": "effective_date",
        "parties": "parties",
    },
    "Amendment": {
        "title": "title",
        "parent": "parent_title",
        "effective": "effective_date",
    },
    "Record": {
        "record type": "record_type",
        "captured": "captured_at",
        "artifact": "preferred_display_artifact",
        "public url": "preferred_public_url",
    },
    "Place": {
        "type": "place_type",
        "parent": "parent_name",
    },
    "Issue": {
        "description": "description",
    },
    "Membership": {
        "person": "person_name",
        "organization": "organization_name",
        "role": "role",
        "period": "started_at",
        "source": "source_basis",
    },
    "EconomicInterest": {
        "interest type": "interest_type",
        "counterparty": "counterparty_name_raw",
        "amount": "amount_band",
        "position": "position",
        "schedule": "schedule",
    },
}


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
    registry = _load_type_registry(registry_path)
    return registry["known_types"]


def _load_type_registry(registry_path: Path) -> dict:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    graph_types = set(registry.get("graph_node_types", {}))
    support_labels = set(registry.get("support_labels", []))
    known = set(registry.get("graph_node_types", {}))
    known.update(registry.get("support_labels", []))
    return {
        "known_types": known,
        "graph_types": graph_types,
        "support_labels": support_labels,
        "organization_subtypes": set(registry.get("organization_subtypes", [])),
        "id_prefixes": dict(registry.get("id_prefixes", {})),
    }


def _is_stripped_property(key: str) -> bool:
    return (
        key == "payload_json"
        or key == "embedding"
        or key.startswith("umap")
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
    if "search_label" in row:
        props["search_label"] = row.get("search_label", "")
    if "display_label" in row:
        props["display_label"] = row.get("display_label", "")
    if "promotion_state" in row:
        props["promotion_state"] = row.get("promotion_state", "")
    return props


def _edge_live_props(row: dict) -> dict:
    return _clean_props(row.get("properties"))


def _json_dumps_stable(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _prop_key_for_fact_label(node_type: str, label: str) -> str:
    key = label.lower()
    return BROWSE_PROP_KEY_MAP.get(node_type, {}).get(key, "_".join(key.split()))


def _browse_column_keys_for_type(node_type: str) -> tuple[str | None, str | None]:
    extras = [
        _prop_key_for_fact_label(node_type, label)
        for label in BROWSE_FACT_LABELS_BY_TYPE.get(node_type, ())
        if label not in {"ID", "Name"}
    ]
    padded = [*extras[:2], None, None]
    return padded[0], padded[1]


def _browse_search_label(node: BakedNode) -> str:
    for key in ("search_label", "name"):
        value = node.props.get(key)
        if value:
            return str(value)
    return node.id


def _json_prop_value_or_none(props: dict, key: str | None) -> str | None:
    if key is None or key not in props:
        return None
    return _json_dumps_stable(props[key])


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


def _infer_node_type(row: dict, type_registry: dict) -> str | None:
    node_id = str(row["id"])
    labels = [str(label) for label in row.get("labels") or []]
    for prefix, node_type in type_registry["id_prefixes"].items():
        if node_id.startswith(prefix):
            return str(node_type)
    for label in labels:
        if label in type_registry["graph_types"]:
            return label
    if any(label in type_registry["organization_subtypes"] for label in labels):
        return "Organization"
    for label in labels:
        if label in type_registry["support_labels"]:
            return label
    return None


def _normalize_node_row(row: dict, type_registry: dict) -> dict:
    normalized = dict(row)
    normalized["id"] = str(row["id"])
    normalized["labels"] = [str(label) for label in row.get("labels") or []]
    if "node_type" not in normalized:
        node_type = _infer_node_type(normalized, type_registry)
        if node_type is None:
            raise ValueError(
                "Unable to infer node_type for live-export node "
                f"{normalized['id']!r} with labels {normalized['labels']!r}"
            )
        normalized["node_type"] = node_type
    if not normalized["labels"]:
        normalized["labels"] = [str(normalized["node_type"])]
    normalized["properties"] = normalized.get("properties") or {}
    return normalized


def _normalize_edge_row(row: dict) -> dict:
    try:
        source_id = row["source_id"]
    except KeyError:
        source_id = row["start_id"]
    try:
        target_id = row["target_id"]
    except KeyError:
        target_id = row["end_id"]
    rel = row.get("relationship_type", row.get("type"))
    if rel is None:
        raise ValueError(f"Edge row missing relationship type: {row!r}")
    properties = row["properties"] if "properties" in row else row.get("props", {})
    return {
        "source_id": str(source_id),
        "relationship_type": str(rel),
        "target_id": str(target_id),
        "properties": properties or {},
    }


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


def _edge_triple(row: dict) -> tuple[str, str, str]:
    return (
        str(row["source_id"]),
        str(row["relationship_type"]),
        str(row["target_id"]),
    )


def _is_stamped_same_as(row: dict) -> bool:
    return (
        row.get("relationship_type") == "SAME_AS"
        and bool((row.get("properties") or {}).get("assertion_id"))
    )


def _is_legacy_unstamped_same_as(row: dict) -> bool:
    return (
        row.get("relationship_type") == "SAME_AS"
        and not (row.get("properties") or {}).get("assertion_id")
    )


def _triple_report(key: tuple[str, str, str]) -> dict:
    return {"source": key[0], "rel": key[1], "target": key[2]}


def _live_export_edge_composition(
    live_edges: list[dict],
    overlay_edges: list[dict],
) -> tuple[list[dict], dict]:
    live_stamped = {_edge_triple(row) for row in live_edges if _is_stamped_same_as(row)}
    overlay_stamped = {
        _edge_triple(row) for row in overlay_edges if _is_stamped_same_as(row)
    }
    overlay_missing_live = sorted(overlay_stamped - live_stamped)
    live_missing_overlay = sorted(live_stamped - overlay_stamped)
    legacy_unstamped_count = sum(
        1 for row in live_edges if _is_legacy_unstamped_same_as(row)
    )

    # The overlay is the stamped SAME_AS authority. Keep legacy unstamped live
    # SAME_AS for parity, but drop every live stamped SAME_AS before appending
    # overlay edges.
    composed_edges = [
        row for row in live_edges if not _is_stamped_same_as(row)
    ] + overlay_edges
    drift = {
        "live_stamped_count": len(live_stamped),
        "overlay_stamped_count": len(overlay_stamped),
        "overlay_rows_missing_live_count": len(overlay_missing_live),
        "overlay_rows_missing_live_sample": [
            _triple_report(key) for key in overlay_missing_live[:20]
        ],
        "live_stamped_rows_missing_overlay_count": len(live_missing_overlay),
        "live_stamped_rows_missing_overlay_sample": [
            _triple_report(key) for key in live_missing_overlay[:20]
        ],
        "legacy_unstamped_count": legacy_unstamped_count,
    }
    return composed_edges, drift


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


def _source_as_of_date(paths: Iterable[Path]) -> str:
    latest_mtime = max(path.stat().st_mtime for path in paths)
    return datetime.fromtimestamp(latest_mtime, timezone.utc).date().isoformat()


def _jurisdiction_count(nodes: dict[str, BakedNode]) -> int:
    return sum(
        1
        for node in nodes.values()
        if node.type == "Place"
        and node.props.get("place_type") in JURISDICTION_PLACE_TYPES
    )


def _status_manifest(
    nodes: dict[str, BakedNode],
    edges: dict[tuple[str, str, str], BakedEdge],
    as_of_date: str,
) -> dict:
    node_counts = Counter(node.type for node in nodes.values())
    return {
        "as_of_date": as_of_date,
        "bake_version": BAKE_VERSION,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "jurisdiction_count": _jurisdiction_count(nodes),
        "per_type_counts": dict(sorted(node_counts.items())),
    }


def _catalog_payload(status_manifest: dict) -> dict:
    return {
        **status_manifest,
        "built_at": status_manifest["as_of_date"],
        "counts": dict(status_manifest["per_type_counts"]),
    }


def _write_sqlite(
    sqlite_path: Path,
    nodes: dict[str, BakedNode],
    edges: dict[tuple[str, str, str], BakedEdge],
    as_of_date: str,
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
                CREATE TABLE browse_rows (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    search_label TEXT NOT NULL,
                    label_lower TEXT NOT NULL,
                    col1_key TEXT,
                    col1_value TEXT,
                    col2_key TEXT,
                    col2_value TEXT
                );
                CREATE TABLE meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE INDEX idx_edges_source_rel_target
                    ON edges(source, rel, target);
                CREATE INDEX idx_edges_target_rel_source
                    ON edges(target, rel, source);
                CREATE INDEX idx_edges_rel_source_target
                    ON edges(rel, source, target);
                CREATE INDEX idx_nodes_type_search_label_id
                    ON nodes(type, search_label, id);
                CREATE INDEX idx_nodes_decision_data_query
                    ON nodes(
                        type,
                        json_extract(props, '$.decided_at'),
                        json_extract(props, '$.institution_id')
                    )
                    WHERE type = 'Decision';
                CREATE INDEX idx_nodes_moneyflow_data_query
                    ON nodes(
                        type,
                        json_extract(props, '$.flow_date'),
                        json_extract(props, '$.amount'),
                        json_extract(props, '$.flow_type')
                    )
                    WHERE type = 'MoneyFlow';
                CREATE INDEX idx_nodes_filing_data_query
                    ON nodes(
                        type,
                        json_extract(props, '$.signed_at'),
                        json_extract(props, '$.filing_type')
                    )
                    WHERE type = 'Filing';
                CREATE INDEX idx_nodes_agreement_data_query
                    ON nodes(type, json_extract(props, '$.effective_date'))
                    WHERE type = 'Agreement';
                CREATE INDEX idx_nodes_proceeding_data_query
                    ON nodes(type, json_extract(props, '$.occurred_at'))
                    WHERE type = 'Proceeding';
                CREATE INDEX idx_nodes_record_data_query
                    ON nodes(type, json_extract(props, '$.captured_at'))
                    WHERE type = 'Record';
                CREATE INDEX idx_browse_rows_type_id
                    ON browse_rows(type, id);
                CREATE INDEX idx_browse_rows_label_lower
                    ON browse_rows(label_lower);
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
                """
                INSERT INTO browse_rows(
                    id,
                    type,
                    search_label,
                    label_lower,
                    col1_key,
                    col1_value,
                    col2_key,
                    col2_value
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        node.id,
                        node.type,
                        browse_label,
                        browse_label.lower(),
                        col1_key,
                        _json_prop_value_or_none(node.props, col1_key),
                        col2_key,
                        _json_prop_value_or_none(node.props, col2_key),
                    )
                    for node in sorted(nodes.values(), key=lambda item: item.id)
                    for browse_label in [_browse_search_label(node)]
                    for col1_key, col2_key in [_browse_column_keys_for_type(node.type)]
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
            conn.executemany(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                [
                    ("as_of_date", as_of_date),
                    ("bake_version", BAKE_VERSION),
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
    node_sources: Iterable[Path | str] | None = None,
    edge_sources: Iterable[Path | str] | None = None,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
    sqlite_path: Path | str = DEFAULT_SQLITE_PATH,
    report_path: Path | str = DEFAULT_REPORT_PATH,
    *,
    source: str = "projection",
    live_export_dir: Path | str = DEFAULT_LIVE_EXPORT_DIR,
    attach_overlay_dir: Path | str = DEFAULT_ATTACH_OVERLAY_DIR,
) -> dict:
    registry = Path(registry_path)
    sqlite_out = Path(sqlite_path)
    report_out = Path(report_path)

    if source not in {"projection", "live-export"}:
        raise ValueError("source must be 'projection' or 'live-export'")

    type_registry = _load_type_registry(registry)
    known_types = type_registry["known_types"]
    same_as_overlay_drift: dict | None = None

    if source == "live-export":
        live_dir = Path(live_export_dir)
        overlay_dir = Path(attach_overlay_dir)
        node_paths = [live_dir / "nodes.jsonl", overlay_dir / "nodes.jsonl"]
        edge_paths = [live_dir / "edges.jsonl", overlay_dir / "edges.jsonl"]
        live_nodes = [
            _normalize_node_row(row, type_registry)
            for row in _read_jsonl(node_paths[0])
        ]
        overlay_nodes = [
            _normalize_node_row(row, type_registry)
            for row in _read_jsonl(node_paths[1])
        ]
        live_edges = [_normalize_edge_row(row) for row in _read_jsonl(edge_paths[0])]
        overlay_edges = [
            _normalize_edge_row(row) for row in _read_jsonl(edge_paths[1])
        ]
        node_rows = live_nodes + overlay_nodes
        edge_rows, same_as_overlay_drift = _live_export_edge_composition(
            live_edges, overlay_edges
        )
    else:
        node_paths = [Path(path) for path in (node_sources or DEFAULT_NODE_SOURCES)]
        edge_paths = [Path(path) for path in (edge_sources or DEFAULT_EDGE_SOURCES)]
        node_rows = [
            _normalize_node_row(row, type_registry)
            for path in node_paths
            for row in _read_jsonl(path)
        ]
        edge_rows = [
            _normalize_edge_row(row)
            for path in edge_paths
            for row in _read_jsonl(path)
        ]

    _validate_node_types(node_rows, known_types)
    nodes, node_validation = _compose_nodes(node_rows)
    edges, edge_validation = _compose_edges(edge_rows)
    as_of_date = _source_as_of_date([*node_paths, *edge_paths])
    status_manifest = _status_manifest(nodes, edges, as_of_date)

    _write_sqlite(sqlite_out, nodes, edges, as_of_date)
    _write_report(sqlite_out.parent / "status_manifest.json", status_manifest)
    _write_report(
        sqlite_out.parent / "catalog.json",
        _catalog_payload(status_manifest),
    )
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
            "source": source,
            "node_sources": _source_strings(node_paths),
            "edge_sources": _source_strings(edge_paths),
            "registry": registry.as_posix(),
            "composition_note": (
                "Projection mode mirrors the historical graph-v2 projection plus "
                "attach overlay. Live-export mode composes the full live export "
                "with the attach overlay and treats overlay stamped SAME_AS as "
                "authoritative; no network or production writes happen during bake."
            ),
        },
        "totals": {
            "nodes": len(nodes),
            "edges": len(edges),
        },
        "metadata": {
            "as_of_date": as_of_date,
            "bake_version": BAKE_VERSION,
            "jurisdiction_count": status_manifest["jurisdiction_count"],
            "status_manifest": (
                sqlite_out.parent / "status_manifest.json"
            ).as_posix(),
            "catalog": (sqlite_out.parent / "catalog.json").as_posix(),
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
    if same_as_overlay_drift is not None:
        report["same_as_overlay_drift"] = same_as_overlay_drift
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
        description="Bake data/exports/public-substrate.sqlite from public graph inputs."
    )
    parser.add_argument(
        "--source",
        choices=("projection", "live-export"),
        default="projection",
        help="Input source mode (default: projection).",
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
        "--live-export-dir",
        type=Path,
        default=DEFAULT_LIVE_EXPORT_DIR,
        help=f"Live export dir for --source live-export (default: {DEFAULT_LIVE_EXPORT_DIR})",
    )
    parser.add_argument(
        "--attach-overlay-dir",
        type=Path,
        default=DEFAULT_ATTACH_OVERLAY_DIR,
        help=f"Attach overlay dir for --source live-export (default: {DEFAULT_ATTACH_OVERLAY_DIR})",
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
            source=args.source,
            live_export_dir=args.live_export_dir,
            attach_overlay_dir=args.attach_overlay_dir,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _print_summary(report, args.sqlite, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
