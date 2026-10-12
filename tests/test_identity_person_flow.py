"""End to end over the fictional world, frozen clock (as-of 2026-10-12): build the queue (every class), ingest
same / distinct / is / reject / defer, then prove staleness, amendments, flow conflicts, revocation, idempotence,
atomic rejection, and that report totals equal an independent cent-exact recomputation over distinct flows.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import identity_person as cli  # noqa: E402
import identity_person_decisions as dec  # noqa: E402
import identity_person_key as ik  # noqa: E402
from tests.identity_person_fixtures import SOURCE, assert_no_street, base_rows, build_world, every_text  # noqa: E402

AS_OF = "2026-10-12"


class Session:
    """One private dir and key; worlds (re-downloads) come and go; the decision file is the first world's."""

    def __init__(self, tmp: Path, capsys, monkeypatch):
        self.tmp, self.capsys, self.said = tmp, capsys, []
        self.world = build_world(tmp / "base")
        self.decisions = self.world.decisions
        monkeypatch.setenv(ik.ENV, str(self.world.private))
        assert self.run("init-key") == 0

    def run(self, *argv) -> int:
        code = cli.main(list(argv))
        out = self.capsys.readouterr()
        self.said.append(out.out + out.err)
        return code

    def build(self, name: str, world=None) -> Path:
        w = world or self.world
        assert self.run("build", "--ledger", str(w.ledger_dir), "--raw-root", str(w.raw_root), "--export",
                        str(w.export_dir), "--decisions", str(self.decisions), "--as-of", AS_OF, "--out", name) == 0, \
            self.said[-1]
        return self.world.private / "builds" / name

    def options(self, build: Path, item_id: str) -> dict[str, list[str]]:
        text = (build / "review" / "batch-001.md").read_text()
        section = next(s for s in text.split("\n## ")[1:] if item_id in s.splitlines()[0])
        out = {}
        for chunk in section.split("**Option ")[1:]:
            label = chunk.split(" — ", 1)[1].split("** (", 1)[0]
            out[label] = chunk.split("```\n", 1)[1].split("\n```", 1)[0].splitlines()
        return out

    def ingest(self, build: Path, lines: list[str], name="decide.jsonl") -> int:
        path = self.tmp / name
        path.write_text("".join(t + "\n" for t in lines))
        return self.run("ingest", "--build", build.name, str(path))


@pytest.fixture
def s(tmp_path, capsys, monkeypatch):
    return Session(tmp_path.resolve(), capsys, monkeypatch)


def _queue(build: Path) -> list[dict]:
    return json.loads((build / "queue.json").read_text())["items"]


def _item(build: Path, bucket: str) -> str:
    return next(i["id"] for i in _queue(build) if i["bucket"] == bucket)


def _state(build: Path) -> dict:
    return json.loads((build / "decisions-state.json").read_text())


def _decide_everything(s: Session) -> tuple[Path, dict[str, list[str]]]:
    b1 = s.build("b1")
    assert {i["class"] for i in _queue(b1)} == {"B", "A", "C"}
    chosen = {
        "larkspur": s.options(b1, _item(b1, "person-larkspur-robin"))["All 2 rows are person-robin-q-larkspur"],
        "osprey": s.options(b1, _item(b1, "person-osprey-sam"))["None of these rows is person-sam-osprey"],
        "thornbury": s.options(b1, _item(b1, "person-thornbury-casey"))["Each address cluster is a different person"],
        "quill": s.options(b1, _item(b1, "person-quill-avery"))["Cannot decide from these inputs"],
    }
    kinds = {json.loads(t)["kind"] for lines in chosen.values() for t in lines}
    assert kinds == {"same", "is", "reject", "distinct", "defer"}
    batch = [t for lines in chosen.values() for t in lines]
    assert s.ingest(b1, batch) == 0, s.said[-1]
    return b1, chosen


def test_the_full_review_cycle(s):
    b1, chosen = _decide_everything(s)
    written = s.decisions.read_bytes()
    assert len(written.decode().splitlines()) == 7  # same+is, reject, same+same+distinct, defer

    # re-ingesting the same batch is a no-op
    assert s.ingest(b1, [t for lines in chosen.values() for t in lines]) == 0 and "no change" in s.said[-1]
    assert s.decisions.read_bytes() == written

    # a batch with one bad line writes nothing
    vale = _rows_of(s, b1, "person-vale-morgan")
    good = dec.decision_line("same", [list(vale)], vale, "stuart", AS_OF)
    assert s.ingest(b1, [good, '{"kind": "same", "groups": "12 Sample Street"}']) == 1
    assert "nothing written" in s.said[-1] and s.decisions.read_bytes() == written

    # everything decided: nothing of B/A/C left, every decision effective
    b2 = s.build("b2")
    assert [i for i in _queue(b2) if i["class"] in ("B", "A", "C")] == []
    assert set(_state(b2)["status"].values()) == {"effective"}

    # two builds of the same inputs, frozen clock: byte-identical
    b2_again = s.build("b2-again")
    for rel in sorted(p.relative_to(b2) for p in b2.rglob("*") if p.is_file()):
        assert (b2 / rel).read_bytes() == (b2_again / rel).read_bytes(), rel
    assert_no_street(every_text([s.tmp], skip=[*s.world.inputs, s.tmp / "decide.jsonl"]) + "\n".join(s.said))


def _rows_of(s: Session, build: Path, bucket: str) -> dict[str, str]:
    """{row id: fp} for a bucket, from the build's address-evidence + a fresh state (fps come from the queue)."""
    import identity_person_evidence as ev

    w = s.world
    evidence = ev.collect(ev.Inputs(w.ledger_dir, w.raw_root, w.export_dir, s.decisions),
                          ik.load_key(w.private))
    return {r.row_id: r.fp for r in evidence.rows if r.bucket == bucket}


def test_an_address_only_change_makes_the_decision_stale_saying_only_address_changed(s):
    _decide_everything(s)
    rows = base_rows()
    for row in rows["A-Contributions"]:
        if row["Tran_ID"] == "M-2":  # a Larkspur row: same street name, new number
            row["Tran_Adr1"] = "79 Fictional Way"
    moved = build_world(s.tmp / "moved", rows=rows, private=s.world.private)
    b = s.build("moved", moved)
    stale = [i for i in _queue(b) if i["class"] == "stale"]
    assert len(stale) == 2  # the same and the is over the Larkspur rows
    for item in stale:
        [changes] = [v for k, v in item["detail"]["diff"].items() if k.startswith("r-")]
        assert changes == ["address"]
    review = (b / "review" / "batch-001.md").read_text()
    assert ": address changed" in review
    assert "79 FICTIONAL" not in review.upper() and "77 FICTIONAL" not in review.upper()
    # and it stays stale when the evidence comes back (latched)
    back = s.build("back")
    assert {i["class"] for i in _queue(back)} >= {"stale"}


def test_an_amendment_that_removes_a_row_stales_its_decisions(s):
    _decide_everything(s)
    rows = base_rows()
    rows["A-Contributions"] = [r for r in rows["A-Contributions"] if r["Tran_ID"] != "M-2"]
    amended = build_world(s.tmp / "amended", rows=rows, private=s.world.private)
    b = s.build("amended", amended)
    diffs = [i["detail"]["diff"] for i in _queue(b) if i["class"] == "stale"]
    assert diffs and all(["row gone"] in d.values() for d in diffs)
    assert "row gone (amended away or no longer counted)" in (b / "review" / "batch-001.md").read_text()


def test_a_flow_split_across_two_people_is_one_conflict_and_counts_for_nobody(s):
    b1 = s.build("b1")
    vale = sorted(_rows_of(s, b1, "person-vale-morgan").items())
    fable = sorted(_rows_of(s, b1, "person-fable-jordan").items())
    split = [dec.decision_line("same", [[vale[0][0], fable[0][0]]], dict([vale[0], fable[0]]), "stuart", AS_OF),
             dec.decision_line("same", [[vale[1][0], fable[1][0]]], dict([vale[1], fable[1]]), "stuart", AS_OF)]
    assert s.ingest(b1, split) == 1 and "split across people" in s.said[-1]  # ingest refuses to create it
    s.decisions.write_text("".join(t + "\n" for t in split))  # a hand edit can
    b = s.build("split")
    [conflict] = [i for i in _queue(b) if i["class"] == "conflict"]
    assert len(conflict["decisions"]) == 2
    report = json.loads((b / "report.json").read_text())
    assert report["persons"] == [] and report["conflicts"] == 1


def test_revoking_a_same_suspends_its_dependent_is(s):
    _, chosen = _decide_everything(s)
    same, is_line = chosen["larkspur"]
    s.decisions.write_text("".join(t + "\n" for t in s.decisions.read_text().splitlines() if t != same))
    b = s.build("revoked")
    assert _state(b)["suspended"] == {dec.parse_line(is_line, 1).digest: "no_covering_same"}
    assert any(i["class"] == "stale" and i["decisions"] == [dec.parse_line(is_line, 1).digest] for i in _queue(b))
    assert _item(b, "person-larkspur-robin")  # and the question is back in the queue


def test_report_totals_equal_an_independent_recomputation_over_distinct_flows(s):
    b1 = s.build("b1")
    _, chosen = _decide_everything(s)
    vale = _rows_of(s, b1, "person-vale-morgan")
    assert s.ingest(b1, [dec.decision_line("same", [list(vale)], vale, "stuart", AS_OF)], name="vale.jsonl") == 0
    report = json.loads((s.build("totals") / "report.json").read_text())

    # independently, from the ledger file: each person's transactions, each counted MoneyFlow once
    ledger = [json.loads(t) for t in (s.world.ledger_dir / SOURCE / "ledger.jsonl").read_text().splitlines()]
    flow_of, amount_of = {}, {}
    for row in ledger:
        if row.get("schedule") == "A" and row.get("counted"):
            flow_of[(SOURCE, row["moneyflow_id"].split("-")[1], row["tran_id"])] = row["moneyflow_id"]
            amount_of[row["moneyflow_id"]] = Decimal(row["amount"])
    assert len(report["persons"]) == 4  # Larkspur, Vale, and the two Thornbury clusters
    for person in report["persons"]:
        flows = {flow_of[tuple(t)] for t in person["transactions"]}
        assert person["total_cents"] == int(sum(amount_of[f] for f in flows) * 100), person["label"]
        assert person["flows"] == len(flows)
    by_bucket = {p["buckets"][0]: p["total_cents"] for p in report["persons"] if len(p["buckets"]) == 1}
    assert by_bucket["person-larkspur-robin"] == 130000 and by_bucket["person-vale-morgan"] == 60000


def test_the_decision_file_holds_only_grammar_and_keyed_digests(s):
    _decide_everything(s)
    for text in s.decisions.read_text().splitlines():
        d = dec.parse_line(text, 1)
        assert set(json.loads(text)) <= dec.KEYS and all(v.startswith("fp1:k1:") for v in d.fp.values())
    hashes = {json.loads(t)["address_hash"] for t in
              (s.world.private / "builds" / "b1" / "address-evidence.jsonl").read_text().splitlines()} - {None}
    assert not any(h in s.decisions.read_text() for h in hashes)
    assert oct(os.stat(s.world.private).st_mode & 0o777) == "0o700"
    shutil.rmtree(s.world.private / "builds")  # nothing else depends on the builds
