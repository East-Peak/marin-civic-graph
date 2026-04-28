import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_umap import (
    fit_similarity_transform,
    apply_similarity_transform,
    drift_metrics,
)


class TestSimilarityTransform:
    def test_identity_when_inputs_equal(self):
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        T = fit_similarity_transform(pts, pts)
        out = apply_similarity_transform(pts, T)
        np.testing.assert_allclose(out, pts, atol=1e-10)

    def test_undoes_uniform_rotation(self):
        prior = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]])
        # Rotate 90° (a fresh UMAP fit could land here).
        rot = np.array([[0.0, -1.0], [1.0, 0.0]])
        new = prior @ rot.T
        T = fit_similarity_transform(new, prior)
        aligned = apply_similarity_transform(new, T)
        np.testing.assert_allclose(aligned, prior, atol=1e-10)

    def test_undoes_uniform_scale(self):
        prior = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]])
        new = prior * 2.5
        T = fit_similarity_transform(new, prior)
        aligned = apply_similarity_transform(new, T)
        np.testing.assert_allclose(aligned, prior, atol=1e-10)

    def test_undoes_translation(self):
        prior = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        new = prior + np.array([10.0, -5.0])
        T = fit_similarity_transform(new, prior)
        aligned = apply_similarity_transform(new, T)
        np.testing.assert_allclose(aligned, prior, atol=1e-10)

    def test_undoes_mirror(self):
        prior = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]])
        # Mirror across x-axis.
        new = prior * np.array([1.0, -1.0])
        T = fit_similarity_transform(new, prior)
        aligned = apply_similarity_transform(new, T)
        np.testing.assert_allclose(aligned, prior, atol=1e-9)


class TestDriftMetrics:
    def test_zero_drift_when_aligned(self):
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        m = drift_metrics(pts, pts)
        assert m["max_node_displacement_pct"] == pytest.approx(0.0, abs=1e-9)
        assert m["max_centroid_displacement_pct"] == pytest.approx(0.0, abs=1e-9)

    def test_drift_pct_relative_to_map_width(self):
        prior = np.array([[0.0, 0.0], [10.0, 0.0]])
        new = np.array([[0.0, 0.0], [10.0, 1.0]])  # one node moved 1.0 across a 10-wide map
        m = drift_metrics(prior, new)
        assert m["max_node_displacement_pct"] == pytest.approx(0.1, rel=1e-6)
