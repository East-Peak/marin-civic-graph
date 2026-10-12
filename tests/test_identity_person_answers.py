"""Short answers: the review file shows numbered options, the build keeps their decision lines in a companion file,
and `ingest --answers` expands `<item> <option>` lines into those exact decision lines before every usual check.
Fictional world; every command's output is scanned for streets."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import identity_person as cli  # noqa: E402
import identity_person_key as ik  # noqa: E402
from tests.identity_person_fixtures import assert_no_street, build_world  # noqa: E402
from tests.test_identity_person_ingest import Run, _built  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = build_world(tmp_path / "w")
    monkeypatch.setenv(ik.ENV, str(w.private))
    assert cli.main(["init-key"]) == 0
    return w


@pytest.fixture
def run(capsys):
    return Run(capsys)


def _options(build_dir: Path) -> list[dict]:
    return json.loads((build_dir / "review" / "batch-001.options.json").read_text())["items"]


def _answer(world, run, build_dir, text, name="answers.txt"):
    """Answers as Stuart writes them; the batch line is added unless the text already starts with one or is a
    test of a missing/wrong batch line (`raw:` prefix)."""
    if text.startswith("raw:"):
        text = text[4:]
    elif not text.startswith("batch "):
        text = _batch_line(build_dir) + text
    path = world.root / name
    path.write_text(text)
    return run("ingest", "--build", build_dir.name, "--answers", str(path))


def test_the_build_numbers_items_and_options_and_keeps_their_lines_beside_the_review(world, run):
    build_dir, queue = _built(world, run)
    items = _options(build_dir)
    assert [i["n"] for i in items] == [1, 2, 3, 4]
    assert [i["id"] for i in items] == [q["id"] for q in queue["items"]]
    for item in items:
        assert [o["n"] for o in item["options"]] == list(range(1, len(item["options"]) + 1))
        assert all(o["label"] and o["lines"] for o in item["options"])
    review = (build_dir / "review" / "batch-001.md").read_text()
    assert "`2 1`" in review and "--answers" in review
    assert '{"' not in review  # no decision JSON to copy any more


def test_an_answer_writes_exactly_the_option_lines_and_a_repeat_is_a_no_op(world, run):
    build_dir, _ = _built(world, run)
    expected = _options(build_dir)[1]["options"][0]["lines"]  # item 2: same + is
    assert _answer(world, run, build_dir, "2 1\n") == 0, run.last
    assert world.decisions.read_text().splitlines() == expected
    assert _answer(world, run, build_dir, "2 1\n") == 0
    assert "no change" in run.last


def test_answers_take_item_ids_comments_and_blank_lines(world, run):
    build_dir, _ = _built(world, run)
    items = _options(build_dir)
    text = _batch_line(build_dir) + f"# my first review\n\n{items[3]['id']} 1   # one person\n"
    assert _answer(world, run, build_dir, text) == 0, run.last
    assert world.decisions.read_text().splitlines() == items[3]["options"][0]["lines"]


@pytest.mark.parametrize("text, why, line", [
    ("9 1\n", "no such item", 3),
    ("2 7\n", "no such option for item 2", 3),
    ("2 1\n2 2\n", "item 2 answered twice", 4),
    ("2\n", "expected", 3),
    ("two one\n", "expected", 3),
])
def test_a_bad_answer_rejects_the_whole_file(world, run, text, why, line):
    build_dir, _ = _built(world, run)
    assert _answer(world, run, build_dir, "4 1\n" + text) == 1
    assert "nothing written" in run.last and why in run.last and f"answer line {line}:" in run.last
    assert world.decisions.read_text() == ""


def test_a_rejected_expansion_names_the_answer_it_came_from(world, run):
    build_dir, _ = _built(world, run)
    c = _options(build_dir)[3]
    distinct = next(o["n"] for o in c["options"] if "different person" in o["label"])
    assert _answer(world, run, build_dir, "4 1\n") == 0, run.last
    assert _answer(world, run, build_dir, f"# later\n4 {distinct}\n", name="second.txt") == 1
    assert "conflict" in run.last and "answer line 3 (item 4, option" in run.last


def test_answers_and_decision_lines_are_one_or_the_other(world, run):
    build_dir, _ = _built(world, run)
    lines = world.root / "lines.jsonl"
    lines.write_text("")
    answers = world.root / "answers.txt"
    answers.write_text(_batch_line(build_dir) + "2 1\n")
    with pytest.raises(SystemExit):
        cli.main(["ingest", "--build", build_dir.name, str(lines), "--answers", str(answers)])
    with pytest.raises(SystemExit):
        cli.main(["ingest", "--build", build_dir.name])


def test_no_answer_output_carries_a_street(world, run):
    build_dir, _ = _built(world, run)
    _answer(world, run, build_dir, "2 1\n9 9\n")
    _answer(world, run, build_dir, "2 1\n")
    assert_no_street("\n".join(run.said))
    assert_no_street((build_dir / "review" / "batch-001.options.json").read_text())


def _batch_line(build_dir: Path) -> str:
    return f"batch {json.loads((build_dir / 'review' / 'batch-001.options.json').read_text())['batch']}\n"


def test_answers_must_name_the_batch_they_answer(world, run):
    build_dir, _ = _built(world, run)
    review = (build_dir / "review" / "batch-001.md").read_text()
    assert f"`{_batch_line(build_dir).strip()}`" in review
    assert _answer(world, run, build_dir, "raw:2 1\n", name="no-batch.txt") == 1
    assert "nothing written" in run.last and "batch" in run.last
    assert _answer(world, run, build_dir, "batch b-000000000000\n2 1\n", name="other.txt") == 1
    assert "another batch" in run.last and world.decisions.read_text() == ""


def test_a_swapped_options_file_is_refused(world, run):
    build_dir, _ = _built(world, run)
    path = build_dir / "review" / "batch-001.options.json"
    options = json.loads(path.read_text())
    options["items"][1], options["items"][3] = options["items"][3], options["items"][1]
    path.write_text(json.dumps(options))
    assert _answer(world, run, build_dir, _batch_line(build_dir) + "2 1\n") == 1
    assert "options file" in run.last and world.decisions.read_text() == ""


def test_an_unknown_item_is_never_echoed(world, run):
    build_dir, _ = _built(world, run)
    secret = "12-Sample-Street-" + "ab" * 32
    assert _answer(world, run, build_dir, _batch_line(build_dir) + f"{secret} 1\n") == 1
    assert "no such item" in run.last and secret not in run.last and "ab" * 32 not in run.last


def test_a_late_dated_expansion_names_its_answer(world, run, tmp_path):
    build_dir, _ = _built(world, run)
    path = build_dir / "review" / "batch-001.options.json"
    options = json.loads(path.read_text())
    lines = options["items"][3]["options"][0]["lines"]
    options["items"][3]["options"][0]["lines"] = [t.replace('"date":"2026-10-12"', '"date":"2027-01-01"') for t in lines]
    path.write_text(json.dumps(options))
    manifest = json.loads((build_dir / "manifest.json").read_text())
    import hashlib
    manifest["options_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (build_dir / "manifest.json").write_text(json.dumps(manifest))
    assert _answer(world, run, build_dir, f"batch {options['batch']}\n# note\n\n4 1\n") == 1
    assert "answer line 4 (item 4, option 1)" in run.last and "dated after" in run.last


def test_two_answers_sharing_a_decision_line_expand_it_once():
    """One bucket matched to two people: both items' first option starts with the same `same` line."""
    options = {"batch": "b-0123456789ab", "items": [
        {"n": 1, "id": "q-A-1", "options": [{"n": 1, "label": "x", "lines": ["SAME", "IS-1"]}]},
        {"n": 2, "id": "q-A-2", "options": [{"n": 1, "label": "y", "lines": ["SAME", "IS-2"]}]}]}
    text, origin = cli.expand_answers("batch b-0123456789ab\n1 1\n2 1\n", options)
    assert text.splitlines() == ["SAME", "IS-1", "IS-2"]
    assert origin == {1: "answer line 2 (item 1, option 1)", 2: "answer line 2 (item 1, option 1)",
                      3: "answer line 3 (item 2, option 1)"}


def test_an_invalid_option_is_never_echoed(world, run):
    build_dir, _ = _built(world, run)
    secret = "123456789012345678901234567890"
    assert _answer(world, run, build_dir, f"2 {secret}\n") == 1
    assert "no such option for item 2" in run.last and secret not in run.last
