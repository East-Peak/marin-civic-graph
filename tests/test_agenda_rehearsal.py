"""The agenda rehearsal's own pieces (scripts/agenda_rehearsal.py): the pruned seed, week 1's withheld listing
rows, qualification in the staging registry only, and check-loaded on a real run's pinned inputs. Fictional data."""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agenda_rehearsal as ar  # noqa: E402
from crosswalk_rehearsal import ResponseStore  # noqa: E402


def _write(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _n(i, label, **p):
    return {"id": i, "labels": [label], "properties": {"id": i, **p}}


def _e(s, t, e, **p):
    return {"start_id": s, "type": t, "end_id": e, "properties": p}


def test_the_seed_drops_withheld_meetings_and_the_records_only_they_hold(tmp_path):
    export = tmp_path / "export"
    _write(export / "nodes.jsonl", [_n("m1", "Meeting"), _n("m2", "Meeting"), _n("r1", "Record"),
                                    _n("r-shared", "Record"), _n("org", "Organization")])
    _write(export / "edges.jsonl", [_e("m1", "EVIDENCED_BY", "r1"), _e("m1", "EVIDENCED_BY", "r-shared"),
                                    _e("m2", "EVIDENCED_BY", "r-shared"), _e("m1", "AT_INSTITUTION", "org"),
                                    _e("m2", "AT_INSTITUTION", "org")])
    seed = ar.prune_seed(export, tmp_path / "seed", {"m1"})
    ids = {json.loads(x)["id"] for x in (seed / "nodes.jsonl").read_text().splitlines()}
    assert ids == {"m2", "r-shared", "org"}
    edges = [json.loads(x) for x in (seed / "edges.jsonl").read_text().splitlines()]
    assert all("m1" not in (e["start_id"], e["end_id"]) and e["end_id"] != "r1" for e in edges) and len(edges) == 2


def test_week_one_withholds_only_the_named_agenda_rows(tmp_path):
    store, week1 = ResponseStore(tmp_path / "store"), ResponseStore(tmp_path / "week1")
    html = ('<table><tr id="a" class="catAgendaRow"><a href="/ViewFile/Agenda/_10202026-1694">x</a></tr>'
            '<tr id="b" class="catAgendaRow"><a href="/ViewFile/Agenda/_10062026-1690">y</a></tr></table>')
    store.put("https://www.lakeport.example/AgendaCenter/UpdateCategoryList", b"year=2026", status=200, headers={},
              body=html.encode(), error=None)
    store.put("https://www.lakeport.example/robots.txt", status=404, headers={}, body=b"", error=None)
    changed = ar.withhold(store, week1, ["1694"])
    assert changed == ["https://www.lakeport.example/AgendaCenter/UpdateCategoryList"] and len(week1) == 1
    body = base64.b64decode(json.loads(next(week1.path.glob("*.json")).read_text())["body"]).decode()
    assert "_10202026-1694" not in body and "_10062026-1690" in body


def test_qualification_exists_only_in_the_rehearsals_staging_registry(tmp_path):
    root = ar._root(tmp_path, 4, frozenset({"ross-town-council"}))
    sources = {s["id"]: s for p in (root / "registry").glob("*-sources.yaml")
               for s in yaml.safe_load(p.read_text()).get("sources") or []}
    assert sources["ross-town-council"]["agenda_items"]["qualified"]["report"] == "rehearsal only"
    assert sources["ross-town-council"]["agenda_items"]["cap"] == 4
    assert "qualified" not in sources["fairfax-town-council"]["agenda_items"]
    repo = yaml.safe_load((REPO / "registry" / "drupal-sources.yaml").read_text())["sources"][0]
    assert "qualified" not in repo["agenda_items"]  # the repo's registry is untouched


def _run_dir(tmp_path, *, tamper=None):
    """A finished run with its pinned stage inputs, as refresh_weekly leaves it."""
    import refresh_weekly as rw

    root, run = tmp_path / "root", "2026-10-19T120000Z"
    work = root / "data/ingest-runs" / run / "agenda-items"
    base_nodes = [_n("m1", "Meeting"), _n("r1", "Record", source_url="u1"), _n("d1", "Decision", t="x")]
    base_edges = [_e("m1", "EVIDENCED_BY", "r1")]
    item = _n("agenda-item-x-1", "AgendaItem", meeting_id="m1", title="T")
    new_edges = [_e(item["id"], "PART_OF_MEETING", "m1"), _e(item["id"], "EVIDENCED_BY", "r1")]
    _write(work / "pre/nodes.jsonl", base_nodes)
    _write(work / "pre/edges.jsonl", base_edges)
    _write(work / "post/nodes.jsonl", base_nodes + [item])
    _write(work / "post/edges.jsonl", base_edges + new_edges)
    _write(work / "bundle/nodes.jsonl", [item])
    _write(work / "bundle/edges.jsonl", new_edges)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    (work / "bundle/manifest.json").write_text(json.dumps({"files": {f: sha(work / "bundle" / f) for f in
                                                                     ("nodes.jsonl", "edges.jsonl")},
                                                           "meetings": [{"meeting_id": "m1", "url": "u1",
                                                                         "sha256": "s1", "item_ids": [item["id"]]}]}))
    (work / "report.json").write_text(json.dumps({"run_id": run, "load": {"created": {"meetings": {"m1": [item["id"]]}}}}))
    (root / "data/ingest-runs/agenda-items-ledger.json").write_text(json.dumps(
        {"version": 1, "meetings": {"m1": {"state": "loaded", "url": "u1", "sha256": "s1"}}}))
    _write(root / "data/exports/backups/pre-load/nodes.jsonl", base_nodes)
    if tamper:
        tamper(work, root)
    state = {"run_id": run, "status": "awaiting_publish_approval", "history": [], "sources": {},
             "backup": "data/exports/backups/pre-load",
             "agenda_items": {"ok": True, "exports_sha256": {f"{s}/{f}": sha(work / s / f) for s in ("pre", "post")
                                                             for f in ("nodes.jsonl", "edges.jsonl")}}}
    (work.parent / "state.json").write_text(json.dumps(state))
    return root, run, rw


def test_check_loaded_passes_a_run_that_wrote_exactly_its_bundle(tmp_path):
    root, run, _ = _run_dir(tmp_path)
    result = ar.check_loaded(root, run)
    assert result["verdict"] == "PASS", result["checks"]


@pytest.mark.parametrize("tamper, failing", [
    (lambda w, r: _write(w / "post/nodes.jsonl", [_n("m1", "Meeting"), _n("r1", "Record", source_url="u1"),
                                                  _n("d1", "Decision", t="changed"),
                                                  _n("agenda-item-x-1", "AgendaItem", meeting_id="m1", title="T")]),
     "stage delta"),
    (lambda w, r: (r / "data/ingest-runs/agenda-items-ledger.json").write_text(json.dumps(
        {"version": 1, "meetings": {"m1": {"state": "loaded", "url": "u1", "sha256": "other"}}})), "ledger"),
])
def test_check_loaded_fails_what_is_not_exact(tmp_path, tamper, failing):
    root, run, _ = _run_dir(tmp_path, tamper=tamper)
    result = ar.check_loaded(root, run)
    assert result["verdict"] == "FAIL" and any(failing in c["check"] and not c["ok"] for c in result["checks"])


def test_check_loaded_refuses_exports_changed_after_the_run(tmp_path):
    root, run, rw = _run_dir(tmp_path)
    with open(rw.run_dir(root, run) / "agenda-items/post/nodes.jsonl", "a") as fh:
        fh.write(json.dumps(_n("late", "Meeting")) + "\n")
    result = ar.check_loaded(root, run)
    assert not result["checks"][0]["ok"] and result["verdict"] == "FAIL"
