"""`build` writes the queue and review files; `ingest` validates Stuart's lines against current evidence and writes
the decision file atomically, or writes nothing. Fictional world; every command's output is scanned for streets."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import identity_person as cli  # noqa: E402
import identity_person_decisions as dec  # noqa: E402
import identity_person_key as ik  # noqa: E402
from tests.identity_person_fixtures import assert_no_street, base_rows, build_world, every_text  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = build_world(tmp_path / "w")
    monkeypatch.setenv(ik.ENV, str(w.private))
    assert cli.main(["init-key"]) == 0
    return w


class Run:
    def __init__(self, capsys):
        self.capsys, self.said = capsys, []

    def __call__(self, *argv) -> int:
        code = cli.main(list(argv))
        captured = self.capsys.readouterr()
        self.said.append(captured.out + captured.err)
        return code

    @property
    def last(self) -> str:
        return self.said[-1]


@pytest.fixture
def run(capsys):
    return Run(capsys)


def _built(world, run, out="test"):
    assert run(*world.build_args(out=out)) == 0, run.last
    path = world.private / "builds" / out
    return path, json.loads((path / "queue.json").read_text())


def _lines(build_dir: Path, item_index: int) -> list[str]:
    """Every decision line the build offers for the n-th item, option after option, in order."""
    items = json.loads((build_dir / "review" / "batch-001.options.json").read_text())["items"]
    return [line for option in items[item_index]["options"] for line in option["lines"]]


def _ingest(world, run, build_dir, lines, name="decide.jsonl"):
    path = world.root / name
    path.write_text("".join(line + "\n" for line in lines))
    return run("ingest", "--build", build_dir.name, str(path))


def test_build_writes_the_queue_and_the_first_batch(world, run):
    build_dir, queue = _built(world, run)
    assert [i["class"] for i in queue["items"]] == ["B", "A", "A", "C"]
    assert (build_dir / "review" / "batch-001.md").is_file()
    assert queue["counts"]["first_batch"] == 4


def test_ingest_writes_canonical_lines_and_a_repeat_is_a_no_op(world, run):
    build_dir, _ = _built(world, run)
    same, is_line = _lines(build_dir, 1)[:2]  # Larkspur: same(all) then is(all)
    assert _ingest(world, run, build_dir, [same, is_line]) == 0, run.last
    written = world.decisions.read_bytes()
    assert written.decode().splitlines() == [same, is_line]
    assert _ingest(world, run, build_dir, [same, is_line]) == 0
    assert "no change" in run.last and world.decisions.read_bytes() == written
    _, queue = _built(world, run, out="after")
    assert [i["bucket"] for i in queue["items"] if i["class"] == "A"] == ["person-osprey-sam"]


def test_a_batch_with_one_bad_line_writes_nothing(world, run):
    build_dir, _ = _built(world, run)
    same, is_line = _lines(build_dir, 1)[:2]
    for bad in ('{"kind": "same", "note": "12\x20Sample Street"}', "not json at all 12\x20Sample Street",
                is_line.replace('"date":"2026-10-12"', '"date":"2027-01-01"')):
        assert _ingest(world, run, build_dir, [same, bad]) == 1
        assert "nothing written" in run.last and "line 2" in run.last
        assert world.decisions.read_text() == ""
    assert_no_street("\n".join(run.said))


def test_an_is_without_its_same_is_rejected(world, run):
    build_dir, _ = _built(world, run)
    _, is_line = _lines(build_dir, 1)[:2]
    assert _ingest(world, run, build_dir, [is_line]) == 1
    assert "no_covering_same" in run.last and world.decisions.read_text() == ""


def test_a_contradiction_with_the_file_rejects_the_batch(world, run):
    build_dir, queue = _built(world, run)
    c_lines = _lines(build_dir, 3)  # Thornbury (C): same(all), distinct(A | B), defer
    same = next(t for t in c_lines if '"kind":"same"' in t)
    distinct = next(t for t in c_lines if '"kind":"distinct"' in t)
    assert _ingest(world, run, build_dir, [same]) == 0
    assert _ingest(world, run, build_dir, [distinct]) == 1
    assert "conflict" in run.last
    assert world.decisions.read_text().splitlines() == [same]


def test_a_stale_line_is_rejected_with_its_field_diff_and_no_value(world, run, tmp_path):
    build_dir, _ = _built(world, run)
    same = _lines(build_dir, 3)[0]
    rows = base_rows()
    for row in rows["A-Contributions"]:
        if row["Tran_NamL"] == "Thornbury":
            row["Tran_Adr1"] = "250\x20Notreal Blvd"
    moved = build_world(tmp_path / "moved", rows=rows, private=world.private)
    moved_dir, _ = _built(moved, run, out="moved")
    assert _ingest(moved, run, moved_dir, [same]) == 1
    assert "stale" in run.last and "address" in run.last
    assert_no_street(run.last)


def test_ingest_refuses_when_the_evidence_inputs_changed_since_the_build(world, run):
    build_dir, _ = _built(world, run)
    same = _lines(build_dir, 3)[0]
    with open(world.export_dir / "edges.jsonl", "a") as f:
        f.write(json.dumps({"start_id": "person-x", "end_id": "person-y", "type": "KNOWS", "properties": {}}) + "\n")
    assert _ingest(world, run, build_dir, [same]) == 1
    assert "changed since build" in run.last and world.decisions.read_text() == ""


def test_ingest_never_overwrites_a_concurrent_edit(world, run, monkeypatch):
    build_dir, _ = _built(world, run)
    same = _lines(build_dir, 3)[0]
    real = cli._replace_decisions

    def sneaky(path, before, text):
        path.write_text("# edited meanwhile\n")
        return real(path, before, text)
    monkeypatch.setattr(cli, "_replace_decisions", sneaky)
    assert _ingest(world, run, build_dir, [same]) == 1
    assert "changed during ingest" in run.last
    assert world.decisions.read_text() == "# edited meanwhile\n"


def test_reingesting_a_latched_line_with_current_evidence_revalidates_it(world, run):
    build_dir, _ = _built(world, run)
    same = _lines(build_dir, 3)[0]
    assert _ingest(world, run, build_dir, [same]) == 0
    digest = dec.parse_line(same, 1).digest
    dec.write_latch(world.private, frozenset({digest}))
    _, queue = _built(world, run, out="latched")
    assert queue["items"][0]["class"] == "stale"
    assert _ingest(world, run, build_dir, [same]) == 0 and "revalidated 1" in run.last
    assert dec.load_latch(world.private) == frozenset()
    _, queue = _built(world, run, out="revalidated")
    assert not [i for i in queue["items"] if i["class"] in ("stale", "C")]


def test_a_second_ingest_waits_for_nobody_it_refuses(world, run):
    import fcntl

    build_dir, _ = _built(world, run)
    same = _lines(build_dir, 3)[0]
    with open(world.private / "decisions.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert _ingest(world, run, build_dir, [same]) == 1
    assert "another identity command" in run.last


def test_no_command_output_or_file_carries_a_street_or_hash(world, run):
    build_dir, _ = _built(world, run)
    lines = _lines(build_dir, 1)[:2]
    _ingest(world, run, build_dir, lines)
    _ingest(world, run, build_dir, ['{"broken": "12\x20Sample Street"'])
    hashes = {json.loads(t)["address_hash"] for t in
              (build_dir / "address-evidence.jsonl").read_text().splitlines()} - {None}
    typed = [world.root / "decide.jsonl"]  # the test's own (deliberately broken) input
    outside = every_text([world.root], skip=[*world.inputs, *typed], exclude=[world.private]) + "\n".join(run.said)
    assert not any(h in outside for h in hashes)
    inside_reports = every_text([build_dir / "review", build_dir / "queue.json"])
    assert not any(h in inside_reports for h in hashes)
    assert_no_street(every_text([world.root], skip=[*world.inputs, *typed]) + "\n".join(run.said))
    assert oct(os.stat(build_dir / "review" / "batch-001.md").st_mode & 0o777) == "0o600"


def test_a_build_refuses_while_another_identity_command_holds_the_lock(world, run):
    import fcntl

    with open(world.private / "decisions.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert run(*world.build_args()) == 1
    assert "another identity command" in run.last
    assert not (world.private / "builds" / "test").exists()


def test_a_failed_latch_write_publishes_no_build(world, run, monkeypatch):
    build_dir, _ = _built(world, run)
    same = _lines(build_dir, 3)[0]
    assert _ingest(world, run, build_dir, [same]) == 0
    rows = base_rows()
    for row in rows["A-Contributions"]:
        if row["Tran_NamL"] == "Thornbury":
            row["Tran_Emp"] = "Example Water District"

    def broken(*_args):
        raise OSError("disk full")
    monkeypatch.setattr(dec, "write_latch", broken)
    moved = build_world(world.root / "moved", rows=rows, private=world.private)
    moved.decisions.write_text(world.decisions.read_text())
    assert run(*moved.build_args(out="moved")) == 2
    assert not (world.private / "builds" / "moved").exists()


def test_a_decision_dated_after_the_as_of_date_fails_the_build(world, run):
    build_dir, _ = _built(world, run)
    same = _lines(build_dir, 3)[0]
    world.decisions.write_text(same.replace('"date":"2026-10-12"', '"date":"2027-01-01"') + "\n")
    assert run(*world.build_args(out="late")) == 1 and "dated after" in run.last


def test_a_latched_line_removed_and_added_back_needs_revalidation_and_gets_it(world, run):
    build_dir, _ = _built(world, run)
    same = _lines(build_dir, 3)[0]
    assert _ingest(world, run, build_dir, [same]) == 0
    dec.write_latch(world.private, frozenset({dec.parse_line(same, 1).digest}))
    world.decisions.write_text("")
    _, queue = _built(world, run, out="removed")
    world.decisions.write_text(same + "\n")  # a hand edit restores it: still latched, so still stale
    _, queue = _built(world, run, out="restored")
    assert queue["items"][0]["class"] == "stale"
    world.decisions.write_text("")
    assert _ingest(world, run, build_dir, [same]) == 0 and "revalidated 1" in run.last
    assert world.decisions.read_text() == same + "\n" and dec.load_latch(world.private) == frozenset()


def test_a_revalidation_only_ingest_still_refuses_a_concurrent_edit(world, run, monkeypatch):
    build_dir, _ = _built(world, run)
    same = _lines(build_dir, 3)[0]
    assert _ingest(world, run, build_dir, [same]) == 0
    dec.write_latch(world.private, frozenset({dec.parse_line(same, 1).digest}))
    # the line is deleted by hand while ingest runs (after it read the file)
    monkeypatch.setattr(cli.dec, "load_latch", lambda private, _real=dec.load_latch: (
        world.decisions.write_text(""), _real(private))[1])
    assert _ingest(world, run, build_dir, [same]) == 1
    assert "changed during ingest" in run.last
    assert dec.load_latch(world.private) == frozenset({dec.parse_line(same, 1).digest})


def test_ingest_checks_the_dates_of_the_lines_already_in_the_file(world, run):
    build_dir, _ = _built(world, run)
    lines = _lines(build_dir, 1)
    same, is_line = lines[0], lines[1]
    world.decisions.write_text(same.replace('"date":"2026-10-12"', '"date":"2027-01-01"') + "\n")
    assert _ingest(world, run, build_dir, [is_line]) == 1 and "dated after" in run.last
