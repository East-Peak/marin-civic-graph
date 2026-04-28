"""Publish the Constellation payload — versioned blob + atomic Cypher.

Spec §9.5 + §9.7. The 4-step atomic Cypher (snapshot → demote → promote
→ manifest) lives in PROMOTE_CYPHER below; main() runs payload build →
drift gate → blob upload → Cypher transaction.

CLI:
  python scripts/publish_constellation.py [--dry-run] [--bypass-drift]
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1
PAYLOAD_SIZE_GZ_BUDGET = 8 * 1024 * 1024  # 8 MB

DRIFT_BUDGET_NODE_PCT = 0.25
DRIFT_BUDGET_CENTROID_PCT = 0.15


class DriftBudgetExceeded(Exception):
    pass


def build_payload(
    *, nodes: list[dict], edges: list[dict], clusters: list[dict],
    version: str, umap_version: int,
) -> dict:
    """Render the Constellation payload from *_pending fields."""
    out_nodes = []
    for n in nodes:
        out_nodes.append({
            "id": n["id"],
            "type": n["type"],
            "label": n.get("label", n["id"]),
            "key_fact": n.get("key_fact"),
            "x": n["umap_x_pending"],
            "y": n["umap_y_pending"],
            "cluster_id": n["cluster_id_pending"],
            "embedding_hash": n.get("embedding_hash"),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "umap_version": umap_version,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(out_nodes),
        "edge_count": len(edges),
        "cluster_count": len(clusters),
        "nodes": out_nodes,
        "edges": edges,
        "clusters": clusters,
    }


def enforce_drift_budget(
    *, prior_pts: np.ndarray, new_pts: np.ndarray,
    prior_centroids: dict[int, np.ndarray],
    new_centroids: dict[int, np.ndarray],
) -> None:
    """Raise DriftBudgetExceeded if §4.3 thresholds breached."""
    if len(prior_pts) and len(new_pts):
        width = max(
            prior_pts[:, 0].max() - prior_pts[:, 0].min(),
            prior_pts[:, 1].max() - prior_pts[:, 1].min(),
            1e-12,
        )
        node_diff_pct = float(np.linalg.norm(new_pts - prior_pts, axis=1).max() / width)
        if node_diff_pct > DRIFT_BUDGET_NODE_PCT:
            raise DriftBudgetExceeded(
                f"node displacement {node_diff_pct:.1%} > budget {DRIFT_BUDGET_NODE_PCT:.0%}"
            )
        for cid, prior_c in prior_centroids.items():
            new_c = new_centroids.get(cid)
            if new_c is None:
                continue
            shift_pct = float(np.linalg.norm(new_c - prior_c) / width)
            if shift_pct > DRIFT_BUDGET_CENTROID_PCT:
                raise DriftBudgetExceeded(
                    f"cluster {cid} centroid displacement {shift_pct:.1%} > "
                    f"budget {DRIFT_BUDGET_CENTROID_PCT:.0%}"
                )


PROMOTE_CYPHER = """
// Spec §9.5 — atomic 4-step promotion. Run inside ONE transaction.

// 1a. Clear prior rollback metadata so each run's metadata is self-contained.
MATCH (n) WHERE n.had_canonical_before IS NOT NULL OR n.umap_x_previous IS NOT NULL
REMOVE n.had_canonical_before,
       n.umap_x_previous, n.umap_y_previous, n.umap_version_previous,
       n.cluster_id_previous, n.cluster_label_previous,
       n.cluster_centroid_distance_previous;

// 1b. Snapshot canonical for nodes that have it.
MATCH (n) WHERE n.umap_x IS NOT NULL
SET n.umap_x_previous = n.umap_x,
    n.umap_y_previous = n.umap_y,
    n.umap_version_previous = n.umap_version,
    n.cluster_id_previous = n.cluster_id,
    n.cluster_label_previous = n.cluster_label,
    n.cluster_centroid_distance_previous = n.cluster_centroid_distance,
    n.had_canonical_before = true;

// 1c. Mark first-time entrants.
MATCH (n) WHERE n.umap_x IS NULL AND n.umap_x_pending IS NOT NULL
SET n.had_canonical_before = false;

// 1d. Snapshot manifest metadata.
MATCH (s:_SyncState {kind: 'constellation'})
SET s.previous_version_id = s.version_id,
    s.previous_umap_version = s.umap_version,
    s.previous_blob_url = s.blob_url;

// 2. Demote BEFORE promote consumes pending.
MATCH (n) WHERE n.umap_x IS NOT NULL AND n.umap_x_pending IS NULL
REMOVE n.umap_x, n.umap_y, n.umap_version,
       n.cluster_id, n.cluster_label, n.cluster_centroid_distance;

// 3. Promote pending → canonical.
MATCH (n) WHERE n.umap_x_pending IS NOT NULL
SET n.umap_x = n.umap_x_pending,
    n.umap_y = n.umap_y_pending,
    n.umap_version = n.umap_version_pending,
    n.cluster_id = n.cluster_id_pending,
    n.cluster_label = n.cluster_label_pending,
    n.cluster_centroid_distance = n.cluster_centroid_distance_pending
REMOVE n.umap_x_pending, n.umap_y_pending, n.umap_version_pending,
       n.cluster_id_pending, n.cluster_label_pending,
       n.cluster_centroid_distance_pending;

// 4. Update manifest pointer.
MERGE (s:_SyncState {kind: 'constellation'})
SET s.version_id = $new_version_id,
    s.umap_version = $new_umap_version,
    s.blob_url = $new_blob_url,
    s.updated_at = datetime();
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--bypass-drift", action="store_true",
                        help="DEV ONLY — skip the §4.3 drift budget check")
    args = parser.parse_args()
    print("publish_constellation.main() is a stub at this commit (Task 16 fills it in)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
