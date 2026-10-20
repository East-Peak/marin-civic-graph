"""Body attribution, increment (c): the apply path — prepare binds the approval to the exact bundle, proofs and
implementation bytes; apply holds the canonical run lock, refuses a canonical checkout not running the approved
guard, checks drift, runs one transaction verified before commit, never retries. Mock drivers; fictional data."""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

import body_attribution as ba  # noqa: E402
import votes_apply  # noqa: E402
from test_body_attribution_migration import world  # noqa: E402,F401  (fixture)
from test_votes_apply import FakeResult, _page  # noqa: E402

URI = "bolt://localhost:7688"
IMPL = ("scripts/body_attribution.py", "scripts/normalize_meetings.py", "scripts/load_neo4j_v2.py",
        "registry/body-attribution-guard.yaml")


@pytest.fixture
def bundle(world, monkeypatch):  # noqa: F811 (the imported fixture)
    """A plan, its map, both proofs (all pass), a canonical checkout with the approved implementation bytes."""
    tmp = world["tmp"]
    monkeypatch.setattr(ba, "STAGING_ROOT", tmp / "staging")
    worktree, canonical = tmp / "worktree", tmp / "canonical"
    for rel in IMPL:
        (worktree / rel).parent.mkdir(parents=True, exist_ok=True)
        (worktree / rel).write_text(f"approved {rel}\n")
    monkeypatch.setattr(ba, "REPO", worktree)  # prepare records the implementation it runs from
    monkeypatch.setattr(ba, "GUARD_PATH", worktree / "registry" / "body-attribution-guard.yaml")
    monkeypatch.setattr(ba, "_revision", lambda: "c" * 40)
    m = tmp / "staging" / "map"
    ba.write_map(world["dir"], world["registry"], m)
    plan = tmp / "staging" / "plan"
    report = ba.write_plan(world["dir"], m, world["registry"], plan)
    ba.write_guard_file(list(ba.read_jsonl(m / "map.jsonl")), json.loads((m / "summary.json").read_text())["map_sha256"],
                        ba.GUARD_PATH)
    shutil.copytree(worktree, canonical)  # the canonical checkout fast-forwarded to the same commit
    proofs = {}
    for name in ("weekly", "app"):
        proofs[name] = tmp / "staging" / f"{name}.json"
        proofs[name].write_text(json.dumps({"all_pass": True, "candidate_sha256": report["candidate_sha256"],
                                            "guard_sha256": ba._sha(ba.GUARD_PATH), "code_revision": "c" * 40}))
    return {"plan": plan, "map": m, "proofs": proofs, "canonical": canonical, "tmp": tmp, "world": world,
            "report": report}


def prepare(b, **override):
    args = {"plan": b["plan"], "map_dir": b["map"], "bodies": b["world"]["registry"], "weekly": b["proofs"]["weekly"],
            "app": b["proofs"]["app"], "state_dir": b["tmp"] / "staging" / "state"} | override
    return ba.prepare(**args)


def test_prepare_binds_the_approval_to_every_file_it_rests_on(bundle):
    sha = prepare(bundle)
    state = bundle["tmp"] / "staging" / "state"
    assert votes_apply.get_state(state) == "AWAITING_APPLY"
    files = json.loads((state / votes_apply.APPROVAL).read_text())["files"]
    assert sha == votes_apply.approval_sha(state)
    assert {"plan/ops.json", "plan/plan-report.json", "plan/inverse.json", "plan/inverse-identity.json",
            "plan/candidate/nodes.jsonl", "plan/candidate/edges.jsonl", "map/map.jsonl", "map/summary.json",
            "proof/weekly.json", "proof/app.json", "bodies.yaml"} | {f"impl/{r}" for r in IMPL} <= set(files)
    assert (state / "APPLY.md").read_text().count(sha) >= 1


@pytest.mark.parametrize("spoil,match", [
    (lambda b: b["proofs"]["weekly"].write_text(json.dumps({**json.loads(b["proofs"]["weekly"].read_text()),
                                                            "all_pass": False})), "weekly"),
    (lambda b: b["proofs"]["app"].write_text(json.dumps({**json.loads(b["proofs"]["app"].read_text()),
                                                         "candidate_sha256": {"nodes.jsonl": "x"}})), "app"),
    (lambda b: b["proofs"]["app"].write_text(json.dumps({**json.loads(b["proofs"]["app"].read_text()),
                                                         "code_revision": "d" * 40})), "app"),
    (lambda b: ba.GUARD_PATH.write_text("other\n"), "guard"),
    (lambda b: (b["plan"] / "inverse-identity.json").write_text(json.dumps({"identical": False})), "inverse"),
])
def test_prepare_refuses_a_proof_that_is_not_of_this_bundle(bundle, spoil, match):
    spoil(bundle)
    with pytest.raises(ba.AttributionError, match=match):
        prepare(bundle)


class StepGraph:
    """A driver whose transaction answers the migration's statements with their planned counts (applying the pure
    twin at the last one) and pages its staged rows like export_live_graph; `fail_step` answers one more."""

    def __init__(self, nodes, edges, ops, fail_step=None):
        self.nodes, self.edges, self.ops, self.fail_step = list(nodes), list(edges), ops, fail_step
        self.calls = []

    def session(self, database=None):
        g = self

        class S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, query, **params):
                return _page(g.nodes, g.edges, query, params)

            def begin_transaction(self):
                g.calls.append("begin")
                return Tx(g)
        return S()

    def close(self):
        self.calls.append("close")


class Tx:
    def __init__(self, g):
        self.g, self.nodes, self.edges = g, list(g.nodes), list(g.edges)
        self.steps = ba.statements(g.ops)

    def run(self, query, **params):
        if "SKIP $skip" in query:
            return _page(self.nodes, self.edges, query, params)
        i = [s["query"] for s in self.steps].index(query)
        stmt = self.steps[i]
        self.g.calls.append(stmt["step"])
        if i == len(self.steps) - 1:
            self.nodes, self.edges = ba.apply_ops(self.nodes, self.edges, self.g.ops)
        return FakeResult(n=stmt["expect"] + (1 if stmt["step"] == self.g.fail_step else 0))

    def rollback(self):
        self.g.calls.append("rollback")

    def commit(self):
        self.g.nodes, self.g.edges = self.nodes, self.edges
        self.g.calls.append("commit")


def apply(bundle, graph, *, uri=URI, approve=None):
    state = bundle["tmp"] / "staging" / "state"
    return ba.run_apply(state, approve=approve or votes_apply.approval_sha(state), canonical_root=bundle["canonical"],
                        uri=uri, database="neo4j", driver_factory=lambda: graph)


def _graph(bundle, **kw):
    ops = json.loads((bundle["plan"] / "ops.json").read_text())
    return StepGraph(bundle["world"]["nodes"], bundle["world"]["edges"], ops, **kw)


def test_apply_runs_one_verified_transaction_and_records_applied(bundle):
    prepare(bundle)
    g = _graph(bundle)
    assert apply(bundle, g) == "APPLIED"
    assert g.calls.count("begin") == 1 and g.calls.count("commit") == 1 and "rollback" not in g.calls
    state = bundle["tmp"] / "staging" / "state"
    assert ba.fingerprint(state / "apply" / "post-apply-export") == bundle["report"]["candidate_sha256"]
    assert ba.fingerprint(state / "apply" / "pre-apply-backup") == bundle["report"]["baseline"]["sha256"]
    assert ba.check(state, g, database="neo4j", out=bundle["tmp"] / "staging" / "check")["matches"] is True


def test_a_count_off_plan_midway_rolls_back_and_leaves_the_graph_unchanged(bundle):
    prepare(bundle)
    g = _graph(bundle, fail_step="repoint:delete_old_edge")
    before = (copy.deepcopy(g.nodes), copy.deepcopy(g.edges))
    assert apply(bundle, g) == "ROLLED_BACK"
    assert "commit" not in g.calls and "rollback" in g.calls and "repoint:create_new_edge" not in g.calls
    assert (g.nodes, g.edges) == before


def test_a_graph_that_drifted_from_the_baseline_is_not_touched(bundle):
    prepare(bundle)
    g = _graph(bundle)
    g.nodes.append({"id": "place-new", "labels": ["Place"], "properties": {"id": "place-new"}})
    assert apply(bundle, g) == "DRIFT"
    assert "begin" not in g.calls
    assert votes_apply.get_state(bundle["tmp"] / "staging" / "state") == "AWAITING_APPLY"


@pytest.mark.parametrize("canonical_change", [
    lambda c: (c / "scripts" / "normalize_meetings.py").write_text("an older normalizer, without the guard\n"),
    lambda c: (c / "scripts" / "normalize_meetings.py").write_text("approved scripts/normalize_meetings.py\n# dirty\n"),
    lambda c: (c / "registry" / "body-attribution-guard.yaml").unlink(),
])
def test_apply_refuses_a_canonical_checkout_not_running_the_approved_guard(bundle, canonical_change):
    prepare(bundle)
    canonical_change(bundle["canonical"])
    g = _graph(bundle)
    with pytest.raises(votes_apply.ApplyRefused, match="canonical"):
        apply(bundle, g)
    assert g.calls == []  # no driver use at all


def test_apply_refuses_another_target_or_another_approval(bundle):
    prepare(bundle)
    g = _graph(bundle)
    with pytest.raises(votes_apply.ApplyRefused, match="7688"):
        apply(bundle, g, uri="bolt://localhost:7687")
    with pytest.raises(votes_apply.ApplyRefused, match="approve"):
        apply(bundle, g, approve="0" * 64)
    assert g.calls == []


def test_check_reports_a_graph_that_is_not_the_candidate(bundle):
    prepare(bundle)
    g = _graph(bundle)
    result = ba.check(bundle["tmp"] / "staging" / "state", g, database="neo4j", out=bundle["tmp"] / "staging" / "c2")
    assert result["matches"] is False and result["equals_baseline"] is True
