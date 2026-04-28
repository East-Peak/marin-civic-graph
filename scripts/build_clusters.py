"""HDBSCAN on 2D *_pending UMAP coords.

Reads umap_x_pending/umap_y_pending; writes cluster_id_pending (raw, not
yet matched across runs — match_clusters.py handles that) and
cluster_centroid_distance_pending.

CLI:
  python scripts/build_clusters.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

MIN_CLUSTER_SIZE = 15
MIN_SAMPLES = 5


def compute_clusters(coords: np.ndarray) -> tuple[np.ndarray, dict, np.ndarray]:
    """Run HDBSCAN on 2D coords. Returns (labels, centroids_by_id, distances).

    labels: shape (N,) int; -1 = noise.
    centroids_by_id: dict[int, np.ndarray of shape (2,)].
    distances: shape (N,) — Euclidean distance from each point to its
               cluster's centroid; noise points have distance to overall
               centroid as a fallback.
    """
    import hdbscan

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE,
        min_samples=MIN_SAMPLES,
        metric="euclidean",
    )
    labels = clusterer.fit_predict(coords)

    centroids: dict[int, np.ndarray] = {}
    for cid in set(labels):
        if cid == -1:
            continue
        centroids[int(cid)] = coords[labels == cid].mean(axis=0)

    overall_centroid = coords.mean(axis=0) if len(coords) else np.zeros(2)
    distances = np.zeros(coords.shape[0])
    for i, cid in enumerate(labels):
        c = centroids.get(int(cid), overall_centroid)
        distances[i] = float(np.linalg.norm(coords[i] - c))
    return labels.astype(int), centroids, distances


def main() -> int:
    from neo4j import GraphDatabase

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session(database=database) as session:
        rows = list(session.run(
            "MATCH (n) WHERE n.umap_x_pending IS NOT NULL "
            "RETURN n.id AS id, n.umap_x_pending AS x, n.umap_y_pending AS y"
        ))

    if not rows:
        print("no nodes with umap_*_pending; nothing to cluster")
        driver.close()
        return 0

    ids = [r["id"] for r in rows]
    coords = np.array([[float(r["x"]), float(r["y"])] for r in rows])

    labels, centroids, distances = compute_clusters(coords)
    noise_count = int((labels == -1).sum())
    unique_clusters = set(labels) - {-1}
    print(f"clusters: {len(unique_clusters)} non-noise; noise: {noise_count}")

    if args.dry_run:
        driver.close()
        return 0

    with driver.session(database=database) as session:
        write_rows = [
            {"id": ids[i], "cluster_id": int(labels[i]), "distance": float(distances[i])}
            for i in range(len(ids))
        ]
        WRITE_BATCH = 1000
        for i in range(0, len(write_rows), WRITE_BATCH):
            session.run(
                "UNWIND $rows AS row "
                "MATCH (n {id: row.id}) "
                "SET n.cluster_id_pending = row.cluster_id, "
                "    n.cluster_centroid_distance_pending = row.distance",
                rows=write_rows[i:i + WRITE_BATCH],
            )

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
