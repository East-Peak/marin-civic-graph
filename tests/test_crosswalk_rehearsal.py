"""The crosswalk rehearsal and check-loaded (scripts/crosswalk_rehearsal.py), on a fictional city.

The rehearsal runs the real weekly chain (refresh_weekly.stage -> ingest.py -> the ProudCity adapter ->
the robots gate; refresh_weekly.load -> normalize_meetings.py --load) against a fake graph. Here every
response is pre-recorded (a fictional Lakeport site), so all four runs replay and nothing reaches the
network. check-loaded is then pointed at the rehearsal's own first run, with a post-export built from
its seed and its writes, then tampered with.
"""
from __future__ import annotations

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
