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
        assert vr.resolve(w.refresh, "batch-001", canonical_root=w.tmp, driver_factory=lambda: g,
                          uri="bolt://localhost:7688") == "APPLIED"
        assert [json.loads(x)["meeting_id"] for x in w.journal().decode().splitlines()] == [f"meeting-{BOS}-7001"]

    def test_resolve_after_a_rollback_releases(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        g = w.graph(commit_raises_before=True)
        assert w.apply(g) == "APPLY_UNVERIFIED"
        assert vr.resolve(w.refresh, "batch-001", canonical_root=w.tmp, driver_factory=lambda: g,
                          uri="bolt://localhost:7688") == "ROLLED_BACK"
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

    def test_unreadable_state_before_approval_is_a_crashed_preparation(self, w):
        w.save(7001)
        w.prepare()
        (w.rev() / "state.json").write_text("{torn")
        assert vr.batch_states(w.refresh, vr.Registry(w.refresh).records())["batch-001"]["state"] == "PREPARING"
        assert BOS not in vr.blocked(w.refresh, vr.Registry(w.refresh).records())
        assert w.prepare(batch="batch-001")["state"] == "AWAITING_REVIEW"  # rev-2

    def test_unreadable_state_after_approval_blocks_until_resolved(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        (w.rev() / "state.json").write_text("{torn")
        assert "no readable state" in vr.blocked(w.refresh, vr.Registry(w.refresh).records())[BOS][0]
        with pytest.raises(vr.RefreshError, match="cannot be revised"):
            w.prepare(batch="batch-001")
        with pytest.raises(vr.RefreshError, match="cannot be abandoned"):
            vr.abandon(w.refresh, "batch-001")
        g = w.graph()  # nothing was applied: the live graph is the baseline
        assert vr.resolve(w.refresh, "batch-001", canonical_root=w.tmp, driver_factory=lambda: g,
                          uri="bolt://localhost:7688") == "ROLLED_BACK"
        assert list(w.rev().glob("state.json.unreadable-*"))  # the torn file is kept, never parsed


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



class TestCodexD1:
    def test_resolve_refuses_another_server_and_unapproved_inputs(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        assert w.apply(w.graph(commit_raises_after_commit=True)) == "APPLY_UNVERIFIED"
        with pytest.raises(vr.RefreshError, match="7688"):
            vr.resolve(w.refresh, "batch-001", canonical_root=w.tmp, driver_factory=w.graph,
                       uri="bolt://elsewhere:7688")
        report = w.rev() / "plan" / "plan-report.json"
        report.write_text(report.read_text().replace('"verification": []', '"verification": [] '))
        with pytest.raises(vr.RefreshError, match="plan/plan-report.json changed"):
            vr.resolve(w.refresh, "batch-001", canonical_root=w.tmp, driver_factory=w.graph,
                       uri="bolt://localhost:7688")

    def test_an_unresolved_batch_blocks_revising_approving_and_applying_another_of_its_body(self, w):
        w.save(7001)
        w.save(7002, day="2030-05-12")
        w.prepare()  # batch-001 takes both
        vr.abandon(w.refresh, "batch-001")
        w.prepare()  # batch-002: both again (same files)
        # make batch-001's revision look like an apply in flight, by hand-crafted approval (as if approved then crashed)
        assert vr.batch_states(w.refresh, vr.Registry(w.refresh).records())["batch-002"]["state"] == "AWAITING_REVIEW"
        votes_apply.set_state(w.rev("batch-001"), "APPLY_IN_PROGRESS", approval_sha256="0" * 64)
        reg = vr.Registry(w.refresh)
        with reg.locked():
            reg.append({"kind": "claim", "batch": "batch-001", "meeting_id": "meeting-x", "slot": "minutes",
                        "sha256": "f" * 64})  # un-release batch-001 without touching batch-002's slots
        with pytest.raises(vr.RefreshError, match="cannot be revised while"):
            w.prepare(batch="batch-002")
        with pytest.raises(vr.RefreshError, match="blocked"):
            w.approve(batch="batch-002")

    def test_a_crash_between_claim_and_build_leaves_preparing_which_can_be_abandoned(self, w, monkeypatch):
        w.save(7001)

        def boom(*a, **k):
            raise RuntimeError("the build died")
        monkeypatch.setattr(vr, "build_revision", boom)
        with pytest.raises(RuntimeError):
            w.prepare()
        st = vr.batch_states(w.refresh, vr.Registry(w.refresh).records())["batch-001"]
        assert st["state"] == "PREPARING" and BOS not in vr.blocked(w.refresh, vr.Registry(w.refresh).records())
        monkeypatch.undo()
        assert w.prepare(batch="batch-001")["state"] == "AWAITING_REVIEW"

    def test_a_revision_keeps_the_reviewer_holds_unless_replaced(self, w):
        w.save(7001)
        w.prepare()
        first = sorted(x["event_id"] for x in vr._read_jsonl(w.rev() / "bundle" / "dispositions.jsonl"))[0]
        holds = w.tmp / "rh.json"
        holds.write_text(json.dumps({"holds": [{"event_id": first, "reason": "S1: wrong item"}]}))
        assert w.prepare(batch="batch-001", reviewer_holds=holds)["attached"] == 1
        rebased = w.write_export("export2", w.nodes, w.edges)
        assert w.prepare(batch="batch-001", export=rebased)["attached"] == 1  # rev-3 keeps the hold
        empty = w.tmp / "none.json"
        empty.write_text(json.dumps({"holds": []}))
        assert w.prepare(batch="batch-001", reviewer_holds=empty)["attached"] == 2  # an explicit replacement

    def test_the_journal_completes_per_slot_after_an_interrupted_sync(self, w):
        w.save(7001)
        w.save(7002, day="2030-05-12")
        w.prepare()
        w.approve()
        assert w.apply(w.graph()) == "APPLIED"
        lines = w.journal().decode().splitlines()
        assert len(lines) == 2
        (w.refresh / "applied.jsonl").write_text(lines[0] + "\n" + lines[1][:20])  # crash mid-append
        reg = vr.Registry(w.refresh)
        with reg.locked():
            vr.sync_journal(w.refresh, reg)
        again = w.journal().decode().splitlines()
        assert again == lines and list(w.refresh.glob("applied.tail-*.quarantine"))

    def test_approval_refuses_a_sheet_that_is_not_the_deterministic_sample(self, w):
        w.save(7001)
        w.prepare()
        sheet = w.rev() / "spot-check.md"
        sheet.write_text(sheet.read_text().split("### S2.")[0])  # an item removed
        with pytest.raises(vr.RefreshError, match="deterministic sample"):
            w.approve()

    def test_check_after_approval_and_its_pins(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        assert vr.check_revision(w.refresh, w.repo, "batch-001", 1) == []  # approval metadata is not a build output
        m = vr.manifest_path(w.refresh, "batch-001", 1)
        m.write_text(m.read_text().replace('"rev": 1', '"rev": 1 '))
        assert "not the one the registry recorded" in vr.check_revision(w.refresh, w.repo, "batch-001", 1)[0]

    def test_two_prepares_in_separate_roots_are_byte_identical(self, w, tmp_path):
        import shutil
        w.save(7001)
        other = tmp_path / "refresh-2"
        other.mkdir()
        shutil.copy(w.refresh / "config.json", other / "config.json")
        w.prepare()
        vr.prepare(w.export, w.repo, other, today="2030-05-11")
        a, b = w.rev(), vr.rev_dir(other, "batch-001", 1)
        files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file() and p.name != "state.json")
        assert files == sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file() and p.name != "state.json")
        assert [f for f in files if (a / f).read_bytes() != (b / f).read_bytes()] == []


class TestFixtureCoverage:
    def test_all_held_and_its_revision(self, w):
        w.save(7001)
        w.prepare()
        ids = sorted(x["event_id"] for x in vr._read_jsonl(w.rev() / "bundle" / "dispositions.jsonl"))
        holds = w.tmp / "rh.json"
        holds.write_text(json.dumps({"holds": [{"event_id": e, "reason": "S: doubt"} for e in ids]}))
        assert w.prepare(batch="batch-001", reviewer_holds=holds)["state"] == "ALL_HELD"
        holds.write_text(json.dumps({"holds": [{"event_id": ids[0], "reason": "S: doubt"}]}))
        assert w.prepare(batch="batch-001", reviewer_holds=holds)["state"] == "AWAITING_REVIEW"

    def test_wrong_meeting_and_same_day_session_files_stay_pending(self, w):
        w.save(7001, minutes(7001).replace("APRIL 9, 2030", "APRIL 16, 2030"))
        w.save(7002, minutes(7002).replace("clip_id=7002", "clip_id=7001"))
        assert w.prepare()["state"] == "AWAITING_MINUTES"
        todo = (w.refresh / "todo.md").read_text()
        assert "heading_date_mismatch:2030-04-16" in todo and "clip_id_mismatch:7001" in todo

    def test_a_quoted_resignation_holds_nothing(self, w):
        w.save(7001, minutes(7001, "<p>Public comment: a speaker said “I resigned from the Board of Supervisors.”</p>"))
        out = w.prepare()
        assert out["new_holds"] == [] and out["attached"] == 2

    def test_zero_usable_roll_calls_is_insufficient_evidence(self, w):
        w.save(7001, minutes(7001).replace("<p>Roll Call</p>", "").replace("Present: ", "Seen: "))
        w.prepare()
        assert json.loads((w.rev() / "hints.json").read_text())[BOS]["evidence"] == "insufficient evidence"

    def test_an_older_document_arriving_later_but_after_the_hold_is_held(self, w):
        resign = "<p>Supervisor Elm resigned from the Board of Supervisors effective May 1.</p>"
        w.save(7001, minutes(7001, resign))
        w.save(7003)
        w.prepare()  # the hold dates from 2030-04-09; 7003 (2030-05-07) held with it
        w.save(7002, day="2030-05-12")  # 2030-04-23: older than 7003, arriving later, after the hold
        out = w.prepare()
        assert out["batch"] == "batch-002" and out["attached"] == 0

    def test_a_process_killed_right_after_commit_leaves_apply_in_progress(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        d = w.rev()
        script = f"""
import os, sys, json
sys.path[:0] = [{str(Path(vr.__file__).parent)!r}, {str(Path(__file__).parent)!r}]
import votes_apply
from test_votes_apply import FakeGraph
nodes = [json.loads(x) for x in open({str(w.export / 'nodes.jsonl')!r})]
edges = [json.loads(x) for x in open({str(w.export / 'edges.jsonl')!r})]
g = FakeGraph(nodes, edges)
real = votes_apply.export_live_graph
def exporter(driver, *, out_dir, **kw):
    if str(out_dir).endswith("post-apply-export"):
        os._exit(9)  # killed right after the commit
    return real(driver, out_dir=out_dir, **kw)
votes_apply.run_apply({str(d)!r}, approve=votes_apply.approval_sha({str(d)!r}), canonical_root={str(w.tmp)!r},
                      uri="bolt://localhost:7688", driver_factory=lambda: g, database="neo4j", exporter=exporter)
"""
        out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        assert out.returncode == 9, out.stderr
        assert votes_apply.get_state(d) == "APPLY_IN_PROGRESS"
        assert w.journal() == b""
        assert "unresolved" in vr.blocked(w.refresh, vr.Registry(w.refresh).records())[BOS][0]
        cand = [json.loads(x) for x in (d / "plan/candidate/nodes.jsonl").read_text().splitlines()]
        cand_e = [json.loads(x) for x in (d / "plan/candidate/edges.jsonl").read_text().splitlines()]
        live = FakeGraph(cand, cand_e)  # the graph as the killed process left it: committed
        assert vr.resolve(w.refresh, "batch-001", canonical_root=w.tmp, driver_factory=lambda: live,
                          uri="bolt://localhost:7688") == "APPLIED"
        assert len(w.journal().decode().splitlines()) == 1

    def test_a_state_write_interrupted_before_replace_leaves_the_old_state(self, w, monkeypatch):
        w.save(7001)
        w.prepare()
        before = (w.rev() / "state.json").read_bytes()

        def die(*a):
            raise KeyboardInterrupt
        monkeypatch.setattr(votes_apply.os, "replace", die)
        with pytest.raises(KeyboardInterrupt):
            votes_apply.set_state(w.rev(), "ALL_HELD")
        assert (w.rev() / "state.json").read_bytes() == before

    def test_a_concurrent_prepare_is_refused_while_another_holds_the_lock(self, w):
        holder = subprocess.Popen([sys.executable, "-c", (
            "import sys, time; sys.path.insert(0, %r); import votes_refresh as vr\n"
            "with vr.Registry(%r).locked():\n    print('held', flush=True); time.sleep(30)") % (
            str(Path(vr.__file__).parent), str(w.refresh))], stdout=subprocess.PIPE, text=True)
        try:
            assert holder.stdout.readline().strip() == "held"
            w.save(7001)
            with pytest.raises(vr.RefreshError, match="locked by another"):
                w.prepare()
        finally:
            holder.kill()
            holder.wait()

    def test_a_rebase_voids_the_old_revisions_approval(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        rebased = w.write_export("export2", w.nodes, w.edges)
        w.prepare(batch="batch-001", export=rebased)
        with pytest.raises(votes_apply.ApplyRefused, match="current revision"):
            w.apply(w.graph(), rev=1)



class TestCodexD2:
    def test_the_approval_anchor_exists_before_the_batch_can_be_applied(self, w, monkeypatch):
        w.save(7001)
        w.prepare()
        real = vr.Registry.append

        def crash_on_anchor(self, record):
            if record["kind"] == "approved":
                raise KeyboardInterrupt  # the process dies writing the anchor
            return real(self, record)
        monkeypatch.setattr(vr.Registry, "append", crash_on_anchor)
        with pytest.raises(KeyboardInterrupt):
            w.approve()
        monkeypatch.undo()
        assert votes_apply.get_state(w.rev()) != "AWAITING_APPLY"  # never applyable without its anchor
        with pytest.raises(votes_apply.ApplyRefused):
            w.apply(w.graph())

    def test_apply_requires_the_anchor_to_be_the_approval_on_disk(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        reg = vr.Registry(w.refresh)
        with reg.locked():
            reg.append({"kind": "approved", "batch": "batch-001", "rev": 1, "approval_sha256": "0" * 64})
        with pytest.raises(votes_apply.ApplyRefused, match="anchor"):
            w.apply(w.graph())

    def test_the_journal_is_written_from_approved_bytes_only(self, w):
        w.save(7001)
        w.prepare()
        w.approve()
        assert w.apply(w.graph()) == "APPLIED"
        (w.refresh / "applied.jsonl").write_text("")
        disp = w.rev() / "bundle" / "dispositions.jsonl"
        disp.write_text(disp.read_text().replace("meeting-marin-county-bos-7001", "meeting-INJECTED"))
        reg = vr.Registry(w.refresh)
        with reg.locked():
            out = vr.sync_journal(w.refresh, reg)
        assert w.journal() == b"" and any("changed" in x for x in out)

    def test_duplicate_sheet_labels_and_answers_are_refused(self, w):
        w.save(7001)
        w.prepare()
        sheet = w.rev() / "spot-check.md"
        sheet.write_text(sheet.read_text().replace("### S2.", "### S1."))
        with pytest.raises(vr.RefreshError, match="deterministic sample"):
            w.approve()

    def test_a_review_answering_an_item_twice_is_refused(self, w):
        w.save(7001)
        w.prepare()
        review = w.review_all_agree()
        review.write_text(review.read_text() + "S1 disagree: second thoughts\n")
        with pytest.raises(vr.RefreshError, match="answered more than once"):
            vr.approve(w.refresh, "batch-001", review=review, bake_check=w.bake_check())

    def test_set_state_quarantines_a_malformed_history(self, w):
        w.save(7001)
        w.prepare()
        (w.rev() / "state.json").write_text(json.dumps({"state": "AWAITING_REVIEW", "history": None}))
        votes_apply.set_state(w.rev(), "ALL_HELD")
        assert votes_apply.get_state(w.rev()) == "ALL_HELD" and list(w.rev().glob("state.json.unreadable-*"))



class TestCodexD3:
    def test_any_extra_or_malformed_heading_is_refused(self, w):
        w.save(7001)
        w.prepare()
        sheet = w.rev() / "spot-check.md"
        sheet.write_text(sheet.read_text() + "\n### S1. held-event (note)\n")
        with pytest.raises(vr.RefreshError, match="deterministic sample"):
            w.approve()

    @pytest.mark.parametrize("body", ["null", "[]", '{"state": "SOMETHING_ELSE"}'])
    def test_a_structurally_invalid_state_reads_as_unreadable(self, w, body):
        w.save(7001)
        w.prepare()
        w.approve()
        (w.rev() / "state.json").write_text(body)
        st = vr.batch_states(w.refresh, vr.Registry(w.refresh).records())["batch-001"]
        assert st["state"] is None and "no readable state" in vr.blocked(w.refresh, vr.Registry(w.refresh).records())[BOS][0]
        assert vr.resolve(w.refresh, "batch-001", canonical_root=w.tmp, driver_factory=w.graph,
                          uri="bolt://localhost:7688") == "ROLLED_BACK"
