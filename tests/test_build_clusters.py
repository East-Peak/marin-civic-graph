import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_clusters import compute_clusters, MIN_CLUSTER_SIZE


def _gaussian_blob(center, n, scale=0.3, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(loc=center, scale=scale, size=(n, 2))


class TestComputeClusters:
    def test_two_dense_blobs_separated(self):
        a = _gaussian_blob((0, 0), 30, seed=1)
        b = _gaussian_blob((10, 10), 30, seed=2)
        coords = np.vstack([a, b])
        labels, centroids, distances = compute_clusters(coords)
        # Should pick out at least 2 clusters; -1 = noise allowed.
        unique = set(labels) - {-1}
        assert len(unique) >= 2
        # Each blob's points predominantly in one cluster.
        a_labels = labels[:30]
        b_labels = labels[30:]
        a_top = max(set(a_labels) - {-1}, key=lambda x: (a_labels == x).sum(), default=-1)
        b_top = max(set(b_labels) - {-1}, key=lambda x: (b_labels == x).sum(), default=-1)
        assert a_top != b_top
        assert (a_labels == a_top).sum() > 20
        assert (b_labels == b_top).sum() > 20

    def test_distances_sized_to_input(self):
        coords = _gaussian_blob((0, 0), MIN_CLUSTER_SIZE * 2, seed=3)
        labels, centroids, distances = compute_clusters(coords)
        assert distances.shape == (coords.shape[0],)
        assert np.all(distances >= 0)

    def test_centroid_per_cluster_id(self):
        a = _gaussian_blob((0, 0), 30, seed=4)
        b = _gaussian_blob((50, 50), 30, seed=5)
        coords = np.vstack([a, b])
        labels, centroids, _ = compute_clusters(coords)
        for cid in set(labels) - {-1}:
            assert cid in centroids
            assert centroids[cid].shape == (2,)
