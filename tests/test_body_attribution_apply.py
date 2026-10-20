"""Body attribution, increment (c): the apply path — prepare binds the approval to the exact bundle, proofs and
implementation bytes; apply holds the canonical run lock, refuses a canonical checkout not running the approved
guard, checks drift, runs one transaction verified before commit, never retries. Mock drivers; fictional data."""
from __future__ import annotations

import copy
import json
import subprocess
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
IMPL = ba.IMPL_FILES


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.org", "GIT_COMMITTER_NAME": "Test",
                        "GIT_COMMITTER_EMAIL": "test@example.org", "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
                        "HOME": str(root)})


def write_proof(path, b, **override):
    report = json.loads((b["plan"] / "plan-report.json").read_text())
    path.write_text(json.dumps({"all_pass": True, "candidate_sha256": report["candidate_sha256"],
                                "baseline_sha256": report["baseline"]["sha256"],
                                "map_sha256": report["map"]["sha256"], "guard_sha256": ba._sha(ba.GUARD_PATH),
                                "implementation": ba.implementation()} | override))


@pytest.fixture
def bundle(world, monkeypatch):  # noqa: F811 (the imported fixture)
    """A plan, its map, both proofs (all pass), the implementation committed in a worktree, a canonical clone."""
    tmp = world["tmp"]
    monkeypatch.setattr(ba, "STAGING_ROOT", tmp / "staging")
    worktree, canonical = tmp / "worktree", tmp / "canonical"
    for rel in IMPL:
        (worktree / rel).parent.mkdir(parents=True, exist_ok=True)
        (worktree / rel).write_text(f"approved {rel}\n")
    monkeypatch.setattr(ba, "REPO", worktree)  # prepare records the implementation it runs from
    monkeypatch.setattr(ba, "GUARD_PATH", worktree / "registry" / "body-attribution-guard.yaml")
    m = tmp / "staging" / "map"
    ba.write_map(world["dir"], world["registry"], m)
    plan = tmp / "staging" / "plan"
    report = ba.write_plan(world["dir"], m, world["registry"], plan)
    ba.write_guard_file(list(ba.read_jsonl(m / "map.jsonl")), json.loads((m / "summary.json").read_text())["map_sha256"],
                        ba.GUARD_PATH)
    git(worktree, "init", "-q")
    git(worktree, "add", "-A")
    git(worktree, "commit", "-q", "-m", "the guard")
    git(tmp, "clone", "-q", str(worktree), str(canonical))  # the canonical checkout fast-forwarded to it
    b = {"plan": plan, "map": m, "canonical": canonical, "worktree": worktree, "tmp": tmp, "world": world,
         "report": report, "proofs": {n: tmp / "staging" / f"{n}.json" for n in ("weekly", "app")}}
    for path in b["proofs"].values():
        write_proof(path, b)
    return b


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
            "proof/weekly.json", "proof/app.json", "bodies.yaml"} | {f"impl/{r}" for r in IMPL} == set(files)
    text = (state / "APPLY.md").read_text()
    assert text.count(sha) == 3 and text.count("--database neo4j") == 3 and "undo" in text


def _spoil_json(path, **change):
    path.write_text(json.dumps({**json.loads(path.read_text()), **change}))


def _replace_inverse(b):
    stmts = json.loads((b["plan"] / "inverse.json").read_text())
    stmts[-1]["query"] = stmts[-1]["query"].replace("DELETE n", "DETACH DELETE n")
    (b["plan"] / "inverse.json").write_text(json.dumps(stmts))
    _spoil_json(b["plan"] / "plan-report.json", inverse_sha256=ba._sha(b["plan"] / "inverse.json"))


@pytest.mark.parametrize("spoil,match", [
    (lambda b: _spoil_json(b["proofs"]["weekly"], all_pass=False), "weekly"),
    (lambda b: _spoil_json(b["proofs"]["app"], candidate_sha256={"nodes.jsonl": "x"}), "candidate_sha256"),
    (lambda b: _spoil_json(b["proofs"]["app"], baseline_sha256=None), "baseline_sha256"),
    (lambda b: _spoil_json(b["proofs"]["weekly"], map_sha256="0" * 64), "map_sha256"),
    (lambda b: _spoil_json(b["proofs"]["app"], implementation={"revision": "d" * 40}), "implementation"),
    (lambda b: ba.GUARD_PATH.write_text("other\n"), "guard"),
    (lambda b: _spoil_json(b["plan"] / "inverse-identity.json", identical=False), "inverse"),
    (lambda b: _spoil_json(b["plan"] / "inverse-identity.json", candidate_sha256={"x": "y"}), "inverse"),
    (lambda b: (b["plan"] / "ops.json").write_text((b["plan"] / "ops.json").read_text() + " "), "ops.json"),
    (_replace_inverse, "inverse.json is not the inverse"),
    (lambda b: (b["map"] / "map.jsonl").write_text((b["map"] / "map.jsonl").read_text() + "\n"), "map"),
    (lambda b: (b["worktree"] / "scripts" / "normalize_meetings.py").write_text("uncommitted\n"), "uncommitted"),
])
def test_prepare_refuses_anything_that_is_not_of_this_bundle(bundle, spoil, match):
    spoil(bundle)
    with pytest.raises(ba.AttributionError, match=match):
        prepare(bundle)


def test_prepare_refuses_a_foreign_but_consistent_map(bundle):
    summary = json.loads((bundle["map"] / "summary.json").read_text())
    (bundle["map"] / "map.jsonl").write_text("{}\n")
    _spoil_json(bundle["map"] / "summary.json", map_sha256=ba._sha(bundle["map"] / "map.jsonl"))
    assert summary["map_sha256"] != ba._sha(bundle["map"] / "map.jsonl")
    with pytest.raises(ba.AttributionError, match="map"):
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
    """Answers forward or inverse statements; the pure twin is applied at each one's last statement."""

    def __init__(self, g):
        self.g, self.nodes, self.edges = g, list(g.nodes), list(g.edges)
        self.forward, self.inverse = ba.statements(g.ops), ba.inverse_statements(g.ops)

    def run(self, query, **params):
        if "SKIP $skip" in query:
            return _page(self.nodes, self.edges, query, params)
        for steps, twin in ((self.forward, ba.apply_ops), (self.inverse, ba.apply_inverse)):
            keys = [(s["query"], json.dumps(s["params"], sort_keys=True)) for s in steps]
            if (query, json.dumps(params, sort_keys=True)) in keys:  # two guards share a query, not its params
                i = keys.index((query, json.dumps(params, sort_keys=True)))
                break
        stmt = steps[i]
        self.g.calls.append(stmt["step"])
        if i == len(steps) - 1:
            self.nodes, self.edges = twin(self.nodes, self.edges, self.g.ops)
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


def _reverted(c):
    (c / "scripts" / "normalize_meetings.py").write_text("an older normalizer, without the guard\n")
    git(c, "commit", "-q", "-am", "revert the normalizer")  # a descendant of the approved commit


def _not_the_commit(c):
    git(c, "reset", "-q", "--hard", "HEAD")
    git(c, "checkout", "-q", "--orphan", "copied")  # the same bytes, but not the approved commit's history
    git(c, "commit", "-q", "-m", "copied by hand")


@pytest.mark.parametrize("canonical_change,match", [
    (_reverted, "normalize_meetings.py"),
    (lambda c: (c / "scripts" / "normalize_meetings.py").write_text("approved\n# dirty\n"), "normalize_meetings.py"),
    (lambda c: (c / "scripts" / "votes_apply.py").write_text("another executor\n"), "votes_apply.py"),
    (lambda c: (c / "registry" / "body-attribution-guard.yaml").unlink(), "guard"),
    (_not_the_commit, "commit"),
])
def test_apply_refuses_a_canonical_checkout_not_running_the_approved_guard(bundle, canonical_change, match):
    prepare(bundle)
    canonical_change(bundle["canonical"])
    g = _graph(bundle)
    with pytest.raises(votes_apply.ApplyRefused, match=match):
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


def test_check_reads_its_expectation_from_the_approval_not_from_files_changed_since(bundle):
    prepare(bundle)
    g = _graph(bundle)
    _spoil_json(bundle["plan"] / "plan-report.json", candidate_sha256=ba.fingerprint(bundle["world"]["dir"]))
    with pytest.raises(ba.AttributionError, match="plan-report.json changed"):
        ba.check(bundle["tmp"] / "staging" / "state", g, database="neo4j", out=bundle["tmp"] / "staging" / "c3")


def _undo(bundle, graph, approve=None):
    state = bundle["tmp"] / "staging" / "state"
    return ba.run_undo(state, approve=approve or votes_apply.approval_sha(state), canonical_root=bundle["canonical"],
                       uri=URI, database="neo4j", driver_factory=lambda: graph)


def test_undo_restores_the_baseline_in_one_verified_transaction(bundle):
    prepare(bundle)
    g = _graph(bundle)
    with pytest.raises(votes_apply.ApplyRefused, match="nothing was applied"):
        _undo(bundle, g)
    assert apply(bundle, g) == "APPLIED"
    g.calls.clear()
    assert _undo(bundle, g) == "UNDONE"
    assert g.calls.count("begin") == 1 and g.calls.count("commit") == 1
    state = bundle["tmp"] / "staging" / "state"
    assert ba.fingerprint(state / "undo" / "post-undo-export") == bundle["report"]["baseline"]["sha256"]
    with pytest.raises(votes_apply.ApplyRefused, match="already ran"):
        _undo(bundle, g)


def test_undo_refuses_a_graph_that_is_not_exactly_the_candidate(bundle):
    prepare(bundle)
    g = _graph(bundle)
    assert apply(bundle, g) == "APPLIED"
    g.nodes.append({"id": "place-new", "labels": ["Place"], "properties": {"id": "place-new"}})
    g.calls.clear()
    assert _undo(bundle, g) == "DRIFT"
    assert "begin" not in g.calls


def test_undo_guard_failure_rolls_back(bundle):
    prepare(bundle)
    g = _graph(bundle)
    assert apply(bundle, g) == "APPLIED"
    g.fail_step = "guard:institution_incident_counts"
    after = (copy.deepcopy(g.nodes), copy.deepcopy(g.edges))
    assert _undo(bundle, g) == "ROLLED_BACK"
    undo_calls = g.calls[len(g.calls) - g.calls[::-1].index("begin"):]
    assert (g.nodes, g.edges) == after and "commit" not in undo_calls and "rollback" in undo_calls
