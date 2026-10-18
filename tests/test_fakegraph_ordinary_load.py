"""The ordinary meeting load on a fake graph (rehearsals): every loader path stays off the real graph.

normalize_meetings' ordinary `--load` (load_neo4j_v2's MERGE + SET +=) writes to `fakegraph:///<dir>` as overlay
MERGE rows with the same semantics, and never opens a driver; any other unsafe target still refuses. Fictional
fixtures (Lakeport).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import guarded_load as gl  # noqa: E402
import normalize_meetings as nm  # noqa: E402

SID = "lakeport-planning"
INST = "org-lakeport-planning"


def _seed(tmp_path, nodes, edges=()):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    (seed / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges))
    return gl.FakeGraphPort(gl.FakeGraphPort.create(tmp_path / "graph", seed=seed))


def test_merge_creates_updates_and_removes_like_set_plus_equals(tmp_path):
    port = _seed(tmp_path, [{"id": "m1", "labels": ["Meeting"], "properties": {"id": "m1", "title": "Old",
                                                                             "keep": 1, "drop": 2}},
                            {"id": "r1", "labels": ["Record"], "properties": {"id": "r1"}}],
                 [{"start_id": "m1", "type": "EVIDENCED_BY", "end_id": "r1", "properties": {"a": 1}}])
    port.merge([{"id": "m1", "labels": ["Meeting", "Event"], "node_type": "Meeting", "display_label": "New",
                 "promotion_state": "promoted", "properties": {"title": "New", "drop": None, "payload_json": "{}"}},
                {"id": "m2", "labels": ["Meeting"], "node_type": "Meeting", "display_label": "Two",
                 "promotion_state": "", "properties": {"title": "Two"}}],
               [{"source_id": "m1", "relationship_type": "EVIDENCED_BY", "target_id": "r1", "properties": {"b": 2}},
                {"source_id": "m2", "relationship_type": "EVIDENCED_BY", "target_id": "r1", "properties": {}},
                {"source_id": "m2", "relationship_type": "AT_INSTITUTION", "target_id": "absent", "properties": {}}])
    with gl.FakeGraphPort(port.path).transaction(()) as tx:
        nodes = tx.nodes(["m1", "m2"])
        assert nodes["m1"]["labels"] == ["Meeting", "Event"]
        assert nodes["m1"]["props"] == {"id": "m1", "title": "New", "keep": 1, "display_label": "New",
                                        "promotion_state": "promoted"}
        assert nodes["m2"]["props"]["title"] == "Two"
        assert tx.existing_edges([("m1", "EVIDENCED_BY", "r1"), ("m2", "EVIDENCED_BY", "r1"),
                                  ("m2", "AT_INSTITUTION", "absent")]) == {("m1", "EVIDENCED_BY", "r1"),
                                                                          ("m2", "EVIDENCED_BY", "r1")}
    assert port.overlay() == ([], [])  # MERGE rows are not creates


def _root(tmp_path):
    root = tmp_path / "root"
    (root / "registry").mkdir(parents=True)
    (root / "registry" / "civicplus-sources.yaml").write_text(yaml.safe_dump({"sources": [
        {"id": SID, "adapter": "civicplus", "url": "https://www.lakeport.example/AgendaCenter",
         "institution_id": INST, "jurisdiction_id": "place-lakeport", "schedule": "weekly"}]}))
    capture = {"capture_id": f"{SID}__2026-10-18", "source_id": SID, "adapter": "civicplus",
               "captured_at": "2026-10-18T12:00:00Z", "url": "https://www.lakeport.example/AgendaCenter",
               "institution_id": INST, "jurisdiction_id": "place-lakeport", "meeting_count": 1, "record_refs": [],
               "meetings": [{"meeting_id": f"meeting-{SID}-7", "date": "2026-10-06", "title": "Planning agenda",
                             "category": "Planning", "meeting_type": "regular", "institution_id": INST,
                             "artifacts": {"agenda": {"available": True,
                                                      "url": "https://www.lakeport.example/a/7"}}}]}
    path = root / "data" / "extracted" / SID / "2026-10-18.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(capture))
    return root, path


def test_the_ordinary_load_writes_merge_rows_to_a_fake_graph_and_opens_no_driver(tmp_path, monkeypatch):
    root, capture = _root(tmp_path)
    port = _seed(tmp_path, [{"id": INST, "labels": ["Organization"], "properties": {"id": INST, "name": "Keep"}}])
    import neo4j_target

    def no_driver(*a, **k):
        raise AssertionError("a fake graph never opens a driver")

    monkeypatch.setattr(neo4j_target, "open_driver", no_driver)
    monkeypatch.setenv("NEO4J_URI", f"fakegraph://{port.path}")
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    assert nm.main(["--source", SID, "--capture", str(capture), "--load", "--root", str(root)]) == 0
    rows = [json.loads(x) for x in (port.path / "overlay.jsonl").read_text().splitlines()]
    assert rows and all(set(r) <= {"merge_node", "merge_edge"} for r in rows)
    with gl.FakeGraphPort(port.path).transaction(()) as tx:
        assert f"meeting-{SID}-7" in tx.nodes([f"meeting-{SID}-7"])


def test_an_unsafe_target_still_refuses(tmp_path, monkeypatch):
    root, capture = _root(tmp_path)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "x")
    from neo4j_target import UnsafeNeo4jTarget

    with pytest.raises(UnsafeNeo4jTarget):
        nm.main(["--source", SID, "--capture", str(capture), "--load", "--root", str(root)])
