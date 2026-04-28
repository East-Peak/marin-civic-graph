"""UMAP fit/transform with persistent similarity-transform alignment.

Spec §9.3 + §4.3. Output coords land in n.umap_x_pending / .umap_y_pending /
.umap_version_pending — never canonical (only publish_constellation.py
promotes pending → canonical).

CLI:
  python scripts/build_umap.py [--full-fit] [--dry-run]

  --full-fit : run UMAP.fit_transform on all eligible embeddings (weekly).
               Otherwise loads cached umap.pkl and runs .transform on
               new/dirty nodes only (nightly).
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
MODEL_PATH = REPO / "data" / "umap_model.pkl"
ALIGNMENT_PATH = REPO / "data" / "umap_alignment.json"
UMAP_VERSION = 1


def fit_similarity_transform(new_pts: np.ndarray, prior_pts: np.ndarray) -> dict:
    """Solve for θ, mirror, scale, translation that best maps new_pts → prior_pts.

    Returns a dict with keys: rotation_rad, mirror, scale, tx, ty.

    Uses the closed-form least-squares solution (Umeyama, 1991) plus a
    reflection check: we evaluate squared error with mirror=False and
    mirror=True and pick the lower one.
    """
    assert new_pts.shape == prior_pts.shape
    n = new_pts.shape[0]
    if n == 0:
        return {"rotation_rad": 0.0, "mirror": False, "scale": 1.0, "tx": 0.0, "ty": 0.0}

    def solve(_new, _prior, mirror: bool) -> tuple[dict, float]:
        new_m = _new.mean(axis=0)
        prior_m = _prior.mean(axis=0)
        new_c = _new - new_m
        prior_c = _prior - prior_m
        if mirror:
            new_c = new_c * np.array([1.0, -1.0])
        # Cross-covariance.
        H = new_c.T @ prior_c
        U, _S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1, :] *= -1
            R = Vt.T @ U.T
        var_new = (new_c ** 2).sum()
        scale = (np.diag(_S).sum() / var_new) if var_new > 0 else 1.0
        T_translate = prior_m - scale * (R @ (new_m * (np.array([1.0, -1.0]) if mirror else 1.0)))
        # Apply transform and measure error.
        applied = scale * ((_new * (np.array([1.0, -1.0]) if mirror else 1.0)) @ R.T) + T_translate
        err = float(((applied - _prior) ** 2).sum())
        theta = float(np.arctan2(R[1, 0], R[0, 0]))
        return ({"rotation_rad": theta, "mirror": mirror, "scale": float(scale),
                 "tx": float(T_translate[0]), "ty": float(T_translate[1])}, err)

    no_mirror, err_n = solve(new_pts, prior_pts, mirror=False)
    yes_mirror, err_y = solve(new_pts, prior_pts, mirror=True)
    return no_mirror if err_n <= err_y else yes_mirror


def apply_similarity_transform(pts: np.ndarray, T: dict) -> np.ndarray:
    """Apply a transform produced by fit_similarity_transform()."""
    theta = T["rotation_rad"]
    s = T["scale"]
    R = np.array([[np.cos(theta), -np.sin(theta)],
                  [np.sin(theta),  np.cos(theta)]])
    p = pts.copy()
    if T["mirror"]:
        p = p * np.array([1.0, -1.0])
    return s * (p @ R.T) + np.array([T["tx"], T["ty"]])


def drift_metrics(prior_pts: np.ndarray, new_pts: np.ndarray) -> dict:
    """Compute per-node and per-centroid drift, normalized by map width.

    Used to enforce the §9.3 drift budget at publish time.
    """
    width = max(
        prior_pts[:, 0].max() - prior_pts[:, 0].min(),
        prior_pts[:, 1].max() - prior_pts[:, 1].min(),
        1e-12,
    )
    diffs = np.linalg.norm(new_pts - prior_pts, axis=1)
    max_node = float(diffs.max()) if len(diffs) else 0.0
    centroid_shift = float(np.linalg.norm(new_pts.mean(axis=0) - prior_pts.mean(axis=0))) if len(prior_pts) else 0.0
    return {
        "max_node_displacement_pct": max_node / width,
        "max_centroid_displacement_pct": centroid_shift / width,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-fit", action="store_true",
                        help="Run UMAP.fit_transform (weekly); otherwise .transform incremental")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # Body filled in during Task 16 rehearsal. The alignment helpers above
    # are the load-bearing surface and have unit-tested correctness.
    print("build_umap.main() is a stub at this commit (Task 16 fills it in)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
