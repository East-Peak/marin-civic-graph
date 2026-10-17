"""Votes refresh, increment d: `prepare` end to end on a fictional world — batches, revisions, holds across
batches, slot identity, apply outcomes and the journal, approval, determinism, no network."""
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import votes_apply  # noqa: E402
import votes_refresh as vr  # noqa: E402
import votes_refresh_ledger as rl  # noqa: E402
from case_additive_plan import fingerprint  # noqa: E402
from test_votes_apply import FakeGraph  # noqa: E402
from votes_inventory import build_inventory, write_inventory  # noqa: E402

BOS = "marin-county-bos"
NOV = "novato-city-council"
ORG = {BOS: "org-marin-county-board-of-supervisors", NOV: "org-novato-city-council"}
MEMBERS = ("ALDER", "BIRCH", "CEDAR", "DOGWOOD", "ELM")
ITEMS = ("<p>1.</p><p>Item one.</p><p>M/s Supervisor Alder - Supervisor Birch to approve item one.</p>"
         "<p>AYES: ALL</p>"
         "<p>2.</p><p>Item two.</p><p>M/s Supervisor Cedar - Supervisor Alder to deny item two.</p>"
         "<p>Vote: Motion carried 3-2</p><p>AYES: Supervisor Alder, Supervisor Cedar, Supervisor Dogwood</p>"
         "<p>NOES: Supervisor Birch, Supervisor Elm</p>")
MEETINGS = {7001: ("2030-04-09", "APRIL 9, 2030"), 7002: ("2030-04-23", "APRIL 23, 2030"),
            7003: ("2030-05-07", "MAY 7, 2030")}


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def minutes(clip, *extra, members=MEMBERS):
    date_text = MEETINGS[clip][1]
    roll = "<p>Roll Call</p><p>Present: " + "; ".join(f"Supervisor {m.title()}" for m in members) + "</p>"
    return (f"<html><body><a href='MinutesViewer.php?view_id=33&clip_id={clip}'>v</a><p>REGULAR MEETING OF THE "
            f"MARIN COUNTY BOARD OF SUPERVISORS HELD TUESDAY, {date_text}, AT 9:00 A.M.</p>{roll}{ITEMS}"
            + "".join(extra) + "<p>The meeting adjourned.</p></body></html>")


class World:
    def __init__(self, tmp: Path):
        self.tmp, self.repo, self.refresh = tmp, tmp / "repo", tmp / "refresh"
        (self.repo / "data" / "ingest-runs").mkdir(parents=True)
        self.refresh.mkdir()
        self.nodes, self.edges = [], []
        for clip, (date, _) in MEETINGS.items():
            mid, rid = f"meeting-{BOS}-{clip}", f"record-min-{clip}"
            self.nodes += [{"id": mid, "labels": ["Meeting"], "properties": {
                "id": mid, "meeting_date": date, "title": "Board of Supervisors 2030", "clip_id": str(clip),
                "institution_id": ORG[BOS]}},
                {"id": rid, "labels": ["Record"], "properties": {
                    "id": rid, "record_type": "meeting_minutes",
                    "source_url": f"//marin.granicus.com/MinutesViewer.php?view_id=33&clip_id={clip}&doc_id=d{clip}"}}]
            self.edges.append({"start_id": mid, "end_id": rid, "type": "EVIDENCED_BY", "properties": {}})
        self.nodes += [{"id": f"person-pat-{k.lower()}", "labels": ["Person"],
                        "properties": {"id": f"person-pat-{k.lower()}", "name": f"Pat {k.title()}"}} for k in MEMBERS]
        self.export = self.write_export("export", self.nodes, self.edges)
        self._part_a_and_b2()
        rl.init_config(self.refresh, part_a=self.tmp / "votes", votes_b=self.tmp / "votes-b")

    def write_export(self, name, nodes, edges):
        from case_additive_plan import write_export
        d = self.tmp / name
        write_export(d, nodes, edges)  # export_live_graph --backup's byte format
        return d

    def _part_a_and_b2(self):
        raw, part_a = self.tmp / "raw", self.tmp / "votes"
        old = []
        terms = {BOS: [], NOV: []}
        for body, n in ((BOS, "1"), (NOV, "2")):
            mid = f"meeting-{body}-{n}"
            (raw / body / "minutes").mkdir(parents=True)
            (raw / body / "minutes" / f"{mid}.html").write_text(
                f"<html><body><p>Present: {' '.join(f'Supervisor {m.title()}' for m in MEMBERS)} ({body}).</p>"
                "</body></html>")
            old.append({"id": mid, "labels": ["Meeting"], "properties": {"id": mid, "meeting_date": "2020-01-07",
                                                                          "title": "Council"}})
            for k in (MEMBERS if body == BOS else ("ALDER",)):
                terms[body].append({"draft_id": f"{body[:3]}-{k.lower()}", "member": f"Pat {k.title()}", "key": k,
                                    "seat": "District 1", "start": "2019-01-01", "end": None, "start_kind": "window",
                                    "basis": "x", "confidence": "high", "notes": "", "evidence": [
                                        {"source": f"minutes:{mid}", "quote": f"Supervisor {k.title()}",
                                         "supports": ["start", "seat"]}]})
        exp = self.write_export("old-export", old, [])
        inv = build_inventory(exp, raw, self.tmp / "fetched", {BOS: ("2019-01-01", "2026-03-20"),
                                                               NOV: ("2019-01-01", "2026-03-10")})
        write_inventory(inv, part_a / "inventory")
        roster = part_a / "roster"
        roster.mkdir()
        drafts = {b: {"body": b, "terms": t} for b, t in terms.items()}
        (roster / "drafts.json").write_text(json.dumps(drafts))
        items = [{"item": str(i + 1), "draft_id": t["draft_id"], "body": b}
                 for i, (b, t) in enumerate((b, t) for b in sorted(drafts) for t in drafts[b]["terms"])]
        (roster / "batch-001.json").write_text(json.dumps({"batch": "roster-001", "items": items}))
        (roster / "answers-001.txt").write_text("batch roster-001\n" + "".join(f"{i['item']} confirm\n" for i in items))
        (part_a / "ledger").mkdir()
        (part_a / "ledger" / "build.json").write_text(json.dumps({"roster_drafts_sha256": _sha(roster / "drafts.json")}))
        vb = self.tmp / "votes-b"
        (vb / "mapping").mkdir(parents=True)
        by_draft = {t["draft_id"]: t for b in drafts for t in drafts[b]["terms"]}
        rows = [{"item": i["item"], "draft_id": i["draft_id"], "body": i["body"], "key": by_draft[i["draft_id"]]["key"],
                 "member": by_draft[i["draft_id"]]["member"], "term_start": "2019-01-01", "term_end": None,
                 "status": "mapped", "person_id": f"person-pat-{by_draft[i['draft_id']]['key'].lower()}",
                 "provenance": [], "alternates": [], "reviewer_basis": "fixture", "notes": ""} for i in items]
        (vb / "mapping" / "mapping.json").write_text(json.dumps({"batch": "map-001", "rows": rows}))
        hashes = {"mapping.json": _sha(vb / "mapping/mapping.json"), "drafts.json": _sha(roster / "drafts.json"),
                  "batch-001.json": _sha(roster / "batch-001.json"), "answers-001.txt": _sha(roster / "answers-001.txt")}
        (vb / "mapping" / "batch-map-001.json").write_text(json.dumps({"batch": "map-001", "inputs": hashes, "items": [
            {"item": r["item"], "draft_id": r["draft_id"], "options": ["confirm"]} for r in rows]}))
        (vb / "mapping" / "answers-map-001.txt").write_text("batch map-001\n" + "".join(f"{r['item']} confirm\n"
                                                                                         for r in rows))
        (vb / "plan").mkdir()
        (vb / "plan" / "ops.json").write_text(json.dumps({"add_nodes": []}))
        (vb / "plan" / "approval-inputs.json").write_text(json.dumps({"files": {"plan/ops.json": {
            "path": str(vb / "plan/ops.json"), "sha256": _sha(vb / "plan/ops.json")}}}))
        (vb / "state.json").write_text(json.dumps({"state": "APPLIED",
                                                   "approval_sha256": _sha(vb / "plan/approval-inputs.json")}))

    def save(self, clip, text=None, day="2030-05-10", ext="html"):
        p = self.repo / "data/raw/manual" / day / "minutes" / BOS / f"meeting-{BOS}-{clip}.{ext}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text or minutes(clip))
        return p

    def prepare(self, **kw):
        return vr.prepare(kw.pop("export", self.export), self.repo, self.refresh, today="2030-05-11", **kw)

    def rev(self, batch="batch-001", rev=1):
        return vr.rev_dir(self.refresh, batch, rev)

    def review_all_agree(self, batch="batch-001", rev=1):
        sheet = (self.rev(batch, rev) / "spot-check.md").read_text()
        items = [ln.split(". ")[0][4:] for ln in sheet.splitlines() if ln.startswith("### S")]
        p = self.tmp / f"review-{batch}-{rev}.md"
        p.write_text(f"Sheet sha256: {hashlib.sha256(sheet.encode()).hexdigest()}\n"
                     + "".join(f"{i} agree\n" for i in items))
        return p

    def bake_check(self, batch="batch-001", rev=1):
        d = self.rev(batch, rev)
        report = json.loads((d / "plan" / "plan-report.json").read_text())
        p = self.tmp / f"bake-{batch}-{rev}.json"
        p.write_text(json.dumps({"problems": [], "candidate_sha256": report["candidate_sha256"],
                                 "bundle_sha256": fingerprint(d / "bundle"), "baseline_sha256": fingerprint(self.export),
                                 "targets_sha256": _sha(d / "plan" / "targets.json")}))
        return p

    def approve(self, batch="batch-001", rev=1):
        return vr.approve(self.refresh, batch, review=self.review_all_agree(batch, rev), bake_check=self.bake_check(batch, rev))

    def apply(self, graph, batch="batch-001", rev=1):
        d = self.rev(batch, rev)
        canonical = self.tmp / "canonical"
        canonical.mkdir(exist_ok=True)
        return votes_apply.run_apply(d, approve=votes_apply.approval_sha(d), canonical_root=canonical,
                                     uri="bolt://localhost:7688", driver_factory=lambda: graph, database="neo4j")

    def graph(self, **kw):
        nodes = [json.loads(x) for x in (self.export / "nodes.jsonl").read_text().splitlines()]
        edges = [json.loads(x) for x in (self.export / "edges.jsonl").read_text().splitlines()]
        return FakeGraph(nodes, edges, **kw)

    def journal(self):
        p = self.refresh / "applied.jsonl"
        return p.read_bytes() if p.exists() else b""


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


class TestStates:
    def test_nothing_saved_is_awaiting_minutes(self, w):
        assert w.prepare()["state"] == "AWAITING_MINUTES"
        assert "meeting-marin-county-bos-7001" in (w.refresh / "todo.md").read_text()

    def test_nothing_known_is_nothing_eligible(self, w):
        empty = w.write_export("empty", [], [])
        assert w.prepare(export=empty)["state"] == "NOTHING_ELIGIBLE"

    def test_a_batch_awaits_review_then_apply(self, w):
        w.save(7001)
        out = w.prepare()
        assert (out["state"], out["batch"], out["attached"]) == ("AWAITING_REVIEW", "batch-001", 2)
        d = w.rev()
        assert json.loads((d / "plan" / "plan-report.json").read_text())["verification"] == []
        assert json.loads((d / "plan" / "targets.json").read_text())["targets"][0].startswith("vev-marin-county-bos-7001-")
        sheet = (d / "spot-check.md").read_text()
        assert sheet.startswith("# Votes refresh batch-001 rev-1 spot check")
        assert sheet.count("### S") == 2  # min(10, 2) random + every no/abstain/recused (already picked)
        sha = w.approve()
        assert votes_apply.get_state(d) == "AWAITING_APPLY" and sha == votes_apply.approval_sha(d)
        files = json.loads((d / "plan" / "approval-inputs.json").read_text())["files"]
        assert {"plan/targets.json", "baseline/edges.jsonl", "manifest.json", vr.MARKER} <= set(files)

    def test_hold_everything_is_all_held_or_roster_review_and_cannot_be_approved(self, w):
        w.save(7001, minutes(7001, members=("ALDER", "BIRCH", "CEDAR", "DOGWOOD", "FIR")))
        out = w.prepare()
        assert out["state"] == "AWAITING_ROSTER_REVIEW" and out["attached"] == 0
        assert [h["key"] for h in out["new_holds"]] == ["FIR"]
        packet = (w.refresh / "roster-holds" / f"{out['new_holds'][0]['hold_id']}.md").read_text()
        assert "`FIR`" in packet and "dismiss:" in packet
        with pytest.raises(vr.RefreshError, match="AWAITING_REVIEW"):
            vr.approve(w.refresh, "batch-001", review=w.tmp / "x", bake_check=w.tmp / "y")


class TestBacklogOverTime:
    def test_partial_save_then_an_older_meeting_saved_later(self, w):
        w.save(7002)
        assert w.prepare()["batch"] == "batch-001"
        w.save(7001, day="2030-05-12")
        out = w.prepare()
        assert out["batch"] == "batch-002" and out["attached"] == 2
        claims = [r for r in vr.Registry(w.refresh).records() if r["kind"] == "batch"]
        assert [[c["meeting_id"] for c in r["claims"]] for r in claims] == [
            [f"meeting-{BOS}-7002"], [f"meeting-{BOS}-7001"]]

    def test_a_different_file_for_a_claimed_slot_is_held_across_a_restart(self, w):
        w.save(7001)
        w.prepare()
        w.save(7001, minutes(7001, "<p>An extra paragraph.</p>"), day="2030-05-12")
        # a new process: nothing in memory, only the registry on disk
        out = subprocess.run([sys.executable, "-c", (
            "import sys, json; sys.path.insert(0, %r); import votes_refresh as vr; "
            "print(json.dumps(vr.prepare(%r, %r, %r, today='2030-05-13'), default=str))") % (
            str(Path(vr.__file__).parent), str(w.export), str(w.repo), str(w.refresh))],
            capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert json.loads(out.stdout)["state"] == "AWAITING_MINUTES"  # nothing new to take: 7001 is prepared
        conflicts = [r for r in vr.Registry(w.refresh).records() if r["kind"] == "conflict"]
        assert [c["meeting_id"] for c in conflicts] == [f"meeting-{BOS}-7001"]
        assert len([p for p in w.refresh.glob("batches/*")]) == 1

    def test_a_second_file_for_an_applied_slot_is_held(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        assert w.apply(w.graph()) == "APPLIED"
        assert [a["meeting_id"] for a in map(json.loads, w.journal().decode().splitlines())] == [f"meeting-{BOS}-7001"]
        w.save(7001, minutes(7001, "<p>Corrected minutes.</p>"), day="2030-06-01")
        row = {r["meeting_id"]: r for r in vr.backlog(w.export, w.repo, w.refresh)[BOS]}[f"meeting-{BOS}-7001"]
        assert row["state"] == "applied" and row["conflicts"][0]["reason"] == "document_version_conflict"
        assert w.prepare()["state"] == "AWAITING_MINUTES"


class TestRosterHoldsAcrossBatches:
    def test_a_hold_from_batch_a_holds_batch_b_including_an_older_document_arriving_later(self, w):
        resign = "<p>Supervisor Elm resigned from the Board of Supervisors effective May 1.</p>"
        w.save(7002, minutes(7002, resign))
        a = w.prepare()
        assert [h["signal"] for h in a["new_holds"]] == ["resignation"] and a["state"] == "AWAITING_ROSTER_REVIEW"
        w.save(7003, day="2030-05-12")
        b = w.prepare()
        assert b["batch"] == "batch-002" and b["attached"] == 0  # 7003 is after the hold's from-date
        w.save(7001, day="2030-05-13")  # older than the hold: attaches
        c = w.prepare()
        assert c["batch"] == "batch-003" and c["attached"] == 2

    def test_a_dismissed_hold_lets_a_revision_attach(self, w):
        w.save(7001, minutes(7001, members=("ALDER", "BIRCH", "CEDAR", "DOGWOOD", "ELM", "FIR")))
        out = w.prepare()
        hid = out["new_holds"][0]["hold_id"]
        (w.refresh / "roster-holds" / "resolutions.txt").write_text(f"{hid} dismiss: a misprint of ELM\n")
        rev2 = w.prepare(batch="batch-001")
        assert (rev2["rev"], rev2["state"]) == (2, "AWAITING_REVIEW")

    def test_a_hold_recorded_after_approval_refuses_the_apply(self, w):
        w.save(7002)
        w.prepare()
        w.approve()
        w.save(7001, minutes(7001, "<p>Supervisor Elm resigned from the Board of Supervisors.</p>"), day="2030-05-12")
        assert w.prepare()["new_holds"]  # from 2030-04-09, before batch-001's 2030-04-23 votes
        with pytest.raises(votes_apply.ApplyRefused, match="roster hold"):
            w.apply(w.graph())


class TestApplyOutcomes:
    def test_apply_unverified_blocks_the_next_prepare_and_journal_is_unchanged(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        before = w.journal()
        assert w.apply(w.graph(commit_raises_after_commit=True)) == "APPLY_UNVERIFIED"
        assert w.journal() == before  # an uncertain commit is never journaled
        w.save(7002, day="2030-05-12")
        out = w.prepare()
        assert out["state"] == "BLOCKED" and "unresolved" in out["blocked"][BOS][0]
        assert w.journal() == before

    def test_a_crash_after_commit_leaves_apply_in_progress_which_blocks(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        g = w.graph()

        class Crash(BaseException):
            pass

        def exporter(driver, *, out_dir, **kw):
            if Path(out_dir).name == "post-apply-export":
                raise Crash()  # the process dies right after the commit
            from export_live_graph import export_live_graph
            return export_live_graph(driver, out_dir=out_dir, **kw)
        d = w.rev()
        with pytest.raises(Crash):
            votes_apply.run_apply(d, approve=votes_apply.approval_sha(d), canonical_root=w.tmp, uri="bolt://localhost:7688",
                                  driver_factory=lambda: g, database="neo4j", exporter=exporter)
        assert votes_apply.get_state(d) == "APPLY_IN_PROGRESS"
        assert vr.blocked(w.refresh, vr.Registry(w.refresh).records())[BOS]
        # resolve proves the outcome against the live graph (here: the fake, which did commit)
        assert vr.resolve(w.refresh, "batch-001", canonical_root=w.tmp, driver_factory=lambda: g) == "APPLIED"
        assert [json.loads(x)["meeting_id"] for x in w.journal().decode().splitlines()] == [f"meeting-{BOS}-7001"]

    def test_resolve_after_a_rollback_releases(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        g = w.graph(commit_raises_before=True)
        assert w.apply(g) == "APPLY_UNVERIFIED"
        assert vr.resolve(w.refresh, "batch-001", canonical_root=w.tmp, driver_factory=lambda: g) == "ROLLED_BACK"
        assert w.journal() == b""
        assert vr.batch_states(w.refresh, vr.Registry(w.refresh).records())["batch-001"]["released"]

    def test_prepare_never_touches_the_journal(self, w):
        w.save(7001)
        w.prepare()
        assert w.journal() == b""


class TestRevisions:
    def test_a_reviewer_hold_makes_a_new_revision_and_voids_the_old_approval(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        first = sorted(x["event_id"] for x in vr._read_jsonl(w.rev() / "bundle" / "dispositions.jsonl"))[0]
        holds = w.tmp / "reviewer-holds.json"
        holds.write_text(json.dumps({"holds": [{"event_id": first, "reason": "S1: wrong item"}]}))
        out = w.prepare(batch="batch-001", reviewer_holds=holds)
        assert (out["rev"], out["attached"]) == (2, 1)
        with pytest.raises(votes_apply.ApplyRefused, match="current revision"):
            w.apply(w.graph(), rev=1)

    def test_an_applied_batch_cannot_be_revised_or_abandoned(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        w.apply(w.graph())
        with pytest.raises(vr.RefreshError, match="cannot be revised"):
            w.prepare(batch="batch-001")
        with pytest.raises(vr.RefreshError, match="cannot be abandoned"):
            vr.abandon(w.refresh, "batch-001")

    def test_an_abandoned_batch_frees_its_meeting_for_the_same_file_only(self, w):
        w.save(7001)
        w.prepare()
        vr.abandon(w.refresh, "batch-001")
        out = w.prepare()
        assert out["batch"] == "batch-002" and out["attached"] == 2

    def test_corrupt_state_blocks_and_cannot_be_revised(self, w):
        w.save(7001)
        w.prepare()
        (w.rev() / "state.json").write_text("{torn")
        assert "no readable state" in vr.blocked(w.refresh, vr.Registry(w.refresh).records())[BOS][0]
        with pytest.raises(vr.RefreshError, match="cannot be revised"):
            w.prepare(batch="batch-001")


class TestDeterminismAndOffline:
    def test_two_prepares_of_the_same_inputs_are_byte_identical(self, w):
        w.save(7001)
        w.prepare()
        assert vr.check_revision(w.refresh, w.repo, "batch-001", 1) == []

    def test_check_catches_a_changed_artifact(self, w):
        w.save(7001)
        w.prepare()
        (w.rev() / "bundle" / "dispositions.jsonl").write_text("{}\n")
        assert any("dispositions.jsonl" in p for p in vr.check_revision(w.refresh, w.repo, "batch-001", 1))

    def test_prepare_makes_no_network_request(self, w, monkeypatch):
        def refuse(*a, **k):
            raise AssertionError("network request during prepare")
        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)
        w.save(7001)
        assert w.prepare()["state"] == "AWAITING_REVIEW"


def test_the_cli_runs_prepare_status_check_and_refuses_cleanly(w, capsys):
    w.save(7001)
    common = ["--refresh-root", str(w.refresh), "--repo-root", str(w.repo), "--today", "2030-05-11"]
    assert vr.main(["prepare", "--export", str(w.export), *common]) == 0
    assert '"state": "AWAITING_REVIEW"' in capsys.readouterr().out
    assert vr.main(["status", "--export", str(w.export), *common]) == 0
    assert "batch-001 rev-1: AWAITING_REVIEW" in capsys.readouterr().out
    assert vr.main(["check", "--batch", "batch-001", "--rev", "1", *common]) == 0
    assert vr.main(["abandon", "--batch", "batch-009", *common]) == 1
    assert "REFUSED" in capsys.readouterr().err
