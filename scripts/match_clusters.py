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
import sys

import numpy as np
from scipy.optimize import linear_sum_assignment

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print("match_clusters.main() is a stub at this commit (Task 16 fills it in)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
