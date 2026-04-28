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
    import json
    import time

    from neo4j import GraphDatabase

    sys.path.insert(0, str(REPO / "scripts"))
    from canonical_type import canonical_type
    from outbound_policy import is_eligible

    parser = argparse.ArgumentParser()
    parser.add_argument("--full-fit", action="store_true",
                        help="Run UMAP.fit_transform (weekly); otherwise .transform incremental")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session(database=database) as session:
        # Step 0: copy canonical → pending for eligible nodes only (spec §9.3).
        eligible_rows = session.run(
            "MATCH (n) WHERE n.umap_x IS NOT NULL RETURN n.id AS id, labels(n) AS labels"
        )
        eligible_ids = [
            r["id"] for r in eligible_rows
            if (t := canonical_type(r["labels"], r["id"])) and is_eligible(t)
        ]
        session.run(
            "MATCH (n) WHERE n.id IN $ids AND n.umap_x IS NOT NULL "
            "SET n.umap_x_pending = n.umap_x, n.umap_y_pending = n.umap_y, "
            "    n.umap_version_pending = n.umap_version",
            ids=eligible_ids,
        )

        # Load embeddings for eligible nodes.
        emb_rows = list(session.run(
            "MATCH (n) WHERE n.embedding IS NOT NULL "
            "RETURN n.id AS id, n.embedding AS emb, labels(n) AS labels"
        ))
        work_ids: list[str] = []
        work_embs_list: list[list[float]] = []
        for row in emb_rows:
            node_id = row["id"]
            t = canonical_type(row["labels"], node_id)
            if t is None or not is_eligible(t):
                continue
            work_ids.append(node_id)
            work_embs_list.append(row["emb"])

        if not work_ids:
            print("no eligible embeddings found; nothing to do")
            driver.close()
            return 0

        embs = np.array(work_embs_list, dtype=np.float32)
        print(f"loaded {len(work_ids)} eligible embeddings")

        if args.full_fit:
            import umap as umap_lib

            model = umap_lib.UMAP(
                n_components=2,
                n_neighbors=30,
                min_dist=0.1,
                metric="cosine",
                random_state=42,
                init="spectral",
            )
            t0 = time.time()
            new_pts = model.fit_transform(embs)
            print(f"UMAP fit_transform: {time.time() - t0:.1f}s")

            # Alignment to prior frame if anchors exist.
            prior_rows = list(session.run(
                "MATCH (n) WHERE n.umap_x_previous IS NOT NULL "
                "RETURN n.id AS id, n.umap_x_previous AS x, n.umap_y_previous AS y"
            ))
            if prior_rows:
                prior_pts_dict = {r["id"]: (float(r["x"]), float(r["y"])) for r in prior_rows}
                anchors = [(i, work_ids[i]) for i in range(len(work_ids))
                           if work_ids[i] in prior_pts_dict]
                if len(anchors) >= 100:
                    anchor_new_pts = np.array([new_pts[i] for i, _ in anchors])
                    anchor_prior_pts = np.array([prior_pts_dict[nid] for _, nid in anchors])
                    T = fit_similarity_transform(anchor_new_pts, anchor_prior_pts)
                    new_pts = apply_similarity_transform(new_pts, T)
                    ALIGNMENT_PATH.parent.mkdir(parents=True, exist_ok=True)
                    ALIGNMENT_PATH.write_text(json.dumps(T))
                    print(f"alignment fitted on {len(anchors)} anchors; saved to {ALIGNMENT_PATH}")

            MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with MODEL_PATH.open("wb") as f:
                pickle.dump(model, f)
            print(f"UMAP model saved to {MODEL_PATH}")
        else:
            with MODEL_PATH.open("rb") as f:
                model = pickle.load(f)
            new_pts = model.transform(embs)
            if ALIGNMENT_PATH.exists():
                T = json.loads(ALIGNMENT_PATH.read_text())
                new_pts = apply_similarity_transform(new_pts, T)

        if args.dry_run:
            print(f"dry-run: would write {len(work_ids)} umap_*_pending coords")
            driver.close()
            return 0

        # Write umap_*_pending in batches.
        WRITE_BATCH = 1000
        for i in range(0, len(work_ids), WRITE_BATCH):
            batch_ids = work_ids[i:i + WRITE_BATCH]
            batch_pts = new_pts[i:i + WRITE_BATCH]
            rows = [
                {"id": nid, "x": float(batch_pts[j, 0]), "y": float(batch_pts[j, 1])}
                for j, nid in enumerate(batch_ids)
            ]
            session.run(
                "UNWIND $rows AS row "
                "MATCH (n {id: row.id}) "
                "SET n.umap_x_pending = row.x, n.umap_y_pending = row.y, "
                "    n.umap_version_pending = $v",
                rows=rows,
                v=UMAP_VERSION,
            )
        print(f"wrote umap_*_pending for {len(work_ids)} nodes")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
