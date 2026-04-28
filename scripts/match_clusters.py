"""Stable cluster IDs across runs via Hungarian matching on Jaccard overlap.

Input: prior_members (canonical cluster_id → member node ids), new_members
(raw HDBSCAN cluster_id from this run → member node ids).
Output: { assignments: { new_id → stable_id }, renames_needed: { new_ids that need a fresh name } }.

renames_needed includes every new cluster that is "fresh" relative to the
prior frame: brand-new clusters (no good match), splits (sibling
descendants of a prior cluster), and merges (multiple prior ancestors
collapsed into one new). The single matched-1:1 case is the only one
that does NOT need a new name.

CLI:
  python scripts/match_clusters.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

REPO = Path(__file__).resolve().parent.parent

JACCARD_MIN = 0.5


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(len(a | b), 1)


def match_clusters(
    prior_members: dict[int, set[str]],
    new_members: dict[int, set[str]],
) -> dict:
    prior_ids = sorted(prior_members.keys())
    new_ids = sorted(new_members.keys())

    if not new_ids:
        return {"assignments": {}, "renames_needed": set()}

    # Build cost matrix (negated overlap so linear_sum_assignment maximizes overlap).
    rows = max(len(new_ids), len(prior_ids))
    cols = rows
    cost = np.zeros((rows, cols))
    for i, n_id in enumerate(new_ids):
        for j, p_id in enumerate(prior_ids):
            overlap = len(new_members[n_id] & prior_members[p_id])
            cost[i, j] = -overlap

    row_ind, col_ind = linear_sum_assignment(cost)

    assignments: dict[int, int] = {}
    renames_needed: set[int] = set()
    used_prior: set[int] = set()
    next_fresh_id = (max(prior_ids, default=-1) + 1)

    # 1) Hungarian-paired assignments that pass Jaccard threshold.
    for i, j in zip(row_ind, col_ind):
        if i >= len(new_ids) or j >= len(prior_ids):
            continue
        n_id = new_ids[i]
        p_id = prior_ids[j]
        if _jaccard(new_members[n_id], prior_members[p_id]) >= JACCARD_MIN:
            assignments[n_id] = p_id
            used_prior.add(p_id)

    # 2) Detect splits / merges among assigned clusters and the rest.
    # Prior used by best-overlap; remaining new clusters get fresh IDs.
    for n_id in new_ids:
        if n_id in assignments:
            continue
        # Find the prior with which this new cluster overlaps most (any non-zero overlap)
        best_prior = None
        best_overlap = 0
        for p_id in prior_ids:
            ov = len(new_members[n_id] & prior_members[p_id])
            if ov > best_overlap:
                best_overlap = ov
                best_prior = p_id
        if best_prior is not None and best_prior not in used_prior:
            # Inherit the prior id; this is a split where the larger sibling
            # got assigned in step 1, OR a freshly disjoint cluster — we
            # treat best-non-conflicting overlap as inheritance.
            assignments[n_id] = best_prior
            used_prior.add(best_prior)
        else:
            # Truly new cluster (no overlap, or overlap was claimed by sibling).
            assignments[n_id] = next_fresh_id
            next_fresh_id += 1
        renames_needed.add(n_id)

    # 3) Identify merges: a stable_id assigned to one new cluster whose
    #    members include majority of more than one prior cluster.
    for n_id, stable_id in assignments.items():
        ancestors = [p for p in prior_ids
                     if len(new_members[n_id] & prior_members[p]) > 0]
        if len(ancestors) > 1:
            renames_needed.add(n_id)

    return {"assignments": assignments, "renames_needed": renames_needed}


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
        # Pull yesterday's stable mapping from canonical.
        prior_rows = list(session.run(
            "MATCH (n) WHERE n.cluster_id IS NOT NULL "
            "RETURN n.cluster_id AS cid, collect(n.id) AS members"
        ))
        prior_members: dict[int, set[str]] = {
            int(r["cid"]): set(r["members"]) for r in prior_rows
        }

        # Pull today's raw mapping from pending.
        new_rows = list(session.run(
            "MATCH (n) WHERE n.cluster_id_pending IS NOT NULL "
            "RETURN n.cluster_id_pending AS cid, collect(n.id) AS members"
        ))
        new_members: dict[int, set[str]] = {
            int(r["cid"]): set(r["members"]) for r in new_rows
        }

    if not new_members:
        print("no pending cluster_ids; nothing to match")
        driver.close()
        return 0

    result = match_clusters(prior_members, new_members)

    # Build per-node stable ID map.
    id_remap: dict[str, int] = {}
    for raw_cid, stable_cid in result["assignments"].items():
        for node_id in new_members[raw_cid]:
            id_remap[node_id] = stable_cid

    # Persist stable IDs that need renaming.
    stable_renames = sorted({
        result["assignments"][raw] for raw in result["renames_needed"]
    })
    renames_path = REPO / "data" / "cluster_renames_needed.json"
    renames_path.parent.mkdir(parents=True, exist_ok=True)
    renames_path.write_text(json.dumps(stable_renames))

    total_clusters = len(result["assignments"])
    print(f"clusters: {total_clusters} total; {len(stable_renames)} needing rename")
    print(f"renames_needed written to {renames_path}")

    if args.dry_run:
        driver.close()
        return 0

    # Write stable cluster_id_pending back in batches.
    write_rows = [{"id": nid, "stable_id": sid} for nid, sid in id_remap.items()]
    WRITE_BATCH = 1000
    with driver.session(database=database) as session:
        for i in range(0, len(write_rows), WRITE_BATCH):
            session.run(
                "UNWIND $rows AS row "
                "MATCH (n {id: row.id}) "
                "SET n.cluster_id_pending = row.stable_id",
                rows=write_rows[i:i + WRITE_BATCH],
            )

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
