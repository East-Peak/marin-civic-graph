"""Votes refresh, increment c: the batch adapter over Part A's parser and B2's bundle rules, both accountings, the
independent expected manifest, and init's pinned roster contract. Fictional names, bodies' real ids only."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import votes_refresh_expected as vx  # noqa: E402
import votes_refresh_ledger as rl  # noqa: E402

BOS = "marin-county-bos"
ORG = "org-marin-county-board-of-supervisors"
MEMBERS = ("ALDER", "BIRCH", "CEDAR", "DOGWOOD", "ELM")


def _roll(members=MEMBERS):
    return "<p>Roll Call</p><p>Present: " + "; ".join(f"Supervisor {m.title()}" for m in members) + "</p>"


def _minutes(mid, date_text, *paragraphs, members=MEMBERS):
    clip = mid.rsplit("-", 1)[1]
    return (f"<html><body><a href='MinutesViewer.php?view_id=33&clip_id={clip}'>v</a><p>REGULAR MEETING OF THE "
            f"MARIN COUNTY BOARD OF SUPERVISORS HELD TUESDAY, {date_text}, AT 9:00 A.M.</p>{_roll(members)}"
            + "".join(paragraphs) + "<p>The meeting adjourned.</p></body></html>").encode()


ITEMS = ("<p>1.</p><p>Item one.</p><p>M/s Supervisor Alder - Supervisor Birch to approve item one.</p>"
         "<p>AYES: ALL</p>"
         "<p>2.</p><p>Item two.</p><p>M/s Supervisor Cedar - Supervisor Alder to deny item two.</p>"
         "<p>Vote: Motion carried 3-2</p><p>AYES: Supervisor Alder, Supervisor Cedar, Supervisor Dogwood</p>"
         "<p>NOES: Supervisor Birch, Supervisor Elm</p>")


def _term(key, start="2029-01-01", end=None):
    return {"draft_id": f"t-{key.lower()}", "member": f"Pat {key.title()}", "key": key, "seat": "District 1",
            "start": start, "end": end, "start_kind": "stated", "end_kind": "stated" if end else None,
            "basis": "x", "confidence": "high", "notes": "", "evidence": []}


def _cfg(terms=None):
    terms = terms or [_term(k) for k in MEMBERS]
    drafts = {BOS: {"body": BOS, "terms": terms}}
    items = [{"item": str(i + 1), "draft_id": t["draft_id"], "body": BOS} for i, t in enumerate(terms)]
    answers = [{"item": i["item"], "option": "confirm", "note": None} for i in items]
    rows = [{"item": i["item"], "draft_id": t["draft_id"], "body": BOS, "key": t["key"], "member": t["member"],
             "term_start": t["start"], "term_end": t["end"], "status": "mapped",
             "person_id": f"person-pat-{t['key'].lower()}", "provenance": [], "alternates": [],
             "reviewer_basis": "fixture", "notes": ""} for i, t in zip(items, terms)]
    return {"drafts": drafts, "items": items, "answers": answers, "rows": rows,
            "mapping_answers": [{"item": r["item"], "option": "confirm", "note": None} for r in rows],
            "applied_persons": []}


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "repo"
    docs, nodes = [], []
    for mid, date, text in ((f"meeting-{BOS}-7001", "2030-04-09", "APRIL 9, 2030"),
                            (f"meeting-{BOS}-7002", "2030-04-23", "APRIL 23, 2030")):
        p = repo / "data/raw/manual/2030-05-01/minutes" / BOS / f"{mid}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_minutes(mid, text, ITEMS))
        docs.append({"body": BOS, "meeting_id": mid, "date": date, "title": "Board of Supervisors 2030",
                     "path": p.relative_to(repo).as_posix(), "format": "html",
                     "sha256": rl.sha256_file(p)})
        nodes.append({"id": mid, "labels": ["Meeting"], "properties": {"id": mid, "meeting_date": date,
                                                                        "institution_id": ORG,
                                                                        "title": "Board of Supervisors 2030"}})
    nodes += [{"id": f"person-pat-{k.lower()}", "labels": ["Person"], "properties": {"id": f"person-pat-{k.lower()}",
                                                                                     "name": f"Pat {k.title()}"}}
              for k in MEMBERS]
    return repo, docs, nodes, []


def _build(world, cfg=None, holds=(), reviewer=()):
    repo, docs, nodes, edges = world
    return rl.build_batch(docs, repo, nodes, edges, cfg or _cfg(), holds=list(holds), reviewer_holds=list(reviewer))


class TestBatch:
    def test_votes_attach_as_new_decisions(self, world):
        out = _build(world)
        acc = out["bundle_accounting"]
        assert acc["by_body"] == {BOS: {"attached": 4}}
        assert acc["edges_by_vote"] == {"aye": 16, "no": 4}
        assert out["accounting"]["problems"] == [] and out["accounting"]["matches_expected"] is True
        assert out["new_holds"] == [] and out["hints"][BOS]["evidence"] == "ok"

    def test_event_ids_carry_meeting_document_and_line(self, world):
        repo, docs, *_ = world
        ids = sorted(d["event_id"] for d in _build(world)["bundle"]["dispositions"])
        assert ids[0].startswith(f"vev-{BOS}-7001-{docs[0]['sha256'][:8]}-L")

    def test_a_changed_document_is_refused(self, world):
        repo, docs, *_ = world
        (repo / docs[0]["path"]).write_bytes(b"<html>other</html>")
        with pytest.raises(rl.AdapterError, match="sha256"):
            _build(world)

    def test_an_unknown_roll_call_name_is_a_hold_from_that_meeting(self, world):
        cfg = _cfg([_term(k) for k in MEMBERS if k != "ELM"])
        out = _build(world, cfg)
        assert [(h["kind"], h["key"], h["from_date"]) for h in out["new_holds"]] == \
            [("name_without_term", "ELM", "2030-04-09")]
        assert out["bundle_accounting"]["by_body"] == {BOS: {"roster_hold": 4}}
        assert out["accounting"]["matches_expected"] is True

    def test_a_hold_from_an_earlier_batch_is_enforced_whatever_the_document_order(self, world):
        hold = {"hold_id": "hold-aaaaaaaa", "body": BOS, "from_date": "2030-04-20", "kind": "roster_event"}
        out = _build(world, holds=[hold])
        by_meeting = {}
        for d in out["bundle"]["dispositions"]:
            by_meeting.setdefault(d["meeting_id"], set()).add(d["reason"])
        assert by_meeting == {f"meeting-{BOS}-7001": {"attached"}, f"meeting-{BOS}-7002": {"roster_hold"}}
        assert out["accounting"]["matches_expected"] is True

    def test_resolved_holds_do_not_hold(self, world):
        hold = {"hold_id": "hold-aaaaaaaa", "body": BOS, "from_date": "2030-01-01", "resolved": True}
        assert _build(world, holds=[hold])["bundle_accounting"]["by_body"] == {BOS: {"attached": 4}}

    def test_a_reviewer_hold(self, world):
        first = sorted(d["event_id"] for d in _build(world)["bundle"]["dispositions"])[0]
        out = _build(world, reviewer=[{"event_id": first, "reason": "S1: wrong item"}])
        assert out["bundle_accounting"]["by_body"] == {BOS: {"attached": 3, "reviewer_hold": 1}}
        assert out["accounting"]["matches_expected"] is True

    def test_hold_everything_attaches_nothing(self, world):
        out = _build(world, holds=[{"hold_id": "hold-b", "body": BOS, "from_date": "2000-01-01"}])
        assert out["bundle"]["edges"] == [] and out["attached"] == 0

    def test_a_quoted_resignation_is_no_hold(self, world):
        repo, docs, nodes, edges = world
        p = repo / docs[0]["path"]
        p.write_bytes(_minutes(docs[0]["meeting_id"], "APRIL 9, 2030", ITEMS,
                               "<p>Public comment: a speaker said “I resigned from the Board of Supervisors.”</p>"))
        docs[0]["sha256"] = rl.sha256_file(p)
        assert _build(world)["new_holds"] == []

    def test_a_resignation_from_the_board_is_a_hold_and_writes_a_packet(self, world, tmp_path):
        repo, docs, nodes, edges = world
        p = repo / docs[0]["path"]
        p.write_bytes(_minutes(docs[0]["meeting_id"], "APRIL 9, 2030", ITEMS,
                               "<p>Supervisor Elm resigned from the Board of Supervisors effective May 1.</p>"))
        docs[0]["sha256"] = rl.sha256_file(p)
        out = _build(world)
        assert [(h["kind"], h["signal"]) for h in out["new_holds"]] == [("roster_event", "resignation")]
        md = rl.render_packet(out["new_holds"][0])
        assert "resigned from the Board of Supervisors" in md and "dismiss:" in md and docs[0]["path"] in md

    def test_zero_roll_calls_is_insufficient_evidence(self, world):
        repo, docs, nodes, edges = world
        for d in docs:
            p = repo / d["path"]
            p.write_bytes(p.read_bytes().replace(b"<p>Roll Call</p>", b"").replace(b"Present: ", b"Seen: "))
            d["sha256"] = rl.sha256_file(p)
        assert _build(world)["hints"][BOS]["evidence"] == "insufficient evidence"

    def test_no_historical_decisions_reach_the_reports(self, world):
        repo, docs, nodes, edges = world
        nodes.append({"id": "decision-marin-county-bos-1-vote-0", "labels": ["Decision"], "properties": {
            "id": "decision-marin-county-bos-1-vote-0", "source_id": BOS, "meeting_id": "meeting-marin-county-bos-1",
            "motion_text": "old", "ayes": ["ALL"], "outcome": "carried"}})
        out = _build(world)
        assert out["reconciliation"] == [r for r in out["reconciliation"] if r["meeting_id"].endswith(("7001", "7002"))]
        assert not [r for r in out["bundle"]["repair"] if r.get("decision_id") == "decision-marin-county-bos-1-vote-0"]

    def test_open_terms_cover_the_selected_dates(self, world):
        cfg = _cfg()
        assert rl.as_of_for(world[1]) == "2030-04-23"
        assert _build(world, cfg)["as_of"] == "2030-04-23"

    def test_the_mapping_is_validated_against_the_batch_baseline(self, world):
        cfg = _cfg()
        cfg["rows"][0]["person_id"] = "person-nobody"
        with pytest.raises(rl.AdapterError, match="mapping"):
            _build(world, cfg)


class TestCandidateAccounting:
    def test_every_document_candidate_and_event_is_accounted(self, world):
        acc = _build(world)["accounting"]
        assert acc["documents"] == 2 and acc["candidates"] > 0 and acc["accepted_events"] == 4
        assert acc["problems"] == []

    def test_a_lost_event_is_a_problem(self, world):
        out = _build(world)
        bundle = dict(out["bundle"], dispositions=out["bundle"]["dispositions"][1:])
        problems = rl.candidate_accounting(out["documents_selected"], out["ledger"], bundle)["problems"]
        assert any("not in the bundle" in p for p in problems)


class TestExpected:
    def test_the_expected_script_imports_neither_builder(self):
        imports = [ln for ln in Path(vx.__file__).read_text().splitlines() if ln.startswith(("import ", "from "))]
        assert imports and not [ln for ln in imports if "votes_" in ln]
