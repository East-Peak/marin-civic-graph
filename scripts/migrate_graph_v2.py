"""migrate_graph_v2.py — orchestrator for the Marin Civic Graph schema migration.

Reads graph-v1 JSONL files (nodes.jsonl, edges.jsonl), applies the migration
mapping from migration_mapping.py, and writes settled-schema JSONL output plus
an ID map and migration report.

Output files:
  nodes.jsonl          — migrated nodes, one JSON object per line
  edges.jsonl          — migrated edges, one JSON object per line
  id-map.json          — old_id → new_id for every remapped ID
  migration-report.json — stats: source/migrated counts, by-type breakdowns,
                          dropped counts, conversion counts

Usage (CLI):
  python scripts/migrate_graph_v2.py
  python scripts/migrate_graph_v2.py --input-dir data/projected/graph-v1 \
                                      --output-dir data/projected/graph-v2
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# scripts/ is not a package; insert its directory so migration_mapping is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migration_mapping import (
    _remap_props,  # second-pass prop remapping
    case_participation_to_edges,
    migrate_edge,
    migrate_id,
    migrate_node,
)


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------

def run_migration(nodes_path: Path, edges_path: Path, output_dir: Path) -> dict:
    """Run the full graph-v1 → settled-schema migration.

    Parameters
    ----------
    nodes_path : Path
        Path to the graph-v1 nodes.jsonl input file.
    edges_path : Path
        Path to the graph-v1 edges.jsonl input file.
    output_dir : Path
        Directory where output files are written.  Must already exist.

    Returns
    -------
    dict
        Migration report dict (same content as migration-report.json).
    """
    output_dir = Path(output_dir)

    # ------------------------------------------------------------------
    # Pass 1: Build ID map — read all nodes, compute new IDs for each.
    # Only entries where old_id != new_id are stored.
    # ------------------------------------------------------------------
    id_map: dict[str, str] = {}
    raw_nodes: list[dict] = []

    with nodes_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            node = json.loads(line)
            raw_nodes.append(node)
            old_id = node["id"]
            new_id = migrate_id(old_id, node["node_type"], node.get("properties", {}))
            if new_id != old_id:
                id_map[old_id] = new_id

    # ------------------------------------------------------------------
    # Pass 2: Migrate nodes.
    # CaseParticipation nodes return None from migrate_node; collect them
    # separately for later conversion to PARTY_TO edges.
    # All other nodes get a second-pass remap of actor- refs in properties.
    # ------------------------------------------------------------------
    migrated_nodes: list[dict] = []
    cp_nodes: list[dict] = []          # raw CaseParticipation nodes
    nodes_by_type: dict[str, int] = defaultdict(int)

    for node in raw_nodes:
        result = migrate_node(node)

        if result is None:
            # CaseParticipation — keep raw node for conversion pass
            cp_nodes.append(node)
            continue

        # Second pass: remap any remaining actor- (and other) property refs
        # using the full id_map that now covers all Actor remappings.
        result["properties"] = _remap_props(result["properties"], id_map=id_map)

        migrated_nodes.append(result)
        nodes_by_type[result["node_type"]] += 1

    # ------------------------------------------------------------------
    # Pass 3: Collect CaseParticipation evidence.
    # Scan edges for EVIDENCED_BY edges whose source starts with "casepart-".
    # Build cp_id → [evidence_record_id, ...].
    # ------------------------------------------------------------------
    raw_edges: list[dict] = []
    cp_evidence: dict[str, list[str]] = defaultdict(list)

    with edges_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            edge = json.loads(line)
            raw_edges.append(edge)
            if (
                edge.get("relationship_type") == "EVIDENCED_BY"
                and edge["source_id"].startswith("casepart-")
            ):
                cp_evidence[edge["source_id"]].append(edge["target_id"])

    # ------------------------------------------------------------------
    # Pass 4: Migrate edges.
    # Edges touching casepart- nodes are dropped (migrate_edge returns None).
    # ------------------------------------------------------------------
    migrated_edges: list[dict] = []
    dropped_edge_count = 0
    edges_by_type: dict[str, int] = defaultdict(int)

    for edge in raw_edges:
        result = migrate_edge(edge, id_map)
        if result is None:
            dropped_edge_count += 1
            continue
        migrated_edges.append(result)
        edges_by_type[result["relationship_type"]] += 1

    # ------------------------------------------------------------------
    # Pass 5: Convert CaseParticipation → PARTY_TO edges.
    # ------------------------------------------------------------------
    party_to_edges = case_participation_to_edges(cp_nodes, dict(cp_evidence), id_map)
    for edge in party_to_edges:
        migrated_edges.append(edge)
        edges_by_type[edge["relationship_type"]] += 1

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    _write_jsonl(output_dir / "nodes.jsonl", migrated_nodes)
    _write_jsonl(output_dir / "edges.jsonl", migrated_edges)

    (output_dir / "id-map.json").write_text(
        json.dumps(id_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    report = {
        "source_node_count": len(raw_nodes),
        "migrated_node_count": len(migrated_nodes),
        "dropped_node_count": len(cp_nodes),
        "source_edge_count": len(raw_edges),
        "migrated_edge_count": len(migrated_edges),
        "dropped_edge_count": dropped_edge_count,
        "conversion_count": len(party_to_edges),
        "nodes_by_type": dict(nodes_by_type),
        "edges_by_type": dict(edges_by_type),
    }

    (output_dir / "migration-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write a list of dicts to a JSONL file (one JSON object per line)."""
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate Marin Civic Graph from v1 (28-type) to settled ontology."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/projected/graph-v1"),
        help="Directory containing nodes.jsonl and edges.jsonl (default: data/projected/graph-v1)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/projected/graph-v2"),
        help="Directory for output files; created if absent (default: data/projected/graph-v2)",
    )
    args = parser.parse_args()

    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir

    nodes_path = input_dir / "nodes.jsonl"
    edges_path = input_dir / "edges.jsonl"

    if not nodes_path.exists():
        print(f"ERROR: nodes file not found: {nodes_path}", file=sys.stderr)
        sys.exit(1)
    if not edges_path.exists():
        print(f"ERROR: edges file not found: {edges_path}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading nodes from: {nodes_path}")
    print(f"Reading edges from: {edges_path}")
    print(f"Writing output to:  {output_dir}")

    report = run_migration(nodes_path, edges_path, output_dir)

    print()
    print("Migration complete.")
    print(f"  Nodes:  {report['source_node_count']} source "
          f"→ {report['migrated_node_count']} migrated "
          f"({report['dropped_node_count']} CaseParticipation dropped, "
          f"{report['conversion_count']} converted to edges)")
    print(f"  Edges:  {report['source_edge_count']} source "
          f"→ {report['migrated_edge_count']} migrated "
          f"({report['dropped_edge_count']} casepart edges dropped)")
    print()
    print("Nodes by type:")
    for ntype, count in sorted(report["nodes_by_type"].items()):
        print(f"  {ntype:30s} {count:6d}")
    print()
    print("Edges by type (top 20):")
    for rel, count in sorted(report["edges_by_type"].items(), key=lambda x: -x[1])[:20]:
        print(f"  {rel:40s} {count:6d}")
    print()
    print(f"  id-map.json:          {len(json.loads((output_dir / 'id-map.json').read_text()))} remapped IDs")


if __name__ == "__main__":
    main()
