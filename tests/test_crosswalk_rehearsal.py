"""The crosswalk rehearsal and check-loaded (scripts/crosswalk_rehearsal.py), on a fictional city.

The rehearsal runs the real weekly chain (refresh_weekly.stage -> ingest.py -> the ProudCity adapter ->
the robots gate; refresh_weekly.load -> normalize_meetings.py --load) against a fake graph. Here every
response is pre-recorded (a fictional Lakeport site), so all four runs replay and nothing reaches the
network. check-loaded is then pointed at the rehearsal's own first run, with a post-export built from
its seed and its writes, then tampered with.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import crosswalk_rehearsal as cr  # noqa: E402
import guarded_load as gl  # noqa: E402
from tests.test_guarded_load import (  # noqa: E402
    ENTRIES, INST, PDF, PLACE, REG, SEED_EDGES, SEED_NODES, SID, XW_REL)

SITE = "https://www.lakeport.example"
NOW = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)  # in the past: a post-export is always taken after it
LISTED = {  # slug -> (title, {tab: pdf})
    "city-council-march-2-2020": ("City Council – March 2, 2020", {"minutes": PDF.format("minutes-2020-03-02")}),
    "city-council-march-2-2020-closed-session": ("City Council – March 2, 2020 (Closed Session)",
                                                 {"agenda": PDF.format("agenda-closed")}),
    "city-council-may-4-2026": ("City Council – May 4, 2026", {"agenda": PDF.format("agenda-2026-05-04")}),
}


def _detail(tabs: dict[str, str]) -> str:
    ids = {"agenda": "tab-agenda", "packet": "tab-agenda-packet", "minutes": "tab-minutes", "video": "tab-video"}
    return "".join(f'<div id="{ids[t]}"><a href="{u}">PDF</a></div>' for t, u in tabs.items())


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "repo"
    (repo / "registry" / "crosswalks").mkdir(parents=True)
    (repo / "scripts").symlink_to(REPO / "scripts", target_is_directory=True)
    config = {"id": SID, "adapter": "proudcity", "url": f"{SITE}/city-council-meetings/", "jurisdiction_id": PLACE,
              "institution_id": INST, "backfill_from": "2019-01-01", "identity": "crosswalk-required",
              "crosswalk": XW_REL, "schedule": "manual", "floors": {"max_newest_age_days": None}}
    (repo / "registry" / "proudcity-sources.yaml").write_text(yaml.safe_dump({"sources": [config]}))
    (repo / XW_REL).write_text(json.dumps({"format": 1, "source_id": SID, "entries": {
        k: v for k, v in ENTRIES.items() if "march-9" not in k}}))
    export = tmp_path / "export"
    export.mkdir()
    (export / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in SEED_NODES))
    (export / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in SEED_EDGES))
    store = cr.ResponseStore(tmp_path / "responses")
    store.put(f"{SITE}/robots.txt", status=200, headers={}, body=b"User-agent: *\nAllow: /\n", error=None)
    listing = "".join(f'<a href="/meetings/{s}/">{t}</a>' for s, (t, _) in LISTED.items())
    store.put(f"{SITE}/city-council-meetings/", status=200, headers={}, body=listing.encode(), error=None)
    for slug, (_, tabs) in LISTED.items():
        store.put(f"{SITE}/meetings/{slug}/", status=200, headers={}, body=_detail(tabs).encode(), error=None)
    return {"repo": repo, "export": export, "responses": store.path, "work": tmp_path / "staging" / "rehearsal"}


def _rehearse(world, **kw):
    return cr.rehearse(SID, world["export"], world["work"], repo=world["repo"], responses=world["responses"],
                       now=NOW, **kw)


def test_the_rehearsal_passes_every_check_on_a_clean_city(world):
    results = _rehearse(world)
    failed = [c for c in results["checks"] if not c["ok"]]
    assert failed == []
    assert {c["check"].split(":")[0] for c in results["checks"]} >= set(cr.VARIANTS)
    assert results["counts"]["new_meetings"] == 1  # May 4, 2026: listing-only
    assert results["counts"]["new_records"] == 3  # its agenda, the closed session's agenda, the listing snapshot
    assert results["expected_records"] == {"listing_snapshot": 1, "existing_exact_match": 1,
                                           "artifact_on_new_meeting": 1, "new_artifact_on_existing_meeting": 1}
    assert "**Rehearsal: PASS**" in cr.render_rehearsal(results)


def _tree(*dirs):
    import hashlib
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for d in dirs if d.exists() for p in sorted(d.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def test_the_rehearsal_never_changes_the_repo(world):
    before = _tree(REPO / "data", REPO / "registry", world["repo"] / "registry", world["export"])
    _rehearse(world)
    assert _tree(REPO / "data", REPO / "registry", world["repo"] / "registry", world["export"]) == before


def test_a_replay_cannot_reach_the_network(world):
    store = cr.ResponseStore(world["responses"])
    store._file(f"{SITE}/meetings/city-council-may-4-2026/").unlink()  # unrecorded: replay must not fetch it
    results = _rehearse(world)
    logs = "".join(p.read_text() for p in (world["work"] / "empty-cache").rglob("logs/ingest-*.log"))
    assert "no recorded response" in logs  # the fetch failed in the child; nothing was sent
    assert results["runs"]["empty-cache"]["status"] != "awaiting_publish_approval"
    assert not all(c["ok"] for c in results["checks"])


def test_the_rehearsal_refuses_to_work_inside_the_repo(world):
    with pytest.raises(ValueError):
        cr.rehearse(SID, world["export"], REPO / "data" / "rehearsal-x", repo=world["repo"],
                    responses=world["responses"], now=NOW)


def test_a_hold_fails_the_rehearsal(world):
    store = cr.ResponseStore(world["responses"])
    store.put(f"{SITE}/meetings/city-council-march-2-2020/", status=200, headers={},
              body=_detail({"minutes": PDF.format("minutes-2020-03-02-v2")}).encode(), error=None)
    results = _rehearse(world)
    assert any(not c["ok"] for c in results["checks"])
    assert results["runs"]["empty-cache"]["outcome"] == "held"
    assert "**Rehearsal: FAIL**" in cr.render_rehearsal(results)


# --- check-loaded on the rehearsal's own first run ---------------------------------------------------------


@pytest.fixture
def ran(world, tmp_path):
    results = _rehearse(world)
    assert all(c["ok"] for c in results["checks"])
    root = world["work"] / "empty-cache"
    run_id = json.loads(next((root / "data/ingest-runs").glob("*/state.json")).read_text())["run_id"]
    graph = world["work"] / "graph-populated-cache"  # exactly one load: the first run's writes
    nodes, edges = gl.FakeGraphPort(graph).overlay()
    post = tmp_path / "post-export"
    post.mkdir()
    seed_nodes = [json.loads(line) for line in (world["export"] / "nodes.jsonl").read_text().splitlines()]
    seed_edges = [json.loads(line) for line in (world["export"] / "edges.jsonl").read_text().splitlines()]
    return {"root": root, "run_id": run_id, "post": post, "nodes": seed_nodes + nodes, "edges": seed_edges + edges}


def _post(ran, nodes=None, edges=None):
    (ran["post"] / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes or ran["nodes"]))
    (ran["post"] / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges or ran["edges"]))


def _check(ran, tmp_path):
    return cr.check_loaded(ran["root"], ran["run_id"], SID, ran["post"], tmp_path / "out")


def test_check_loaded_never_passes_a_held_source(ran, tmp_path):
    _post(ran)
    run = ran["root"] / "data/ingest-runs" / ran["run_id"]
    state = json.loads((run / "state.json").read_text())
    state["sources"][SID].update(ok=False, held=True)
    state["loaded"].remove(SID)
    (run / "state.json").write_text(json.dumps(state))
    assert _check(ran, tmp_path)["verdict"] == "HELD"


def test_a_retried_load_is_checked_against_all_its_attempts(ran, tmp_path):
    _post(ran)
    run = ran["root"] / "data/ingest-runs" / ran["run_id"]
    state = json.loads((run / "state.json").read_text())
    first = run / "load-reports" / state["sources"][SID]["load_report"]["path"]
    retry = json.loads(first.read_text())
    retry["created"] = {"nodes": {}, "edges": []}  # the retry found everything already there
    (run / "load-reports" / f"{SID}.2.json").write_text(json.dumps(retry))
    state["sources"][SID]["load_report"]["path"] = f"{SID}.2.json"
    (run / "state.json").write_text(json.dumps(state))
    assert _check(ran, tmp_path)["verdict"] == "PASS"


def test_check_loaded_passes_on_exactly_the_planned_writes(ran, tmp_path):
    _post(ran)
    results = _check(ran, tmp_path)
    assert [c for c in results["checks"] if not c["ok"]] == [] and results["verdict"] == "PASS"


def _with(ran, nid, **props):
    return [{**n, "properties": {**n["properties"], **props}} if n["id"] == nid else n for n in ran["nodes"]]


@pytest.mark.parametrize("tamper", ["meeting-property", "extra-record", "lost-edge", "stub-promotion", "new-label",
                                    "lost-agenda-item-edge", "duplicate-edge", "new-edge-property"])
def test_check_loaded_fails_on_any_write_it_did_not_plan(ran, tmp_path, tamper):
    nodes, edges = ran["nodes"], ran["edges"]
    if tamper == "meeting-property":
        nodes = _with(ran, REG, meeting_type="regular")
    elif tamper == "extra-record":
        nodes = nodes + [{"id": "record-x", "labels": ["Record"], "properties": {"id": "record-x", "source_id": SID}}]
    elif tamper == "lost-edge":
        edges = [e for e in edges if not (e["start_id"] == REG and e["type"] == "AT_INSTITUTION")]
    elif tamper == "stub-promotion":
        nodes = _with(ran, INST, promotion_state="promoted")
    elif tamper == "lost-agenda-item-edge":
        edges = [e for e in edges if e["type"] != "PART_OF_MEETING"]
    elif tamper == "duplicate-edge":
        edges = edges + [e for e in edges if e["start_id"] == REG and e["type"] == "AT_INSTITUTION"]
    elif tamper == "new-edge-property":
        new = {n["id"] for n in ran["nodes"][len(SEED_NODES):]}
        edges = [{**e, "properties": {"weight": 1}} if e["start_id"] in new else e for e in edges]
    elif tamper == "new-label":
        nodes = [{**n, "labels": n["labels"] + ["Government"]} if n["id"] == REG else n for n in nodes]
    _post(ran, nodes, edges)
    assert _check(ran, tmp_path)["verdict"] == "FAIL"


def test_another_loaders_stub_property_is_not_this_sources_change(ran, tmp_path):
    _post(ran, _with(ran, PLACE, source="another-loader"))
    assert _check(ran, tmp_path)["verdict"] == "PASS"


def test_check_loaded_refuses_inputs_it_cannot_bind_to_the_run(ran, tmp_path):
    _post(ran)
    run = ran["root"] / "data/ingest-runs" / ran["run_id"]
    state = json.loads((run / "state.json").read_text())
    state["backup_sha256"]["nodes.jsonl"] = "0" * 64
    (run / "state.json").write_text(json.dumps(state))
    with pytest.raises(cr.CheckRefused, match="backup"):
        _check(ran, tmp_path)


@pytest.mark.parametrize("later_state", [{"history": [{"status": "load_failed"}]},
                                         {"history": [{"status": "awaiting_load_approval"}], "backup": "x"}])
def test_check_loaded_refuses_when_a_later_run_attempted_a_load(ran, tmp_path, later_state):
    _post(ran)
    later = ran["root"] / "data/ingest-runs" / "2999-01-01T000000Z"
    later.mkdir()
    (later / "state.json").write_text(json.dumps({"run_id": later.name, **later_state}))
    with pytest.raises(cr.CheckRefused, match="after"):
        _check(ran, tmp_path)


# --- the independent Record oracle refuses what the resolver must hold ----------------------------------------


def _oracle(meetings, extra_nodes=(), extra_edges=()):
    nodes = {n["id"]: n for n in [*SEED_NODES, *extra_nodes]}
    capture = {"meetings": meetings, "record_refs": []}
    return cr.expected_records(capture, nodes, [*SEED_EDGES, *extra_edges], SID, INST)


def _cm(mid, **urls):
    return {"meeting_id": mid, "artifacts": {k: {"available": True, "url": u} for k, u in urls.items()}}


def test_the_oracle_refuses_to_reuse_a_record_of_another_kind():
    new = f"meeting-{SID}-city-council-x"
    assert _oracle([_cm(new, agenda=PDF.format("minutes-2020-03-02"))])["holds"]


def test_the_oracle_refuses_one_url_on_two_artifacts_of_a_meeting():
    new = f"meeting-{SID}-city-council-x"
    assert _oracle([_cm(new, agenda=PDF.format("same"), packet=PDF.format("same"))])["holds"]


def test_the_oracle_refuses_a_new_url_shared_across_kinds():
    assert _oracle([_cm(f"meeting-{SID}-a", agenda=PDF.format("same")),
                    _cm(f"meeting-{SID}-b", packet=PDF.format("same"))])["holds"]


def test_check_loaded_refuses_a_post_export_older_than_the_load(ran, tmp_path):
    _post(ran)
    for f in ("nodes.jsonl", "edges.jsonl"):
        os.utime(ran["post"] / f, (0, 0))
    with pytest.raises(cr.CheckRefused, match="predates"):
        _check(ran, tmp_path)


# --- check-loaded writes only where it is told ----------------------------------------------------------------


def _main_check(ran, post, out):
    return cr.main(["check-loaded", ran["run_id"], "--source", SID, "--post-export", str(post),
                    "--root", str(ran["root"]), *(["--out", str(out)] if out is not None else [])])


def test_relative_out_and_post_export_resolve_from_the_callers_directory(ran, tmp_path, monkeypatch):
    _post(ran)
    monkeypatch.chdir(tmp_path)
    assert _main_check(ran, os.path.relpath(ran["post"], tmp_path), "staging/out") == 0
    results = json.loads((tmp_path / "staging/out/check-loaded.json").read_text())
    assert results["verdict"] == "PASS" and (tmp_path / "staging/out" / f"expected-graph-{ran['run_id']}").is_dir()


def test_out_is_required(ran, tmp_path):
    _post(ran)
    with pytest.raises(SystemExit) as exc:
        _main_check(ran, ran["post"], None)
    assert exc.value.code == 2
    assert not (ran["post"] / "check-loaded").exists()


def test_out_inside_the_repos_data_is_refused(ran, tmp_path):
    _post(ran)
    inside = ran["root"] / "data/ingest-runs" / ran["run_id"] / "check"
    with pytest.raises(cr.CheckRefused, match="data/"):
        cr.check_loaded(ran["root"], ran["run_id"], SID, ran["post"], inside)
    assert not inside.exists()


def test_an_existing_expected_graph_is_refused_and_left_alone(ran, tmp_path):
    _post(ran)
    graph = tmp_path / "out" / f"expected-graph-{ran['run_id']}"
    graph.mkdir(parents=True)
    (graph / "keep.txt").write_text("someone else's")
    with pytest.raises(cr.CheckRefused, match="already exists"):
        _check(ran, tmp_path)
    assert (graph / "keep.txt").read_text() == "someone else's"


LATER = "2026-01-12T120000Z"  # a later run that loaded; the fixture's run is 2026-01-05T120000Z


def _later_loaded(ran, run_id=LATER):
    later = ran["root"] / "data/ingest-runs" / run_id
    later.mkdir(parents=True)
    (later / "state.json").write_text(json.dumps({"run_id": run_id, "history": [{"status": "loaded"}]}))


def _pinned_pre(ran, run_id=None, taken="2026-01-05T13:00:00+00:00", marker=True):
    pre = ran["root"] / "data/ingest-runs" / (run_id or ran["run_id"]) / "agenda-items/pre"
    pre.mkdir(parents=True, exist_ok=True)  # the rehearsal's run may have taken one (fixture tmp only)
    for f in ("complete.json", "nodes.jsonl", "edges.jsonl"):  # its stand-in exports are symlinks to the seed
        (pre / f).unlink(missing_ok=True)
    (pre / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in ran["nodes"]))
    (pre / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ran["edges"]))
    if marker:
        (pre / "complete.json").write_text(json.dumps({f: hashlib.sha256((pre / f).read_bytes()).hexdigest()
                                                       for f in ("edges.jsonl", "nodes.jsonl")}))
    when = datetime.fromisoformat(taken).timestamp()
    for f in ("nodes.jsonl", "edges.jsonl"):
        os.utime(pre / f, (when, when))
    return pre


def test_the_runs_own_pinned_pre_export_is_checked_after_a_later_load(ran, tmp_path):
    pre = _pinned_pre(ran)
    _later_loaded(ran)
    assert cr.check_loaded(ran["root"], ran["run_id"], SID, pre, tmp_path / "out")["verdict"] == "PASS"


def test_another_runs_pinned_pre_export_is_not_this_runs(ran, tmp_path):
    other = _pinned_pre(ran, run_id="2026-01-04T120000Z")
    _later_loaded(ran)
    with pytest.raises(cr.CheckRefused, match="after"):
        cr.check_loaded(ran["root"], ran["run_id"], SID, other, tmp_path / "out")


@pytest.mark.parametrize("problem", ["no-marker", "changed-bytes", "bad-marker"])
def test_a_pinned_pre_export_that_does_not_match_its_marker_is_not_bound(ran, tmp_path, problem):
    pre = _pinned_pre(ran, marker=problem != "no-marker")
    if problem == "changed-bytes":
        with open(pre / "nodes.jsonl", "a") as fh:
            fh.write(json.dumps({"id": "x", "labels": ["Record"], "properties": {}}) + "\n")
        when = datetime.fromisoformat("2026-01-05T13:00:00+00:00").timestamp()
        os.utime(pre / "nodes.jsonl", (when, when))
    if problem == "bad-marker":
        (pre / "complete.json").write_text("not json")
    _later_loaded(ran)
    with pytest.raises(cr.CheckRefused, match="after"):
        cr.check_loaded(ran["root"], ran["run_id"], SID, pre, tmp_path / "out")


def test_a_pre_export_taken_after_the_later_run_started_is_not_bound(ran, tmp_path):
    # A interrupted before its pre-export, B staged and loaded, A resumed: A's "pre" shows B's graph.
    pre = _pinned_pre(ran, taken="2026-01-12T13:00:00+00:00")
    _later_loaded(ran)
    with pytest.raises(cr.CheckRefused, match="after"):
        cr.check_loaded(ran["root"], ran["run_id"], SID, pre, tmp_path / "out")


@pytest.mark.parametrize("via", ["through-the-data-symlink", "at-the-symlinks-target", "beside-it-in-that-repo"])
def test_out_in_a_data_layer_reached_through_a_symlink_is_refused(ran, tmp_path, via):
    _post(ran)
    private = tmp_path / "private-data-repo" / "layer"
    private.mkdir(parents=True)
    (ran["root"] / "data" / "layer").symlink_to(private, target_is_directory=True)  # as data/normalized is
    out = {"through-the-data-symlink": ran["root"] / "data/layer/check", "at-the-symlinks-target": private / "check",
           "beside-it-in-that-repo": private.parent / "review-output"}[via]  # the private repo, not just its layers
    with pytest.raises(cr.CheckRefused, match="data"):
        cr.check_loaded(ran["root"], ran["run_id"], SID, ran["post"], out)
    assert sorted(p.name for p in private.parent.iterdir()) == ["layer"] and list(private.iterdir()) == []


@pytest.mark.parametrize("name", ["check-loaded.json", "check-loaded.md"])
def test_an_existing_report_in_out_is_refused_before_anything_is_written(ran, tmp_path, name):
    _post(ran)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    out = tmp_path / "out"
    out.mkdir()
    (out / name).symlink_to(victim)
    assert _main_check(ran, ran["post"], out) == 2
    assert victim.read_text() == "keep" and not (out / f"expected-graph-{ran['run_id']}").exists()


@pytest.mark.parametrize("redirect", ["pre-dir", "export-file"])
def test_a_redirected_pinned_pre_export_is_not_bound(ran, tmp_path, redirect):
    pre = _pinned_pre(ran)
    elsewhere = tmp_path / "elsewhere"
    if redirect == "pre-dir":  # the run's pre is a link to some other (internally consistent) export
        pre.rename(elsewhere)
        pre.symlink_to(elsewhere, target_is_directory=True)
    else:
        elsewhere.mkdir()
        (pre / "nodes.jsonl").rename(elsewhere / "nodes.jsonl")
        (pre / "nodes.jsonl").symlink_to(elsewhere / "nodes.jsonl")
    _later_loaded(ran)
    with pytest.raises(cr.CheckRefused, match="after"):
        cr.check_loaded(ran["root"], ran["run_id"], SID, pre, tmp_path / "out")


@pytest.mark.parametrize("pinned", ["0" * 64, None], ids=["pinned-another-version", "pinned-none-but-a-list-now"])
def test_check_loaded_refuses_when_the_alias_list_is_not_the_one_the_run_pinned(ran, tmp_path, pinned):
    import record_url_aliases as rua

    _post(ran)
    path = ran["root"] / rua.PATH
    path.write_text(yaml.safe_dump({"format": 1, "sources": {SID: [{
        "record_id": "record-x", "art": "minutes", "established_url": PDF.format("a"), "page_url": PDF.format("b"),
        "evidence": {"kind": "identical_bytes", "sha256": "1" * 64}, "reviewed": "2026-11-12"}]}}))
    run = ran["root"] / "data/ingest-runs" / ran["run_id"]
    state = json.loads((run / "state.json").read_text())
    capture = ran["root"] / state["sources"][SID]["capture"]["path"]
    if pinned:
        state["sources"][SID]["record_url_aliases_sha256"] = pinned
        (run / "state.json").write_text(json.dumps(state))
    else:  # the run pinned nothing, its capture has no binding: the planner simply ignores the list
        _check(ran, tmp_path)
        return
    with pytest.raises(cr.CheckRefused, match="alias list"):
        _check(ran, tmp_path)
    assert capture.is_file()
