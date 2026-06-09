#!/usr/bin/env python3
"""
Build signature-subgraph JSON bundles per spec §5.5.

Reads registry/signature-subgraphs.yaml. For each entry, queries AuraDB to collect
the focus node + 2-hop neighborhood along the Phase-2 whitelist, computes headline
stats, and writes:
    data/projected/graph-v1/signature-subgraphs/manifest.json
    data/projected/graph-v1/signature-subgraphs/{slug}.json

Run after each successful ingestion. Nightly cron is a backstop (spec §3.7).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import yaml
from neo4j import GraphDatabase, Session

# Single source of truth for spec §3 → live AuraDB edge mapping.
# See docs/reference/2026-04-19-live-edge-catalog.md for the catalog.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from edge_vocabulary import (  # noqa: E402
    LEGAL_EDGES_LIVE,
    MONEY_EDGES_LIVE,
    PHASE2_WHITELIST_LIVE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = REPO_ROOT / "registry" / "signature-subgraphs.yaml"
OUT_DIR = REPO_ROOT / "data" / "projected" / "graph-v1" / "signature-subgraphs"

PHASE2_WHITELIST = PHASE2_WHITELIST_LIVE
WHITELIST_PATTERN = "|".join(PHASE2_WHITELIST)

MONEY_EDGES = set(MONEY_EDGES_LIVE)
LEGAL_EDGES = set(LEGAL_EDGES_LIVE)

MAX_NODES = 55  # per §5.5 target ≤ 60 nodes; small safety margin.

# Canonical type resolver — registry-derived (single source of truth:
# registry/node-types.json, via scripts/canonical_type.py). Re-exported so this
# module keeps a stable canonical_type / TYPE_BY_ID_PREFIX surface, but the
# prefix map (incl. the REAL `agenda-item-` prefix) lives in exactly ONE place —
# no hand-rolled second copy to drift stale (M1b: killed the `agendaitem-` bug).
from canonical_type import (  # noqa: E402
    TYPE_BY_ID_PREFIX,
    canonical_type,
)

KNOWN_TYPES = set(TYPE_BY_ID_PREFIX.values())


def classify_edge_style(rel_type: str) -> str:
    if rel_type in MONEY_EDGES:
        return "money"
    if rel_type in LEGAL_EDGES:
        return "legal-constrains"
    return "governance"


def build_node_payload(node: dict, role: str) -> dict:
    node_id = node["id"]
    label = node.get("search_label") or node.get("name") or node_id
    type_name = canonical_type(node.get("labels", []), node_id) or "Unknown"
    return {
        "id": node_id,
        "type": type_name,
        "label": label,
        "role": role,
        "route": f"/graph?focus={node_id}",
    }


def expand_template(template: str, stats: dict) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        val = stats.get(key)
        return str(val) if val is not None else ""
    return re.sub(r"\{\{(\w+)\}\}", repl, template).strip()


def fetch_subgraph(session: Session, focus_id: str) -> tuple[list[dict], list[dict], dict]:
    """Returns (nodes, edges, headline_stats)."""
    # Focus node + 1-hop + up to 2-hop along whitelist, capped at MAX_NODES.
    # Uses a single Cypher with APOC expandConfig-free pattern.
    query = f"""
    MATCH (f {{id: $focus_id}})
    OPTIONAL MATCH (f)-[r1:{WHITELIST_PATTERN}]-(n1)
    WHERE NOT n1:Place AND NOT n1:Issue
    WITH f, collect(DISTINCT {{node: n1, rel: r1}}) AS hop1_pairs
    UNWIND hop1_pairs AS p
    WITH f, hop1_pairs, p.node AS n1
    OPTIONAL MATCH (n1)-[r2:{WHITELIST_PATTERN}]-(n2)
    WHERE n2 <> f AND NOT n2:Place AND NOT n2:Issue
    WITH f, hop1_pairs, collect(DISTINCT {{src: n1, node: n2, rel: r2}}) AS hop2_pairs
    RETURN f, hop1_pairs, hop2_pairs
    LIMIT 1
    """
    record = session.run(query, focus_id=focus_id).single()
    if not record:
        raise RuntimeError(f"focus node not found: {focus_id}")

    focus = record["f"]
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    # Add focus as role=focus.
    nodes[focus["id"]] = {
        "id": focus["id"],
        "labels": list(focus.labels),
        **dict(focus),
    }

    for pair in record["hop1_pairs"] or []:
        if len(nodes) >= MAX_NODES:
            break
        n1, r1 = pair["node"], pair["rel"]
        if n1 is None or r1 is None:
            continue
        if n1["id"] not in nodes:
            nodes[n1["id"]] = {"id": n1["id"], "labels": list(n1.labels), **dict(n1)}
        edges.append({
            "source": r1.start_node["id"],
            "target": r1.end_node["id"],
            "type": r1.type,
        })

    for pair in record["hop2_pairs"] or []:
        src, n2, r2 = pair.get("src"), pair.get("node"), pair.get("rel")
        if n2 is None or r2 is None or src is None:
            continue
        if n2["id"] in nodes or len(nodes) >= MAX_NODES:
            if r2.start_node["id"] in nodes and r2.end_node["id"] in nodes:
                edges.append({
                    "source": r2.start_node["id"],
                    "target": r2.end_node["id"],
                    "type": r2.type,
                })
            continue
        nodes[n2["id"]] = {"id": n2["id"], "labels": list(n2.labels), **dict(n2)}
        edges.append({
            "source": r2.start_node["id"],
            "target": r2.end_node["id"],
            "type": r2.type,
        })

    # Build headline stats by counting types in the neighborhood.
    stats = _compute_stats(nodes.values())
    return list(nodes.values()), edges, stats


def _compute_stats(nodes) -> dict:
    counts: dict[str, int] = {}
    money_total = 0
    for node in nodes:
        for lbl in node.get("labels", []):
            counts[lbl] = counts.get(lbl, 0) + 1
        if "MoneyFlow" in node.get("labels", []):
            try:
                money_total += int(float(node.get("amount") or 0))
            except (ValueError, TypeError):
                pass

    return {
        "money_total": f"{money_total:,}" if money_total else "0",
        "decision_count": counts.get("Decision", 0),
        "counterparty_count": counts.get("Organization", 0) + counts.get("Person", 0),
        "record_count": counts.get("Record", 0),
        "case_count": counts.get("Case", 0),
        "agreement_count": counts.get("Agreement", 0),
        "proceeding_count": counts.get("Proceeding", 0),
        "constrained_decision_count": counts.get("Decision", 0),
        "seat_service_count": counts.get("SeatService", 0),
        "filing_count": counts.get("Filing", 0),
        "person_count": counts.get("Person", 0),
    }


def assign_role(node_id: str, focus_id: str, hop1_ids: set[str]) -> str:
    if node_id == focus_id:
        return "focus"
    if node_id in hop1_ids:
        return "primary"
    return "secondary"


def build_bundle(session: Session, entry: dict, built_at: str) -> dict:
    raw_nodes, raw_edges, stats = fetch_subgraph(session, entry["focus_node_id"])
    focus_id = entry["focus_node_id"]
    hop1_ids = {
        e["target"] if e["source"] == focus_id else e["source"]
        for e in raw_edges
        if e["source"] == focus_id or e["target"] == focus_id
    }

    nodes = [build_node_payload(n, assign_role(n["id"], focus_id, hop1_ids)) for n in raw_nodes]
    edges = [
        {
            "source": e["source"],
            "target": e["target"],
            "type": e["type"],
            "style": classify_edge_style(e["type"]),
        }
        for e in raw_edges
    ]

    caption = expand_template(entry["headline_stats_template"], stats)
    kicker = f"SIGNATURE SUBGRAPH · {entry['display_name'].upper()}"

    return {
        "slug": entry["slug"],
        "display_name": entry["display_name"],
        "built_at": built_at,
        "focus_node_id": focus_id,
        "headline_stats": {"caption": caption, "kicker": kicker},
        "nodes": nodes,
        "edges": edges,
    }


def main() -> int:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    registry = yaml.safe_load(REGISTRY.read_text())
    entries = registry["subgraphs"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    built_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    manifest_subgraphs = []
    # Fatal failures block the pipeline (bad registry). Warnings note data gaps
    # that should be fixed but don't block downstream steps.
    fatal_failures: list[str] = []
    warnings: list[str] = []
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            for entry in entries:
                try:
                    bundle = build_bundle(session, entry, built_at)
                except RuntimeError as exc:
                    fatal_failures.append(f"{entry['slug']}: focus missing — {exc}")
                    print(f"  FATAL {entry['slug']}: {exc}", file=sys.stderr)
                    continue
                node_count = len(bundle["nodes"])
                # Always write the bundle artifact for inspection, but only add
                # to the manifest if it has real connective content (focus + ≥1 neighbor).
                (OUT_DIR / f"{entry['slug']}.json").write_text(json.dumps(bundle, indent=2))
                if node_count < 2:
                    warnings.append(
                        f"{entry['slug']}: low-connectivity bundle ({node_count} node(s); expected focus + neighbors)"
                    )
                    print(
                        f"  WARN {entry['slug']}: only {node_count} node(s) — excluded from manifest",
                        file=sys.stderr,
                    )
                    continue
                manifest_subgraphs.append({
                    "slug": entry["slug"],
                    "display_name": entry["display_name"],
                    "focus_node_id": entry["focus_node_id"],
                })
                print(f"  {entry['slug']}: {node_count} nodes, {len(bundle['edges'])} edges")

    manifest = {"built_at": built_at, "subgraphs": manifest_subgraphs}
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(manifest_subgraphs)} bundles + manifest to {OUT_DIR}")

    if warnings:
        print("", file=sys.stderr)
        print(f"WARN: {len(warnings)} bundle(s) excluded from manifest (low connectivity):", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
        print("(These are expected until the spec/graph edge-vocabulary reconciliation lands — see Codex deferred item #2.)", file=sys.stderr)

    if fatal_failures:
        print("", file=sys.stderr)
        print(f"FATAL: {len(fatal_failures)} bundle(s) failed to build (registry mismatch):", file=sys.stderr)
        for f in fatal_failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
