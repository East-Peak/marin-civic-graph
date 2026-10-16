"""Votes Part B2, increment d: the apply runner — approval binding, the canonical run lock, the baseline fingerprint,
one transaction verified before commit, and the post-apply export. Mock drivers only; fictional data."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import votes_apply  # noqa: E402
from case_additive_plan import fingerprint, plan_additive, write_export  # noqa: E402
from case_additive_plan import apply_additive  # noqa: E402
from votes_apply import ApplyRefused, approval_sha, check_published_edges, expected_edges, run_apply  # noqa: E402


def _n(id_, labels, **props):
    return {"id": id_, "labels": labels, "properties": {"id": id_, **props}}


def _e(s, t, rel, **props):
    return {"start_id": s, "end_id": t, "type": rel, "properties": props}


BASE_NODES = [_n("meeting-body-x-1", ["Meeting"], meeting_date="2020-06-09"),
              _n("person-ann-alder", ["Person"], name="Ann Alder")]
BASE_EDGES = []
CASE_NODES = [_n("vev-body-x-1-aaaa-L40", ["Decision"], meeting_id="meeting-body-x-1", status="carried")]
CASE_EDGES = [_e("vev-body-x-1-aaaa-L40", "meeting-body-x-1", "DECIDED_AT"),
              _e("person-ann-alder", "vev-body-x-1-aaaa-L40", "CAST_VOTE", vote="aye", ledger_event_id="vev-x",
                 doc_sha256="d" * 64, evidence='{"kind":"named","span":[1,2]}', disposition="named")]


def _setup(tmp_path):
    """A state dir as `prepare` leaves it: plan (ops, candidate, baseline sha), approval manifest, state."""
    state = tmp_path / "votes-b"
    (state / "plan").mkdir(parents=True)
    write_export(state / "baseline", BASE_NODES, BASE_EDGES)
    ops = plan_additive(BASE_NODES, BASE_EDGES, CASE_NODES, CASE_EDGES)
    nodes, edges = apply_additive(BASE_NODES, BASE_EDGES, ops)
    cand = write_export(state / "plan" / "candidate", nodes, edges)
    (state / "plan" / "ops.json").write_text(json.dumps(ops, sort_keys=True))
    (state / "plan" / "plan-report.json").write_text(json.dumps({
        "baseline": {"sha256": fingerprint(state / "baseline")}, "candidate_sha256": cand, "verification": [],
        "profile": "votes-b"}))
    (state / "plan" / "inverse.json").write_text("{}")
    (state / "review.md").write_text("S1 agree\n")
    files = {"plan/ops.json": state / "plan" / "ops.json", "plan/plan-report.json": state / "plan" / "plan-report.json",
             "plan/inverse.json": state / "plan" / "inverse.json", "review.md": state / "review.md",
             "plan/candidate/nodes.jsonl": state / "plan" / "candidate" / "nodes.jsonl",
             "plan/candidate/edges.jsonl": state / "plan" / "candidate" / "edges.jsonl"}
    votes_apply.write_approval(state, files)
    return state, nodes, edges


class FakeResult:
    def __init__(self, rows=None, n=None):
        self.rows, self.n = rows or [], n

    def single(self):
        return {"n": self.n}

    def __iter__(self):
        return iter(self.rows)


class FakeGraph:
    """Enough of a Neo4j driver: committed nodes/edges, a transaction that stages writes, export paging."""

    def __init__(self, nodes, edges, *, commit_raises_after_commit=False, commit_raises_before=False,
                 tamper_in_tx=False, tamper_after_commit=False):
        self.nodes, self.edges = list(nodes), list(edges)
        self.calls = []
        self.commit_raises_after_commit = commit_raises_after_commit
        self.commit_raises_before = commit_raises_before
        self.tamper_in_tx, self.tamper_after_commit = tamper_in_tx, tamper_after_commit

    def session(self, database=None):
        self.calls.append("session")
        return FakeSession(self)

    def close(self):
        self.calls.append("close")


class FakeSession:
    def __init__(self, g):
        self.g = g

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        return _page(self.g.nodes, self.g.edges, query, params)

    def begin_transaction(self):
        self.g.calls.append("begin")
        return FakeTx(self.g)


def _page(nodes, edges, query, params):
    if "count(n)" in query:
        return FakeResult(n=None, rows=[]) if False else _Count(len(nodes))
    if "count(r)" in query:
        return _Count(len(edges))
    rows = sorted(nodes, key=lambda n: n["id"]) if "RETURN n.id AS id" in query else \
        sorted(edges, key=lambda e: (e["start_id"], e["type"], e["end_id"]))
    page = rows[params["skip"]:params["skip"] + params["limit"]]
    return FakeResult(rows=[dict(r) for r in page])


class _Count:
    def __init__(self, c):
        self.c = c

    def single(self):
        return {"c": self.c}


class FakeTx:
    def __init__(self, g):
        self.g, self.nodes, self.edges = g, list(g.nodes), list(g.edges)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False  # leaving without commit = rollback: staged rows are dropped

    def run(self, query, **params):
        self.g.calls.append("tx.run")
        if "SKIP $skip" in query:
            return _page(self.nodes, self.edges, query, params)
        rows = params["rows"]
        if query.startswith("UNWIND $rows AS id OPTIONAL MATCH") or "WHERE r IS NOT NULL" in query:
            return FakeResult(n=0)
        if "CREATE (n:" in query:
            labels = query.split("CREATE (n:")[1].split(")")[0].split(":")
            self.nodes += [{"id": r["props"]["id"], "labels": sorted(labels), "properties": dict(r["props"])}
                           for r in rows]
        elif "CREATE (s)-[r:" in query:
            rel = query.split("CREATE (s)-[r:")[1].split("]")[0]
            self.edges += [{"start_id": r["start_id"], "end_id": r["end_id"], "type": rel,
                            "properties": dict(r["props"])} for r in rows]
        if self.g.tamper_in_tx and len(self.edges) > len(self.g.edges):
            self.edges[-1] = {**self.edges[-1], "properties": {**self.edges[-1]["properties"], "vote": "no"}}
        return FakeResult(n=len(rows))

    def commit(self):
        if self.g.commit_raises_before:
            raise RuntimeError("connection reset before commit")
        self.g.nodes, self.g.edges = self.nodes, self.edges
        if self.g.tamper_after_commit:
            self.g.nodes = self.g.nodes + [_n("person-stray", ["Person"])]
        self.g.calls.append("commit")
        if self.g.commit_raises_after_commit:
            raise RuntimeError("connection reset after the server committed")


URI = "bolt://localhost:7688"


def _run(state, graph, tmp_path, approve=None, uri=URI):
    canonical = tmp_path / "canonical"
    canonical.mkdir(exist_ok=True)
    return run_apply(state, approve=approve or approval_sha(state), canonical_root=canonical, uri=uri,
                     driver_factory=lambda: graph, database="neo4j")


class TestApproval:
    def test_the_approval_must_match_and_every_listed_file_is_rehashed(self, tmp_path):
        state, *_ = _setup(tmp_path)
        g = FakeGraph(BASE_NODES, BASE_EDGES)
        with pytest.raises(ApplyRefused, match="approval"):
            _run(state, g, tmp_path, approve="0" * 64)
        for rel in ("plan/ops.json", "review.md", "plan/candidate/edges.jsonl"):
            state, *_ = _setup(tmp_path / rel.replace("/", "_"))
            (state / rel).write_text((state / rel).read_text() + " ")
            with pytest.raises(ApplyRefused, match=rel):
                _run(state, FakeGraph(BASE_NODES, BASE_EDGES), tmp_path)
        assert g.calls == []

    def test_only_from_awaiting_apply(self, tmp_path):
        state, *_ = _setup(tmp_path)
        votes_apply.set_state(state, "APPLIED")
        with pytest.raises(ApplyRefused, match="AWAITING_APPLY"):
            _run(state, FakeGraph(BASE_NODES, BASE_EDGES), tmp_path)

    @pytest.mark.parametrize("uri", ["bolt://localhost:7687", "bolt://localhost", "neo4j+s://x.databases.neo4j.io",
                                     "bolt://otherhost:7688"])
    def test_only_the_open_marin_graph(self, tmp_path, uri):
        state, *_ = _setup(tmp_path)
        g = FakeGraph(BASE_NODES, BASE_EDGES)
        with pytest.raises(ApplyRefused, match="7688"):
            _run(state, g, tmp_path, uri=uri)
        assert g.calls == []

    def test_a_provisional_or_failing_plan_cannot_be_approved(self, tmp_path):
        state, *_ = _setup(tmp_path)
        report = json.loads((state / "plan" / "plan-report.json").read_text())
        (state / "plan" / "plan-report.json").write_text(json.dumps({**report, "verification": ["x"]}))
        with pytest.raises(ApplyRefused, match="verification"):
            votes_apply.write_approval(state, {"plan/plan-report.json": state / "plan" / "plan-report.json"})


class TestLock:
    def test_a_weekly_lock_holder_blocks_before_any_write(self, tmp_path):
        state, *_ = _setup(tmp_path)
        canonical = tmp_path / "canonical"
        (canonical / "data" / "ingest-runs").mkdir(parents=True)
        scripts = Path(__file__).resolve().parents[2] / "scripts"
        holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
            import sys, time; sys.path.insert(0, {str(scripts)!r})
            from pathlib import Path; from run_lock import run_lock
            with run_lock(Path({str(canonical)!r})):
                print("held", flush=True); time.sleep(30)
        """)], stdout=subprocess.PIPE, env={**os.environ, "OPEN_MARIN_RUN_LOCK_OWNER": ""})
        try:
            assert holder.stdout.readline().strip() == b"held"
            g = FakeGraph(BASE_NODES, BASE_EDGES)
            with pytest.raises(votes_apply.RunLockHeld):
                run_apply(state, approve=approval_sha(state), canonical_root=canonical, uri=URI,
                          driver_factory=lambda: g, database="neo4j")
            assert g.calls == [] and votes_apply.get_state(state) == "AWAITING_APPLY"
        finally:
            holder.kill()
            holder.wait()


class TestApply:
    def test_drift_writes_nothing(self, tmp_path):
        state, *_ = _setup(tmp_path)
        g = FakeGraph(BASE_NODES + [_n("person-new-since", ["Person"])], BASE_EDGES)
        assert _run(state, g, tmp_path) == "DRIFT"
        assert "begin" not in g.calls and votes_apply.get_state(state) == "AWAITING_APPLY"
        assert (state / "apply" / "pre-apply-backup" / "nodes.jsonl").exists()

    def test_success(self, tmp_path):
        state, nodes, edges = _setup(tmp_path)
        g = FakeGraph(BASE_NODES, BASE_EDGES)
        assert _run(state, g, tmp_path) == "APPLIED"
        assert g.calls.count("commit") == 1 and votes_apply.get_state(state) == "APPLIED"
        cand = json.loads((state / "plan" / "plan-report.json").read_text())["candidate_sha256"]
        assert fingerprint(state / "apply" / "post-apply-export") == cand

    def test_in_transaction_mismatch_rolls_back(self, tmp_path):
        state, *_ = _setup(tmp_path)
        g = FakeGraph(BASE_NODES, BASE_EDGES, tamper_in_tx=True)
        assert _run(state, g, tmp_path) == "ROLLED_BACK"
        assert "commit" not in g.calls and g.nodes == BASE_NODES and g.edges == BASE_EDGES
        assert votes_apply.get_state(state) == "ROLLED_BACK"

    def test_commit_failure_before_the_server_commits_is_still_unverified(self, tmp_path):
        state, *_ = _setup(tmp_path)
        g = FakeGraph(BASE_NODES, BASE_EDGES, commit_raises_before=True)
        assert _run(state, g, tmp_path) == "APPLY_UNVERIFIED"
        assert "commit_uncertain" in (state / "apply" / "RECOVERY.md").read_text()

    def test_commit_raising_after_the_server_committed_is_unverified_not_rolled_back(self, tmp_path):
        state, *_ = _setup(tmp_path)
        g = FakeGraph(BASE_NODES, BASE_EDGES, commit_raises_after_commit=True)
        assert _run(state, g, tmp_path) == "APPLY_UNVERIFIED"
        recovery = (state / "apply" / "RECOVERY.md").read_text()
        assert "commit_uncertain" in recovery and "pre-apply-backup" in recovery and "inverse.json" in recovery
        assert "post-apply export MATCHES" in recovery  # the export shows what happened; still never auto-promoted

    def test_post_apply_mismatch_is_unverified(self, tmp_path):
        state, *_ = _setup(tmp_path)
        g = FakeGraph(BASE_NODES, BASE_EDGES, tamper_after_commit=True)
        assert _run(state, g, tmp_path) == "APPLY_UNVERIFIED"
        assert "post_export_mismatch" in (state / "apply" / "RECOVERY.md").read_text()
        with pytest.raises(ApplyRefused, match="AWAITING_APPLY"):
            _run(state, FakeGraph(BASE_NODES, BASE_EDGES), tmp_path)  # never retried blindly

    def test_the_backup_is_kept(self, tmp_path):
        state, *_ = _setup(tmp_path)
        _run(state, FakeGraph(BASE_NODES, BASE_EDGES, commit_raises_after_commit=True), tmp_path)
        assert fingerprint(state / "apply" / "pre-apply-backup") == fingerprint(state / "baseline")


class TestExpectedAndPublished:
    def test_expected_edges_from_ops(self):
        ops = plan_additive(BASE_NODES, BASE_EDGES, CASE_NODES, CASE_EDGES)
        assert expected_edges(ops) == [{"start_id": "person-ann-alder", "end_id": "vev-body-x-1-aaaa-L40",
                                        "vote": "aye"}]

    def test_published_edges_must_equal_the_expected_set(self, tmp_path):
        import sqlite3
        db = tmp_path / "a.sqlite"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE edges (source TEXT, rel TEXT, target TEXT, props TEXT)")
        con.executemany("INSERT INTO edges VALUES (?,?,?,?)", [
            ("person-ann-alder", "CAST_VOTE", "vev-body-x-1-aaaa-L40", '{"vote":"aye"}'),
            ("person-other", "CAST_VOTE", "decision-elsewhere-1", '{"vote":"no"}')])
        con.commit()
        con.close()
        exp = [{"start_id": "person-ann-alder", "end_id": "vev-body-x-1-aaaa-L40", "vote": "aye"}]
        assert check_published_edges(db, exp, scope=("vev-body-x-",)) == []
        assert check_published_edges(db, exp + [{"start_id": "p", "end_id": "vev-body-x-2", "vote": "no"}],
                                     scope=("vev-body-x-",)) != []
        assert check_published_edges(db, [{**exp[0], "vote": "no"}], scope=("vev-body-x-",)) != []


class TestReviewAndPages:
    SHEET = "# x\n\n### S1. vev-a\n- x\n\n### S2. vev-b\n- y\n"

    def test_review_must_answer_every_item_and_doubts_must_be_held(self):
        ok = votes_apply.review_problems(self.SHEET, "S1 agree\nS2 unsure: arrival unclear\n", attached={"vev-a"})
        assert ok == []
        assert votes_apply.review_problems(self.SHEET, "S1 agree\n", attached=set()) == ["S2 is not answered"]
        bad = votes_apply.review_problems(self.SHEET, "S1 disagree: wrong person\nS2 agree\n", attached={"vev-a"})
        assert bad == ["S1 (vev-a) is disagree but still attached"]
        assert votes_apply.review_problems(self.SHEET, "S1 agree\nS2 agree\nS3 agree\n", attached=set()) == [
            "S3 is not in the sheet"]

    def test_page_shows_each_planned_vote(self):
        html = "<li>Ann Alder <span>voted aye</span></li><li>Bea Birch <span>absent</span></li>"
        assert votes_apply.page_problems(html, [("Ann Alder", "aye"), ("Bea Birch", "absent")]) == []
        assert votes_apply.page_problems(html, [("Ann Alder", "aye"), ("Bea Birch", "no")]) == [
            "expected 1 'voted no' label(s), found 0"]
        assert votes_apply.page_problems(html, [("Cy Cedar", "aye")]) == ["Cy Cedar is not on the page"]


class TestBakeCheck:
    def test_new_decisions_labels_fts_and_props(self, tmp_path):
        import sqlite3
        db = tmp_path / "s.sqlite"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, search_label TEXT, props TEXT)")
        con.execute("CREATE TABLE edges (source TEXT, rel TEXT, target TEXT, props TEXT)")
        con.execute("CREATE VIRTUAL TABLE search_fts USING fts5(search_label, search_terms, content='', "
                    "tokenize='unicode61')")
        label = "Example Council vote, item 7 — carried"
        con.execute("INSERT INTO nodes VALUES (?,?,?,?)", ("vev-body-x-1-aaaa-L40", "Decision", label,
                                                          json.dumps({"status": "carried", "item_number": "7"})))
        rowid = con.execute("SELECT rowid FROM nodes WHERE id = 'vev-body-x-1-aaaa-L40'").fetchone()[0]
        con.execute("INSERT INTO search_fts(rowid, search_label, search_terms) VALUES (?,?,?)",
                    (rowid, label, f"vev-body-x-1-aaaa-L40 {label.lower()}"))
        con.execute("INSERT INTO edges VALUES (?,?,?,?)", ("person-ann-alder", "CAST_VOTE", "vev-body-x-1-aaaa-L40",
                                                          '{"vote":"aye"}'))
        con.commit()
        new = [{"id": "vev-body-x-1-aaaa-L40", "labels": ["Decision"], "properties": {
            "id": "vev-body-x-1-aaaa-L40", "search_label": label, "status": "carried", "item_number": "7",
            "motion_text": None}}]
        exp = [{"start_id": "person-ann-alder", "end_id": "vev-body-x-1-aaaa-L40", "vote": "aye"}]
        assert votes_apply.bake_problems(db, new, exp, scope=("vev-body-x-",)) == []
        con.execute("UPDATE nodes SET props = ? WHERE id = 'vev-body-x-1-aaaa-L40'",
                    (json.dumps({"status": "carried", "motion_text": "secret"}),))
        con.execute("UPDATE nodes SET search_label = 'vev-body-x-1-aaaa-L40'")
        con.commit()
        probs = votes_apply.bake_problems(db, new, exp, scope=("vev-body-x-",))
        assert any("search_label" in p for p in probs) and any("motion_text" in p for p in probs)


class TestPrepare:
    def _world(self, tmp_path, *, provisional=False, matches=True, review="S1 agree\n", bake_ok=True):
        state = tmp_path / "votes-b"
        bundle, plan = state / "bundle", state / "plan"
        bundle.mkdir(parents=True)
        write_export(state / "baseline", BASE_NODES, BASE_EDGES)
        write_export(bundle, CASE_NODES, CASE_EDGES)
        src = tmp_path / "ledger-events.jsonl"
        src.write_text("{}\n")
        (bundle / "inputs.json").write_text(json.dumps({"provisional": provisional, "inputs": {
            "ledger/events.jsonl": {"path": str(src), "sha256": votes_apply._sha_bytes(src.read_bytes())},
            "baseline/nodes.jsonl": {"path": str(state / "baseline" / "nodes.jsonl"),
                                     "sha256": fingerprint(state / "baseline")["nodes.jsonl"]},
            "baseline/edges.jsonl": {"path": str(state / "baseline" / "edges.jsonl"),
                                     "sha256": fingerprint(state / "baseline")["edges.jsonl"]}}}))
        (bundle / "accounting.json").write_text(json.dumps({"matches_expected": matches}))
        (bundle / "dispositions.jsonl").write_text(json.dumps({"event_id": "vev-x", "reason": "attached"}) + "\n")
        import case_additive_plan
        old = case_additive_plan.STAGING_ROOTS
        case_additive_plan.STAGING_ROOTS = (state,)
        try:
            assert case_additive_plan.main(["--baseline", str(state / "baseline"), "--case", str(bundle), "--out",
                                            str(plan), "--profile", "votes-b"]) == 0
        finally:
            case_additive_plan.STAGING_ROOTS = old
        (state / "spot-check.md").write_text("### S1. vev-x\n")
        (state / "spot-check-review.md").write_text(review)
        (state / "bake-check.json").write_text(json.dumps({"problems": [] if bake_ok else ["x"]}))
        return state

    def _prepare(self, state):
        return votes_apply.prepare(state, bundle=state / "bundle", plan=state / "plan",
                                   sheet=state / "spot-check.md", review=state / "spot-check-review.md",
                                   bake_check=state / "bake-check.json")

    def test_prepare_records_everything_and_awaits_apply(self, tmp_path):
        state = self._world(tmp_path)
        sha = self._prepare(state)
        assert votes_apply.get_state(state) == "AWAITING_APPLY" and sha == approval_sha(state)
        files = json.loads((state / "plan" / "approval-inputs.json").read_text())["files"]
        for name in ("plan/ops.json", "plan/plan-report.json", "plan/inverse.json", "plan/expected-edges.jsonl",
                     "plan/candidate/nodes.jsonl", "bundle/nodes.jsonl", "bundle/accounting.json",
                     "input/ledger/events.jsonl", "spot-check.md", "spot-check-review.md", "bake-check.json"):
            assert name in files, name
        assert [json.loads(x) for x in (state / "plan" / "expected-edges.jsonl").read_text().splitlines()] == [
            {"end_id": "vev-body-x-1-aaaa-L40", "start_id": "person-ann-alder", "vote": "aye"}]

    @pytest.mark.parametrize("kw, match", [({"provisional": True}, "provisional"),
                                           ({"matches": False}, "manifest"),
                                           ({"review": "S1 disagree: no\n"}, "spot check"),
                                           ({"review": ""}, "spot check"),
                                           ({"bake_ok": False}, "bake")])
    def test_prepare_refuses(self, tmp_path, kw, match):
        state = self._world(tmp_path, **kw)
        with pytest.raises(ApplyRefused, match=match):
            self._prepare(state)
        assert votes_apply.get_state(state) is None

    def test_prepare_refuses_a_plan_of_another_bundle(self, tmp_path):
        state = self._world(tmp_path)
        write_export(state / "bundle", CASE_NODES[:1], CASE_EDGES[:1])
        with pytest.raises(ApplyRefused, match="bundle"):
            self._prepare(state)

    def test_prepare_refuses_a_plan_on_another_baseline(self, tmp_path):
        state = self._world(tmp_path)
        inputs = json.loads((state / "bundle" / "inputs.json").read_text())
        inputs["inputs"]["baseline/nodes.jsonl"]["sha256"] = "0" * 64
        (state / "bundle" / "inputs.json").write_text(json.dumps(inputs))
        with pytest.raises(ApplyRefused, match="baseline"):
            self._prepare(state)


class TestPublishedCli:
    def _artifact(self, tmp_path):
        import sqlite3
        db = tmp_path / "pub.sqlite"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, search_label TEXT, props TEXT)")
        con.execute("CREATE TABLE edges (source TEXT, rel TEXT, target TEXT, props TEXT)")
        rows = [("person-ann-alder", "Ann Alder"), ("person-bea-birch", "Bea Birch")]
        con.executemany("INSERT INTO nodes VALUES (?, 'Person', ?, '{}')", rows)
        votes = [("person-ann-alder", "vev-novato-city-council-1-aa-L1", "aye"),
                 ("person-bea-birch", "vev-marin-county-bos-1-bb-L1", "no")]
        con.executemany("INSERT INTO edges VALUES (?, 'CAST_VOTE', ?, ?)",
                        [(s, t, json.dumps({"vote": v})) for s, t, v in votes])
        con.commit()
        con.close()
        state = tmp_path / "votes-b"
        (state / "plan").mkdir(parents=True)
        (state / "plan" / "expected-edges.jsonl").write_text("".join(
            json.dumps({"start_id": s, "end_id": t, "vote": v}) + "\n" for s, t, v in votes))
        votes_apply.set_state(state, "APPLIED")
        return db, state

    def test_published_verified_needs_edges_and_both_pages(self, tmp_path, monkeypatch):
        db, state = self._artifact(tmp_path)
        pages = {"https://site/decision/vev-novato-city-council-1-aa-L1": "Ann Alder voted aye",
                 "https://site/decision/vev-marin-county-bos-1-bb-L1": "Bea Birch voted no"}
        monkeypatch.setattr(votes_apply, "_fetch", lambda url: pages[url])
        args = ["check-published", "--state-dir", str(state), "--sqlite", str(db), "--base-url", "https://site"]
        assert votes_apply.main(args) == 0 and votes_apply.get_state(state) == "PUBLISHED_VERIFIED"

    def test_a_page_without_its_labels_fails(self, tmp_path, monkeypatch):
        db, state = self._artifact(tmp_path)
        monkeypatch.setattr(votes_apply, "_fetch", lambda url: "Ann Alder Bea Birch")
        args = ["check-published", "--state-dir", str(state), "--sqlite", str(db), "--base-url", "https://site"]
        assert votes_apply.main(args) == 1 and votes_apply.get_state(state) == "APPLIED"

    def test_only_after_applied(self, tmp_path, monkeypatch):
        db, state = self._artifact(tmp_path)
        votes_apply.set_state(state, "AWAITING_APPLY")
        monkeypatch.setattr(votes_apply, "_fetch", lambda url: "")
        args = ["check-published", "--state-dir", str(state), "--sqlite", str(db), "--base-url", "https://site"]
        assert votes_apply.main(args) == 1
