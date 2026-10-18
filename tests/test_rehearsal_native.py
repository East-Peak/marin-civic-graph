"""The rehearsal and check-loaded for a native-only source (scripts/crosswalk_rehearsal.py), on a fictional city.

The real weekly chain (refresh_weekly.stage -> ingest.py -> the Archive Center adapter -> the robots gate with
its host allowlist; refresh_weekly.load -> normalize_meetings.py --load -> the guarded load) on a fake graph,
every response pre-recorded. Expected Meetings and Records come from the caller (in production: the reviewed
inventory), not from the code under test. The seed has neither stub, so the first load creates both, once.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import crosswalk_rehearsal as cr  # noqa: E402
import guarded_load as gl  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "civicplus-archive-lakeport.html"
SID = "lakeport-city-council"
INST = "org-lakeport-city-council"
PLACE = "place-lakeport"
SITE = "https://www.lakeport.example"
NOW = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)  # in the past: a post-export is always taken after it
# The fixture's 24 meetings, by hand: (ADID key, artifact), the two-date notice once (it is one Record).
MEETINGS = ["9537", "9533", "9517", "9494", "9459", "9458", "9441", "9440", "9249", "9248", "9208", "9151", "9141",
            "9143", "9138-2023-12-06", "9138-2023-12-20", "9133", "9129", "9128", "9006", "8411", "8412", "8315",
            "8213"]
NOTICES = {"9517", "9494", "9249", "9138-2023-12-06", "9138-2023-12-20"}


def _expected():
    meetings = [f"meeting-{SID}-adid-{k}" for k in MEETINGS]
    records = [f"record-{SID}-{SID}-adid-{k}-{'notice' if k in NOTICES else 'agenda'}" for k in MEETINGS
               if k != "9138-2023-12-20"]
    return {"meetings": sorted(meetings), "records": sorted(records), "stubs": sorted([INST, PLACE])}


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "repo"
    (repo / "registry").mkdir(parents=True)
    (repo / "scripts").symlink_to(REPO / "scripts", target_is_directory=True)
    config = {"id": SID, "adapter": "civicplus_archive", "url": f"{SITE}/Archive.aspx?AMID=49",
              "allowed_hosts": ["www.lakeport.example"], "archive_title": "City Council Agendas",
              "jurisdiction_id": PLACE, "institution_id": INST, "backfill_from": "2019-01-01", "schedule": "manual",
              "identity": "native-only", "create_missing_stubs": True,
              "floors": {"max_newest_age_days": None, "min_rows": 24}}
    other = {"id": "harbor-town-council", "adapter": "civicplus", "url": "https://harbor.example/AgendaCenter",
             "jurisdiction_id": "place-harbor", "institution_id": "org-harbor", "schedule": "weekly"}
    (repo / "registry" / "civicplus-sources.yaml").write_text(yaml.safe_dump({"sources": [other, config]}))
    export = tmp_path / "export"
    export.mkdir()
    (export / "nodes.jsonl").write_text(json.dumps({"id": "place-harbor", "labels": ["Place"],
                                                    "properties": {"id": "place-harbor"}}) + "\n")
    (export / "edges.jsonl").write_text("")
    store = cr.ResponseStore(tmp_path / "responses")
    store.put(f"{SITE}/robots.txt", status=200, headers={}, body=b"User-agent: *\nDisallow: /admin\n", error=None)
    store.put(f"{SITE}/Archive.aspx?AMID=49", status=200, headers={}, body=FIXTURE.read_bytes(), error=None)
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps(_expected()))
    return {"repo": repo, "export": export, "responses": store.path, "work": tmp_path / "staging" / "rehearsal",
            "expected": expected}


def _rehearse(world):
    return cr.rehearse(SID, world["export"], world["work"], repo=world["repo"], responses=world["responses"],
                       now=NOW, expected=world["expected"])


def test_the_rehearsal_passes_every_check(world):
    results = _rehearse(world)
    assert [c for c in results["checks"] if not c["ok"]] == []
    assert {c["check"].split(":")[0] for c in results["checks"]} >= set(cr.VARIANTS)
    assert results["counts"]["new_meetings"] == 24
    assert results["counts"]["new_records"] == 23 + 1
    assert results["counts"]["new_stubs"] == [INST, PLACE]
    assert results["crosswalk_sha256"] is None and results["identity"] == "native-only"
    assert "**Rehearsal: PASS**" in cr.render_rehearsal(results)


def test_only_the_source_is_scheduled_and_only_its_registry_is_staged(world):
    _rehearse(world)
    registry = yaml.safe_load((world["work"] / "empty-cache" / "registry" / "civicplus-sources.yaml").read_text())
    assert {s["id"]: s["schedule"] for s in registry["sources"]} == {"harbor-town-council": "manual", SID: "weekly"}


def test_a_wrong_expectation_fails_the_rehearsal(world):
    expected = _expected()
    expected["meetings"] = expected["meetings"][1:]
    world["expected"].write_text(json.dumps(expected))
    results = _rehearse(world)
    assert any(not c["ok"] and "new Meetings" in c["check"] for c in results["checks"])


def test_a_native_rehearsal_needs_its_expectation(world):
    with pytest.raises(ValueError, match="expected"):
        cr.rehearse(SID, world["export"], world["work"], repo=world["repo"], responses=world["responses"], now=NOW)


# --- check-loaded on the rehearsal's own first run ---------------------------------------------------------


@pytest.fixture
def ran(world, tmp_path):
    assert all(c["ok"] for c in _rehearse(world)["checks"])
    root = world["work"] / "empty-cache"
    run_id = json.loads(next((root / "data/ingest-runs").glob("*/state.json")).read_text())["run_id"]
    nodes, edges = gl.FakeGraphPort(world["work"] / "graph-populated-cache").overlay()
    post = tmp_path / "post-export"
    post.mkdir()
    seed = [json.loads(line) for line in (world["export"] / "nodes.jsonl").read_text().splitlines()]
    return {"root": root, "run_id": run_id, "post": post, "nodes": seed + nodes, "edges": edges}


def _post(ran, nodes=None, edges=None):
    (ran["post"] / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes or ran["nodes"]))
    (ran["post"] / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges or ran["edges"]))


def test_check_loaded_passes_on_exactly_the_planned_writes_stubs_included(ran, tmp_path):
    _post(ran)
    results = cr.check_loaded(ran["root"], ran["run_id"], SID, ran["post"], tmp_path / "out")
    assert [c for c in results["checks"] if not c["ok"]] == [] and results["verdict"] == "PASS"


@pytest.mark.parametrize("tamper", ["stub-missing", "stub-property", "extra-meeting"])
def test_check_loaded_fails_on_a_stub_or_meeting_it_did_not_plan(ran, tmp_path, tamper):
    nodes = ran["nodes"]
    if tamper == "stub-missing":
        nodes = [n for n in nodes if n["id"] != PLACE]
        ran["edges"] = [e for e in ran["edges"] if PLACE not in (e["start_id"], e["end_id"])]
    elif tamper == "stub-property":
        nodes = [{**n, "properties": {**n["properties"], "name": "Elsewhere"}} if n["id"] == INST else n for n in nodes]
    else:
        nodes = nodes + [{"id": f"meeting-{SID}-adid-1", "labels": ["Meeting"],
                          "properties": {"id": f"meeting-{SID}-adid-1", "institution_id": INST}}]
    _post(ran, nodes)
    assert cr.check_loaded(ran["root"], ran["run_id"], SID, ran["post"], tmp_path / "out")["verdict"] == "FAIL"


def test_check_loaded_refuses_a_registry_policy_that_changed_since_the_run(ran, tmp_path):
    _post(ran)
    registry = ran["root"] / "registry" / "civicplus-sources.yaml"
    registry.write_text(registry.read_text().replace("create_missing_stubs: true", "create_missing_stubs: false"))
    with pytest.raises(cr.CheckRefused, match="policy"):
        cr.check_loaded(ran["root"], ran["run_id"], SID, ran["post"], tmp_path / "out")
