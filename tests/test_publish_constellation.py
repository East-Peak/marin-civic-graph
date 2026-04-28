import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from publish_constellation import (
    SCHEMA_VERSION,
    PAYLOAD_SIZE_GZ_BUDGET,
    DRIFT_BUDGET_NODE_PCT,
    DRIFT_BUDGET_CENTROID_PCT,
    build_payload,
    enforce_drift_budget,
    DriftBudgetExceeded,
)


def _node(i, x=0.0, y=0.0):
    return {
        "id": f"person-{i}", "type": "Person", "label": f"P{i}",
        "umap_x_pending": x, "umap_y_pending": y,
        "cluster_id_pending": 1, "embedding_hash": "h",
    }


class TestBuildPayload:
    def test_includes_schema_and_versions(self):
        payload = build_payload(
            nodes=[_node(0), _node(1, 1, 1)],
            edges=[],
            clusters=[{"id": 1, "label": "Test", "centroid": [0.5, 0.5], "member_count": 2}],
            version="2026-04-27-rehearsal-001",
            umap_version=14,
        )
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["version"] == "2026-04-27-rehearsal-001"
        assert payload["umap_version"] == 14
        assert payload["node_count"] == 2
        assert len(payload["nodes"]) == 2
        # Coords come from *_pending fields.
        assert payload["nodes"][0]["x"] == 0.0
        assert payload["nodes"][1]["x"] == 1.0


class TestDriftBudget:
    def test_within_budget_passes(self):
        prior = np.array([[0.0, 0.0], [10.0, 0.0]])
        new = np.array([[0.1, 0.1], [10.1, 0.0]])  # tiny drift
        # Should not raise.
        enforce_drift_budget(prior_pts=prior, new_pts=new,
                             prior_centroids={1: prior.mean(axis=0)},
                             new_centroids={1: new.mean(axis=0)})

    def test_node_breach_raises(self):
        prior = np.array([[0.0, 0.0], [10.0, 0.0]])
        new = np.array([[0.0, 0.0], [13.0, 0.0]])  # node moved 30% of map width
        try:
            enforce_drift_budget(prior_pts=prior, new_pts=new,
                                 prior_centroids={}, new_centroids={})
        except DriftBudgetExceeded as e:
            assert "node" in str(e).lower()
            return
        raise AssertionError("DriftBudgetExceeded not raised")

    def test_centroid_breach_raises(self):
        prior = np.array([[0.0, 0.0], [10.0, 0.0]])
        new = np.array([[0.0, 0.0], [10.0, 0.0]])  # nodes still
        # Cluster centroid moved 20% of map width — breach (budget 15%).
        try:
            enforce_drift_budget(
                prior_pts=prior, new_pts=new,
                prior_centroids={1: np.array([5.0, 0.0])},
                new_centroids={1: np.array([7.0, 0.0])},
            )
        except DriftBudgetExceeded as e:
            assert "centroid" in str(e).lower()
            return
        raise AssertionError("DriftBudgetExceeded not raised")


class TestBudgetConstants:
    def test_drift_budgets_match_spec(self):
        # Spec §4.3: 25% per-node, 15% per-cluster-centroid.
        assert DRIFT_BUDGET_NODE_PCT == 0.25
        assert DRIFT_BUDGET_CENTROID_PCT == 0.15

    def test_payload_size_budget_matches_spec(self):
        # Spec §11 v2.0 pass criterion: ≤8MB gzipped.
        assert PAYLOAD_SIZE_GZ_BUDGET == 8 * 1024 * 1024
