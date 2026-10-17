"""normalize_meetings.py --load for a crosswalk-required source goes through the no-overwrite load.

The capture decides as much as the registry: a capture made under a crosswalk never reaches the ordinary
MERGE loader. Everything resolves under --root (the weekly run's), the report lands where --report says,
and a hold is a successful exit with outcome `held` (the weekly run reads it). Fictional fixtures; the
graph is a fake one in tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import crosswalk as cw  # noqa: E402
import guarded_load as gl  # noqa: E402
import normalize_meetings as nm  # noqa: E402
from tests.test_guarded_load import (  # noqa: E402
    CONFIG, INST, PDF, PLACE, SEED_EDGES, SEED_NODES, SID, XW_REL, _capture, _m)

PLAIN = {"id": "harbor-town-council", "adapter": "proudcity", "url": "https://harbor.example/meetings/",
         "institution_id": "org-harbor-town-council", "jurisdiction_id": "place-harbor", "schedule": "weekly"}


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "root"
    (root / "registry").mkdir(parents=True)
    (root / "registry" / "proudcity-sources.yaml").write_text(json.dumps({"sources": [
        {**CONFIG, "url": "https://www.lakeport.example/city-council-meetings/", "schedule": "manual"}, PLAIN]}))
    xw = root / XW_REL
    xw.parent.mkdir(parents=True)
    xw.write_text(json.dumps({"format": 1, "source_id": SID, "entries": {
        "city-council-march-2-2020": "meeting-2020-03-02-lakeport-city-council"}}))
    return root


@pytest.fixture
def graph(tmp_path, monkeypatch):
    export = tmp_path / "export"
    export.mkdir()
    (export / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in SEED_NODES))
    (export / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in SEED_EDGES))
    path = gl.FakeGraphPort.create(tmp_path / "graph", seed=export)
    monkeypatch.setenv("NEO4J_URI", f"fakegraph://{path}")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "unused")
    return path


def _write_capture(root, capture, sid=SID):
    path = root / "data" / "extracted" / sid / "2026-10-19.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(capture))
    return path


def _main(root, capture_path, *extra, sid=SID):
    return nm.main(["--source", sid, "--capture", str(capture_path), "--root", str(root), *extra])


def test_a_crosswalk_source_loads_through_the_guarded_path_under_root(root, graph, tmp_path):
    capture = _write_capture(root, _capture(root, [_m("city-council-may-4-2026", "2026-05-04",
                                                      agenda=PDF.format("a"))]))
    report_path = tmp_path / "run" / "load-reports" / f"{SID}.json"
    assert _main(root, capture, "--load", "--report", str(report_path)) == 0
    out = root / "data" / "normalized" / f"{SID}-meetings"
    report = json.loads(report_path.read_text())
    assert report == json.loads((out / "load-report.json").read_text())
    assert report["outcome"] == "loaded" and report["source_id"] == SID
    assert report["capture_sha256"] == cw.sha256_file(capture)
    assert (out / "nodes.jsonl").is_file() and (out / "edges.jsonl").is_file()
    nodes, _ = gl.FakeGraphPort(graph).overlay()
    assert cw.adapter_id(SID, "city-council-may-4-2026") in {n["id"] for n in nodes}
    assert not (REPO / "data" / "normalized" / f"{SID}-meetings").exists()


def test_a_hold_is_a_successful_exit_with_a_held_report(root, graph, tmp_path):
    capture = _write_capture(root, _capture(root, [_m("city-council-march-2-2020", "2020-03-02",
                                                      minutes=PDF.format("minutes-changed"))]))
    report_path = tmp_path / "held.json"
    assert _main(root, capture, "--load", "--report", str(report_path)) == 0
    report = json.loads(report_path.read_text())
    assert report["outcome"] == "held" and report["holds"][0]["reason"] == "artifact_url_changed"
    assert gl.FakeGraphPort(graph).overlay() == ([], [])


def test_a_crosswalk_capture_never_reaches_the_ordinary_loader(root, graph, tmp_path, monkeypatch):
    registry = root / "registry" / "proudcity-sources.yaml"
    sources = json.loads(registry.read_text())["sources"]
    capture = _write_capture(root, _capture(root, [_m("city-council-may-4-2026", "2026-05-04")]))
    sources[0] = {k: v for k, v in sources[0].items() if k not in ("identity", "crosswalk")}  # removed after staging
    registry.write_text(json.dumps({"sources": sources}))
    import load_neo4j_v2
    monkeypatch.setattr(load_neo4j_v2, "load_nodes", lambda *a, **k: pytest.fail("ordinary loader reached"))
    report_path = tmp_path / "r.json"
    assert _main(root, capture, "--load", "--report", str(report_path)) == 0
    assert json.loads(report_path.read_text())["holds"][0]["reason"] == "policy_mismatch"


def test_a_crosswalk_source_needs_load_and_a_graph(root, graph, monkeypatch):
    capture = _write_capture(root, _capture(root, [_m("city-council-may-4-2026", "2026-05-04")]))
    assert _main(root, capture) == 2  # no --load: there is no graph to resolve Record ids against
    monkeypatch.delenv("NEO4J_URI")
    assert _main(root, capture, "--load") == 2
    assert gl.FakeGraphPort(graph).overlay() == ([], [])


def test_other_sources_normalize_as_before_but_under_root(root):
    capture = {"capture_id": "harbor-2026-10-19", "source_id": PLAIN["id"], "adapter": "proudcity",
               "captured_at": "2026-10-19T12:00:00Z", "jurisdiction_id": PLAIN["jurisdiction_id"],
               "institution_id": PLAIN["institution_id"], "meeting_count": 1, "record_refs": [],
               "meetings": [{"meeting_id": "meeting-harbor-town-council-x", "date": "2026-10-05",
                             "title": "Town Council", "artifacts": {}}]}
    path = _write_capture(root, capture, sid=PLAIN["id"])
    assert _main(root, path, sid=PLAIN["id"]) == 0
    out = root / "data" / "normalized" / f"{PLAIN['id']}-meetings"
    expected, _ = nm.normalize_rows(capture)
    assert [json.loads(line) for line in (out / "nodes.jsonl").read_text().splitlines()] == expected


def test_default_record_ids_are_one_function_for_nodes_and_edges():
    capture = {"capture_id": "c", "source_id": "harbor-town-council", "captured_at": "2026-10-19T12:00:00Z",
               "institution_id": INST, "jurisdiction_id": PLACE, "record_refs": [],
               "meetings": [{"meeting_id": "meeting-harbor-town-council-x", "date": "2026-10-05", "title": "T",
                             "artifacts": {"minutes": {"available": True, "url": "u"}}}]}
    nodes, edges = nm.normalize_rows(capture)
    record = "record-harbor-town-council-harbor-town-council-x-minutes"
    assert record in {n["id"] for n in nodes}
    assert record in {e["target_id"] for e in edges if e["relationship_type"] == "EVIDENCED_BY"}
    custom, custom_edges = nm.normalize_rows(capture, record_id=lambda m, art: f"rec-{art}")
    assert "rec-minutes" in {n["id"] for n in custom} and "rec-minutes" in {e["target_id"] for e in custom_edges}


def test_a_standalone_guarded_load_waits_for_no_one_holding_the_run_lock(root, graph):
    from run_lock import run_lock
    capture = _write_capture(root, _capture(root, [_m("city-council-may-4-2026", "2026-05-04")]))
    with run_lock(root):
        import subprocess
        result = subprocess.run([sys.executable, str(REPO / "scripts" / "normalize_meetings.py"), "--source", SID,
                                 "--capture", str(capture), "--root", str(root), "--load"],
                                capture_output=True, text=True,
                                env={k: v for k, v in __import__("os").environ.items()
                                     if k != "OPEN_MARIN_RUN_LOCK_OWNER"})
    assert result.returncode == 2 and "holds" in result.stderr
    assert gl.FakeGraphPort(graph).overlay() == ([], [])
