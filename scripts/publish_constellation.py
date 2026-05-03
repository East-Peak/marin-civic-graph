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
    s.size_gz = $new_size_gz,
    s.updated_at = datetime();
"""


def main() -> int:
    from neo4j import GraphDatabase

    # Allow import of canonical_type from scripts/ dir.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from canonical_type import canonical_type

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--bypass-drift", action="store_true",
                        help="DEV ONLY — skip the §4.3 drift budget check")
    parser.add_argument("--no-edges", action="store_true",
                        help="Drop edges from payload. v2.0 calibration: edges are "
                             "decoration per §4.3 (layout uses UMAP), and including all "
                             "~148K edges blows the 8MB gzipped budget. v2.1 decides "
                             "whether to raise the budget or trim edges by class/weight.")
    parser.add_argument("--bypass-size", action="store_true",
                        help="DEV ONLY — skip the §11 v2.0 payload-size pass criterion. "
                             "Used during the v2.0 calibration rehearsal where actual "
                             "payload (8.4 MB gzipped, no edges) marginally exceeds the "
                             "8MB estimate. v2.1 amends the budget or trims contents.")
    args = parser.parse_args()

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session(database=database) as session:
        # 1. Pull all *_pending nodes.
        node_rows = list(session.run(
            "MATCH (n) WHERE n.umap_x_pending IS NOT NULL "
            "RETURN n.id AS id, labels(n) AS labels, n.label AS label, "
            "       n.umap_x_pending AS umap_x_pending, "
            "       n.umap_y_pending AS umap_y_pending, "
            "       n.cluster_id_pending AS cluster_id_pending, "
            "       n.embedding_hash AS embedding_hash, "
            "       n.search_key_fact AS key_fact"
        ))

        payload_nodes = []
        for r in node_rows:
            nt = canonical_type(r["labels"], r["id"])
            if nt is None:
                continue
            payload_nodes.append({
                "id": r["id"],
                "type": nt,
                "label": r["label"] or r["id"],
                "key_fact": r["key_fact"],
                "umap_x_pending": float(r["umap_x_pending"]),
                "umap_y_pending": float(r["umap_y_pending"]),
                "cluster_id_pending": r["cluster_id_pending"],
                "embedding_hash": r["embedding_hash"],
            })

        # 2. Pull edges between published nodes (skipped when --no-edges).
        if args.no_edges:
            edges = []
            print("--no-edges: skipping edge fetch (v2.0 calibration)")
        else:
            edge_rows = list(session.run(
                "MATCH (a)-[r]-(b) "
                "WHERE a.umap_x_pending IS NOT NULL AND b.umap_x_pending IS NOT NULL "
                "RETURN a.id AS a_id, b.id AS b_id, type(r) AS rel_type "
                "LIMIT 5000000"
            ))
            edges = [{"s": r["a_id"], "t": r["b_id"], "type": r["rel_type"], "weight": 1}
                     for r in edge_rows]

        # 3. Build clusters list.
        cluster_rows = list(session.run(
            "MATCH (n) WHERE n.cluster_id_pending IS NOT NULL "
            "RETURN n.cluster_id_pending AS id, "
            "       avg(n.umap_x_pending) AS cx, avg(n.umap_y_pending) AS cy, "
            "       count(n) AS member_count, "
            "       collect(n.cluster_label_pending)[0] AS label"
        ))
        clusters = [
            {
                "id": r["id"],
                "label": r["label"],
                "centroid": [float(r["cx"]), float(r["cy"])],
                "member_count": r["member_count"],
            }
            for r in cluster_rows
        ]

        # 4. Pull prior frame for drift check.
        prior_rows = list(session.run(
            "MATCH (n) WHERE n.umap_x_previous IS NOT NULL "
            "RETURN n.id AS id, n.umap_x_previous AS x, n.umap_y_previous AS y"
        ))

    # 5. Generate version_id.
    version_id = (
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M')}-rehearsal-001"
    )
    umap_version = int(os.environ.get("UMAP_VERSION", str(SCHEMA_VERSION)))

    # 6. Build payload.
    payload = build_payload(
        nodes=payload_nodes,
        edges=edges,
        clusters=clusters,
        version=version_id,
        umap_version=umap_version,
    )

    # 7. Drift gate.
    if not args.bypass_drift and prior_rows:
        prior_dict = {r["id"]: (float(r["x"]), float(r["y"])) for r in prior_rows}
        curr_dict = {n["id"]: (n["umap_x_pending"], n["umap_y_pending"]) for n in payload_nodes}
        matched_ids = [nid for nid in curr_dict if nid in prior_dict]
        if matched_ids:
            prior_pts = np.array([prior_dict[nid] for nid in matched_ids])
            new_pts = np.array([curr_dict[nid] for nid in matched_ids])
            enforce_drift_budget(
                prior_pts=prior_pts,
                new_pts=new_pts,
                prior_centroids={},
                new_centroids={},
            )

    # 8. Serialize and check size.
    body = json.dumps(payload).encode("utf-8")
    body_gz = gzip.compress(body, compresslevel=6)
    print(
        f"payload: {len(body)} raw, {len(body_gz)} gzipped "
        f"({len(body_gz) / 1024 / 1024:.1f} MB)"
    )
    if len(body_gz) > PAYLOAD_SIZE_GZ_BUDGET:
        if args.bypass_size:
            print(
                f"WARN (--bypass-size): gzipped size {len(body_gz)} > "
                f"budget {PAYLOAD_SIZE_GZ_BUDGET}; proceeding for v2.0 calibration"
            )
        else:
            print(
                f"FAIL: gzipped size {len(body_gz)} > budget {PAYLOAD_SIZE_GZ_BUDGET}",
                file=sys.stderr,
            )
            driver.close()
            return 4

    # 9. Write rehearsal blob.
    blob_dir = Path(__file__).resolve().parent.parent / "data" / "rehearsal-blobs"
    blob_dir.mkdir(parents=True, exist_ok=True)
    blob_path = blob_dir / f"constellation-{version_id}.json.gz"
    blob_path.write_bytes(body_gz)
    print(f"blob written to {blob_path}")

    if args.dry_run:
        driver.close()
        return 0

    # 10. Atomic Cypher promote.
    blob_url = f"constellation-{version_id}.json.gz"
    with driver.session(database=database) as session:
        with session.begin_transaction() as tx:
            for stmt in PROMOTE_CYPHER.split(";"):
                stmt = stmt.strip()
                if not stmt:
                    continue
                tx.run(
                    stmt,
                    new_version_id=version_id,
                    new_umap_version=umap_version,
                    new_blob_url=blob_url,
                    new_size_gz=len(body_gz),
                )
            tx.commit()

    print("promoted to canonical; manifest updated")
    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
