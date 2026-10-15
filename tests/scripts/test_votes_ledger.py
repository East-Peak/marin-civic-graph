"""Votes Part A, increment g: the ledger build end to end on a fictional world — outputs, checks,
coverage, samples, and byte-identical rebuilds."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from votes_inventory import build_inventory, write_inventory  # noqa: E402
from votes_ledger import build, main  # noqa: E402

BOS = "marin-county-bos"
NOV = "novato-city-council"
ROLL = ("<p>Roll Call</p><p>Present: Supervisor Alder; Supervisor Birch; Supervisor Cedar; Supervisor Dogwood; "
        "Supervisor Elm</p>")


def _html(*paragraphs):
    return ("<html><body><p>MINUTES OF THE FICTIONAL BOARD OF SUPERVISORS</p>" + "".join(paragraphs)
            + "<p>The meeting adjourned.</p></body></html>").encode()


@pytest.fixture
def world(tmp_path):
    raw = tmp_path / "raw"
    (raw / BOS / "minutes").mkdir(parents=True)
    (raw / NOV / "minutes").mkdir(parents=True)
    docs = {
        f"meeting-{BOS}-1": _html(ROLL, "<p>1.</p><p>Item one.</p>",
                                  "<p>M/s Supervisor Alder - Supervisor Birch to approve item one.</p><p>AYES: ALL</p>",
                                  "<p>2.</p><p>Item two.</p>",
                                  "<p>M/s Supervisor Cedar - Supervisor Alder to deny item two.</p>",
                                  "<p>Vote: Motion carried 3-2</p>",
                                  "<p>AYES: Supervisor Alder, Supervisor Cedar, Supervisor Dogwood</p>",
                                  "<p>NOES: Supervisor Birch, Supervisor Elm</p>",
                                  "<p>3.</p><p>Item three.</p><p>The Board voted unanimously to reconsider.</p>"),
        f"meeting-{BOS}-2": _html("<p>Closed session only.</p>"),
    }
    for mid, data in docs.items():
        (raw / BOS / "minutes" / f"{mid}.html").write_bytes(data)
    nodes, edges = [], []
    for i, (mid, date) in enumerate([(f"meeting-{BOS}-1", "2020-01-07"), (f"meeting-{BOS}-2", "2020-01-14"),
                                     (f"meeting-{BOS}-3", "2020-01-21")]):
        nodes.append({"id": mid, "labels": ["Meeting"], "properties": {"id": mid, "meeting_date": date,
                                                                        "title": "Board of Supervisors 2020"}})
        if i < 2:
            rid = f"record-{mid}-minutes"
            nodes.append({"id": rid, "labels": ["Record"], "properties": {
                "id": rid, "record_type": "meeting_minutes", "preferred_public_url": f"https://example.invalid/{i}"}})
            edges.append({"start_id": mid, "end_id": rid, "type": "EVIDENCED_BY", "properties": {}})
    nodes.append({"id": f"decision-{BOS}-1-vote-0", "labels": ["Decision"], "properties": {
        "id": f"decision-{BOS}-1-vote-0", "source_id": BOS, "meeting_id": f"meeting-{BOS}-1",
        "motion_text": "approve item one.", "mover": "Alder", "seconder": "Birch", "ayes": ["ALL"], "noes": [],
        "recused": [], "absent": [], "outcome": "carried"}})
    nodes.append({"id": "seatservice-ann-alder-x", "labels": ["SeatService"], "properties": {
        "id": "seatservice-ann-alder-x", "started_at": "2019-01-01", "ended_at": None}})
    nodes.append({"id": "seat-x-district-1", "labels": ["Seat"], "properties": {"id": "seat-x-district-1",
                                                                               "name": "District 1"}})
    nodes.append({"id": "person-ann-alder", "labels": ["Person"], "properties": {"id": "person-ann-alder",
                                                                                "name": "Ann Alder"}})
    edges += [{"start_id": "seatservice-ann-alder-x", "end_id": "seat-x-district-1", "type": "FOR_SEAT",
               "properties": {}},
              {"start_id": "seatservice-ann-alder-x", "end_id": "person-ann-alder", "type": "HELD_BY",
               "properties": {}},
              {"start_id": "seat-x-district-1", "end_id": "org-marin-county-board-of-supervisors",
               "type": "AT_INSTITUTION", "properties": {}}]
    export = tmp_path / "export"
    export.mkdir()
    (export / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    (export / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges))
    inv = build_inventory(export, raw, tmp_path / "fetched", {BOS: ("2019-01-01", "2020-12-31"),
                                                              NOV: ("2019-01-01", "2020-12-31")})
    write_inventory(inv, tmp_path / "inventory")
    drafts = {BOS: {"body": BOS, "terms": [
        {"draft_id": "t-alder", "member": "Ann Alder", "key": "ALDER", "seat": "District 1", "start": "2019-01-01",
         "end": None, "start_kind": "window", "basis": "in office at the window's start", "confidence": "low",
         "notes": "", "evidence": [{"source": f"minutes:meeting-{BOS}-1", "quote": "Present: Supervisor Alder",
                                    "supports": ["start", "seat"]}]}]},
        NOV: {"body": NOV, "terms": []}}
    (tmp_path / "drafts.json").write_text(json.dumps(drafts))
    return tmp_path


def _build(world, out):
    return build(world / "inventory", out, roster_drafts=world / "drafts.json", seed=7, as_of="2020-12-31")


def _jsonl(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def test_outputs_and_checks(world):
    out = world / "out"
    summary = _build(world, out)
    for name in ("events.jsonl", "candidates.jsonl", "dispositions.jsonl", "documents.jsonl", "reconciliation.jsonl",
                 "coverage.json", "coverage.md", "samples.md", "check.json", "roster/batch-001.md",
                 "roster/batch-001.json", "roster/seatservices.json", "roster/coverage.json"):
        assert (out / name).is_file(), name
    check = json.loads((out / "check.json").read_text())
    assert check["problems"] == [] and summary["problems"] == 0
    events = _jsonl(out / "events.jsonl")
    assert sorted(e["status"] for e in events) == ["expanded", "named"]


def test_documents_without_candidates_and_meetings_without_documents_are_recorded(world):
    out = world / "out"
    _build(world, out)
    docs = {d["meeting_id"]: d for d in _jsonl(out / "documents.jsonl")}
    assert docs[f"meeting-{BOS}-2"]["class"] == "no_candidates"
    assert docs[f"meeting-{BOS}-3"]["class"] == "gap" and docs[f"meeting-{BOS}-3"]["gap"] == "no_minutes_record"


def test_a_narrative_vote_is_held_and_counted(world):
    out = world / "out"
    _build(world, out)
    held = [d for d in _jsonl(out / "dispositions.jsonl") if d["reason"] == "narrative_vote_unaccounted"]
    assert held
    cov = json.loads((out / "coverage.json").read_text())
    assert cov[BOS]["candidates"]["held"]["narrative_vote_unaccounted"] == len(held)


def test_coverage_numbers(world):
    out = world / "out"
    _build(world, out)
    cov = json.loads((out / "coverage.json").read_text())[BOS]
    assert cov["meetings"] == 3 and cov["documents"] == 2 and cov["gaps"] == {"no_minutes_record": 1}
    assert cov["events"]["expanded"] == 1 and cov["events"]["named"] == 1
    assert cov["decisions"]["matched"] == 1 and cov["decisions"]["new_events"] == 1


def test_samples_carry_excerpts_and_every_dissent(world):
    out = world / "out"
    _build(world, out)
    md = (out / "samples.md").read_text()
    assert "seed 7" in md and "NOES: Supervisor Birch, Supervisor Elm" in md
    assert "AYES: ALL" in md


def test_rebuilds_are_byte_identical(world):
    a, b = world / "a", world / "b"
    _build(world, a)
    _build(world, b)
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    for f in files:
        assert hashlib.sha256((a / f).read_bytes()).digest() == hashlib.sha256((b / f).read_bytes()).digest(), f


def test_a_changed_document_stops_the_build(world):
    (world / "raw" / BOS / "minutes" / f"meeting-{BOS}-1.html").write_bytes(b"<html>changed</html>")
    with pytest.raises(Exception, match="sha256"):
        _build(world, world / "out")


def test_cli_build_and_check(world):
    out = world / "out"
    assert main(["build", "--inventory", str(world / "inventory"), "--out", str(out), "--roster-drafts",
                 str(world / "drafts.json"), "--seed", "7", "--as-of", "2020-12-31"]) == 0
    assert main(["check", "--out", str(out)]) == 0
    (out / "events.jsonl").write_text((out / "events.jsonl").read_text().replace('"named"', '"expanded"', 1))
    assert main(["check", "--out", str(out)]) == 1
