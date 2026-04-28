import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from match_clusters import match_clusters


def _members(d: dict[int, list[str]]) -> dict[int, set[str]]:
    return {k: set(v) for k, v in d.items()}


class TestMatchClusters:
    def test_perfect_match_keeps_ids(self):
        prior = {7: ["a", "b", "c"], 12: ["d", "e", "f"]}
        new = {0: ["a", "b", "c"], 1: ["d", "e", "f"]}
        m = match_clusters(_members(prior), _members(new))
        # New cluster 0 (members a,b,c) should map to prior 7.
        assert m["assignments"][0] == 7
        assert m["assignments"][1] == 12
        assert m["renames_needed"] == set()

    def test_new_cluster_gets_new_id(self):
        prior = {7: ["a", "b", "c"]}
        new = {0: ["a", "b", "c"], 1: ["x", "y", "z"]}
        m = match_clusters(_members(prior), _members(new))
        assert m["assignments"][0] == 7
        # new[1] has no overlap with any prior — fresh ID, distinct from 7.
        assert m["assignments"][1] != 7
        assert 1 in m["renames_needed"]

    def test_dropped_prior_cluster_no_assignment(self):
        prior = {7: ["a"], 9: ["dead"]}
        new = {0: ["a"]}
        m = match_clusters(_members(prior), _members(new))
        assert m["assignments"][0] == 7
        # 9 is dropped; not present in assignments.
        assert 9 not in m["assignments"].values()

    def test_split_largest_descendant_inherits_id(self):
        prior = {7: ["a", "b", "c", "d"]}
        new = {0: ["a", "b", "c"], 1: ["d"]}
        m = match_clusters(_members(prior), _members(new))
        # The 3-member descendant inherits 7.
        assert m["assignments"][0] == 7
        assert m["assignments"][1] != 7
        assert 1 in m["renames_needed"]

    def test_merge_largest_ancestor_id_wins(self):
        prior = {7: ["a", "b", "c"], 9: ["d"]}
        new = {0: ["a", "b", "c", "d"]}
        m = match_clusters(_members(prior), _members(new))
        # New cluster has more overlap with 7 (3) than 9 (1) → 7 wins.
        assert m["assignments"][0] == 7
        assert 0 in m["renames_needed"]  # merged → re-name
