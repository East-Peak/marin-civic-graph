"""The agenda stage's complete delta (scripts/agenda_delta.py): two full exports taken immediately before and
after the stage must differ by exactly the committed AgendaItems and their two edges each — nothing changed,
removed or added elsewhere. The same comparison serves the rehearsal and check-loaded. Fictional data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agenda_delta as ad  # noqa: E402

M, R = "meeting-lakeport-1", "record-lakeport-1-agenda"
ITEM = {"id": "agenda-item-lakeport-1-4a", "labels": ["AgendaItem"],
        "properties": {"id": "agenda-item-lakeport-1-4a", "title": "Approve", "meeting_id": M}}
BASE_NODES = [{"id": M, "labels": ["Meeting"], "properties": {"id": M, "title": "Council"}},
              {"id": R, "labels": ["Record"], "properties": {"id": R, "source_url": "u"}}]
BASE_EDGES = [{"start_id": M, "type": "EVIDENCED_BY", "end_id": R, "properties": {}}]
NEW_EDGES = [{"start_id": ITEM["id"], "type": "PART_OF_MEETING", "end_id": M, "properties": {}},
             {"start_id": ITEM["id"], "type": "EVIDENCED_BY", "end_id": R, "properties": {}}]


def _export(path: Path, nodes, edges) -> Path:
    path.mkdir(parents=True)
    (path / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    (path / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges))
    return path


def _bundle(path: Path) -> Path:
    path.mkdir()
    (path / "nodes.jsonl").write_text(json.dumps(ITEM) + "\n")
    (path / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in NEW_EDGES))
    return path


def _run(tmp_path, post_nodes, post_edges, committed=(M,)):
    pre = _export(tmp_path / "pre", BASE_NODES, BASE_EDGES)
    post = _export(tmp_path / "post", post_nodes, post_edges)
    return ad.compare(pre, post, _bundle(tmp_path / "bundle"), committed=list(committed))


def test_exactly_the_committed_items_is_ok(tmp_path):
    result = _run(tmp_path, BASE_NODES + [ITEM], BASE_EDGES + NEW_EDGES)
    assert result["ok"] is True and result["added_nodes"] == 1 and result["added_edges"] == 2
    assert result["problems"] == []


@pytest.mark.parametrize("post_nodes, post_edges, problem", [
    (BASE_NODES, BASE_EDGES, "missing"),  # committed but absent
    (BASE_NODES + [ITEM, {"id": "x", "labels": ["Decision"], "properties": {"id": "x"}}], BASE_EDGES + NEW_EDGES,
     "unexpected node"),
    ([{**BASE_NODES[0], "properties": {"id": M, "title": "Renamed"}}, BASE_NODES[1], ITEM], BASE_EDGES + NEW_EDGES,
     "changed node"),
    ([BASE_NODES[0], ITEM], NEW_EDGES[:1], "removed node"),
    (BASE_NODES + [ITEM], NEW_EDGES, "removed edge"),
    (BASE_NODES + [ITEM], BASE_EDGES + NEW_EDGES + NEW_EDGES[:1], "unexpected edge"),
    (BASE_NODES + [{**ITEM, "properties": {**ITEM["properties"], "title": "Other"}}], BASE_EDGES + NEW_EDGES,
     "differs from the bundle"),
])
def test_anything_else_is_a_problem(tmp_path, post_nodes, post_edges, problem):
    result = _run(tmp_path, post_nodes, post_edges)
    assert result["ok"] is False and any(problem in p for p in result["problems"])


def test_a_held_meeting_gains_nothing(tmp_path):
    result = _run(tmp_path, BASE_NODES + [ITEM], BASE_EDGES + NEW_EDGES, committed=())
    assert result["ok"] is False and any("unexpected node" in p for p in result["problems"])


def test_the_cli_writes_its_verdict(tmp_path):
    pre = _export(tmp_path / "pre", BASE_NODES, BASE_EDGES)
    post = _export(tmp_path / "post", BASE_NODES + [ITEM], BASE_EDGES + NEW_EDGES)
    bundle = _bundle(tmp_path / "bundle")
    (tmp_path / "report.json").write_text(json.dumps({"load": {"created": {"meetings": {M: [ITEM["id"]]}}}}))
    out = tmp_path / "delta.json"
    code = ad.main(["--pre", str(pre), "--post", str(post), "--bundle", str(bundle),
                    "--stage-report", str(tmp_path / "report.json"), "--out", str(out)])
    assert code == 0 and json.loads(out.read_text())["ok"] is True
