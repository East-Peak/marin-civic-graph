#!/usr/bin/env python3
"""build_graph_v2.py — the v2-native graph projector.

Reads registry/import-manifest.yaml and emits settled-schema Person/Organization
nodes/edges DIRECTLY, in a single pass — collapsing today's two-stage
build_graph_projection (legacy Actor/Institution) -> migrate_graph_v2
(-> Person/Organization) pipeline. Behavior-preserving: byte-for-byte (field
level) identical to running the two stages, proven by projection_compare against
a golden captured from the current pipeline.

The single pass:
  1. Project all NODES from every bundle/section — reusing build_graph_projection's
     section-walking, filters, promotion_state, merge precedence, and ordering —
     then build the full old_id -> new_id map across ALL nodes and migrate each
     node inline (CaseParticipation drops out for conversion in step 3).
  2. Project all EDGES (field-derived, vote, relationship_passthrough, alias
     remap, missing-endpoint filter, dedup, ordering), then remap endpoints/props
     via the id-map and apply REL_TYPE_MAP renames.
  3. Convert CaseParticipation -> PARTY_TO, harvesting evidence from both the node
     and the dropped EVIDENCED_BY edges.
  4. Property remapping is SHALLOW — payload_json keeps legacy ids verbatim.
  5. Emit a migration-style report (remap / dropped-node / dropped-edge /
     conversion counts) for parity diagnostics.

No database. Reads import-manifest.yaml only (not the sha256 materialization
ledger). Does NOT retire the legacy scripts — they remain the golden source for
B-core.

Usage:
  python scripts/build_graph_v2.py
  python scripts/build_graph_v2.py --manifest registry/import-manifest.yaml \
      --output-dir data/projected/phase0-bcore/candidate-v2
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# scripts/ is not a package; ensure sibling modules are importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Identity stamped into the migration report so downstream readers (the query
# pack) can attribute a projection without re-deriving it.
PROJECTION_ID = "graph-v2-native"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

from graph_projection_lib import DEFAULT_MANIFEST_PATH, ROOT, load_json, read_manifest

# Reuse the shared projection-phase helpers verbatim.
from projection_helpers import (
    build_actor_alias_map,
    build_node_envelope,
    extract_edges_from_object,
    finalize_edge_for_output,
    finalize_node_for_output,
    merge_edge,
    merge_node,
    passthrough_relationships,
    remap_actor_aliases,
    should_include_object,
)

# Reuse the settled-schema transforms (golden-pinned against migration_mapping).
from graph_v2_transforms import (
    cp_to_party_to,
    edge_to_v2,
    migrate_id,
    node_to_v2,
    remap_props,
)


# ---------------------------------------------------------------------------
# Phase 1+2 (projection): manifest -> legacy node/edge envelopes
# ---------------------------------------------------------------------------

def project_legacy(manifest: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Reproduce build_graph_projection's projection in memory: returns the
    finalized, sorted legacy (Actor/Institution) nodes and edges — exactly what
    build_graph_projection writes to nodes.jsonl/edges.jsonl."""
    nodes_by_id: dict[str, dict] = {}
    raw_edges: list[dict] = []

    for bundle in manifest["bundles"]:
        bundle_path = (ROOT / bundle["path"]).resolve()
        payload = load_json(bundle_path)
        bundle_id = payload.get("bundle_id") or bundle_path.stem
        for section in bundle["sections"]:
            section_name = section["name"]
            items = payload.get(section_name) or []
            if section["mode"] == "relationship_passthrough":
                raw_edges.extend(passthrough_relationships(items, bundle_id))
                continue
            node_type = section["node_type"]
            promotion_state = section["promotion_state"]
            for obj in items:
                include, _reason = should_include_object(section, obj)
                if not include:
                    continue
                node = build_node_envelope(
                    node_type=node_type,
                    promotion_state=promotion_state,
                    bundle_id=bundle_id,
                    section_name=section_name,
                    obj=obj,
                )
                existing = nodes_by_id.get(node["id"])
                if existing is None:
                    nodes_by_id[node["id"]] = node
                else:
                    merged, _conflicts = merge_node(existing, node)
                    nodes_by_id[node["id"]] = merged
                raw_edges.extend(extract_edges_from_object(node_type, obj, bundle_id))

    known_node_ids = set(nodes_by_id)
    actor_alias_map = build_actor_alias_map(nodes_by_id)
    edges_by_key: dict[tuple[str, str, str], dict] = {}
    for edge in raw_edges:
        edge, _remapped = remap_actor_aliases(edge, actor_alias_map)
        if edge["source_id"] not in known_node_ids:
            continue
        if edge["target_id"] not in known_node_ids:
            continue
        key = (edge["source_id"], edge["relationship_type"], edge["target_id"])
        existing = edges_by_key.get(key)
        if existing is None:
            edges_by_key[key] = edge
        else:
            merged, _conflicts = merge_edge(existing, edge)
            edges_by_key[key] = merged

    nodes = sorted(
        (finalize_node_for_output(node) for node in nodes_by_id.values()),
        key=lambda item: (item["node_type"], item["id"]),
    )
    edges = sorted(
        (finalize_edge_for_output(edge) for edge in edges_by_key.values()),
        key=lambda item: (item["relationship_type"], item["source_id"], item["target_id"]),
    )
    return nodes, edges


# ---------------------------------------------------------------------------
# Migration: legacy envelopes -> settled-schema nodes/edges
# ---------------------------------------------------------------------------

def migrate(
    legacy_nodes: list[dict], legacy_edges: list[dict]
) -> tuple[list[dict], list[dict], dict[str, str], dict]:
    """Apply the inline migration (mirrors migrate_graph_v2.run_migration's five
    passes) to the legacy projection. Returns migrated nodes, migrated edges, the
    id-map, and a migration-style report."""
    # Pass 1: full old_id -> new_id map across ALL nodes first.
    id_map: dict[str, str] = {}
    for node in legacy_nodes:
        old_id = node["id"]
        new_id = migrate_id(old_id, node["node_type"], node.get("properties", {}))
        if new_id != old_id:
            id_map[old_id] = new_id

    # Pass 2: migrate nodes inline; CaseParticipation drops out for conversion.
    migrated_nodes: list[dict] = []
    cp_nodes: list[dict] = []
    nodes_by_type: dict[str, int] = defaultdict(int)
    for node in legacy_nodes:
        result = node_to_v2(node)
        if result is None:
            cp_nodes.append(node)
            continue
        # Second-pass remap of remaining (actor- etc.) property refs via id_map.
        result["properties"] = remap_props(result["properties"], id_map)
        migrated_nodes.append(result)
        nodes_by_type[result["node_type"]] += 1

    # Pass 3: harvest CaseParticipation evidence from dropped EVIDENCED_BY edges.
    cp_evidence: dict[str, list[str]] = defaultdict(list)
    for edge in legacy_edges:
        if (
            edge.get("relationship_type") == "EVIDENCED_BY"
            and edge["source_id"].startswith("casepart-")
        ):
            cp_evidence[edge["source_id"]].append(edge["target_id"])

    # Pass 4: migrate edges; casepart- endpoints drop out.
    migrated_edges: list[dict] = []
    dropped_edge_count = 0
    edges_by_type: dict[str, int] = defaultdict(int)
    for edge in legacy_edges:
        result = edge_to_v2(edge, id_map)
        if result is None:
            dropped_edge_count += 1
            continue
        migrated_edges.append(result)
        edges_by_type[result["relationship_type"]] += 1

    # Pass 5: convert CaseParticipation -> PARTY_TO (evidence from node + harvest).
    party_to_edges = cp_to_party_to(cp_nodes, dict(cp_evidence), id_map)
    for edge in party_to_edges:
        migrated_edges.append(edge)
        edges_by_type[edge["relationship_type"]] += 1

    report = {
        "remap_count": len(id_map),
        "source_node_count": len(legacy_nodes),
        "migrated_node_count": len(migrated_nodes),
        "dropped_node_count": len(cp_nodes),
        "source_edge_count": len(legacy_edges),
        "migrated_edge_count": len(migrated_edges),
        "dropped_edge_count": dropped_edge_count,
        "conversion_count": len(party_to_edges),
        "nodes_by_type": dict(nodes_by_type),
        "edges_by_type": dict(edges_by_type),
    }
    return migrated_nodes, migrated_edges, id_map, report


# ---------------------------------------------------------------------------
# Orchestration + output
# ---------------------------------------------------------------------------

def run(manifest_path, output_dir) -> dict:
    """Project + migrate in one pass; write settled-schema output; return report."""
    manifest = read_manifest(Path(manifest_path).resolve())
    legacy_nodes, legacy_edges = project_legacy(manifest)
    v2_nodes, v2_edges, id_map, report = migrate(legacy_nodes, legacy_edges)

    # Identity for downstream readers (query pack reads migration-report.json).
    report["projection_id"] = PROJECTION_ID
    report["generated_at"] = _utc_now_iso()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "nodes.jsonl", v2_nodes)
    _write_jsonl(output_dir / "edges.jsonl", v2_edges)
    (output_dir / "id-map.json").write_text(
        json.dumps(id_map, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "migration-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="v2-native projector: import-manifest.yaml -> Person/Organization graph."
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH),
                        help="Path to the import manifest (default: registry/import-manifest.yaml).")
    parser.add_argument("--output-dir", default="data/projected/phase0-bcore/candidate-v2",
                        help="Output directory (default: data/projected/phase0-bcore/candidate-v2).")
    args = parser.parse_args()

    report = run(args.manifest, args.output_dir)

    print(f"Wrote v2-native projection to: {args.output_dir}")
    print(f"  Nodes: {report['source_node_count']} legacy "
          f"-> {report['migrated_node_count']} migrated "
          f"({report['dropped_node_count']} CaseParticipation dropped, "
          f"{report['conversion_count']} converted to PARTY_TO edges)")
    print(f"  Edges: {report['source_edge_count']} legacy "
          f"-> {report['migrated_edge_count']} migrated "
          f"({report['dropped_edge_count']} casepart edges dropped)")
    print(f"  id-map (remap_count): {report['remap_count']}")


if __name__ == "__main__":
    main()
