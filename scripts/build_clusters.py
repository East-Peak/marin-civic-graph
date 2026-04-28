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
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print("build_clusters.main() is a stub at this commit (Task 16 fills it in)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
