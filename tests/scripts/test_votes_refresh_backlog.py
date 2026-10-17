"""Votes refresh, increment b: the backlog of known Meetings, the minutes to-do list, saved-file validation, the
durable registry/journal readers, listing freshness and the digest list. All names and documents are fictional."""
import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import votes_refresh as vr  # noqa: E402

NOV, BOS = "novato-city-council", "marin-county-bos"


def _meeting(mid, date, title, clip=None, body=NOV):
    org = vr.BODY_ORG[body]
    return {"id": mid, "labels": ["Meeting"], "properties": {"id": mid, "meeting_date": date, "title": title,
                                                             "institution_id": org,
                                                             **({"clip_id": clip} if clip else {})}}


def _record(rid, **props):
    return {"id": rid, "labels": ["Record"], "properties": {"id": rid, "record_type": "meeting_minutes", **props}}


def _ev(mid, rid):
    return {"start_id": mid, "end_id": rid, "type": "EVIDENCED_BY", "properties": {}}


NOV_URL = "//novato.granicus.com/MinutesViewer.php?view_id=7&clip_id={}&doc_id=aaaa-{}"
BOS_URL = "//marin.granicus.com/MinutesViewer.php?view_id=33&clip_id={}&doc_id=bbbb-{}"


def _export(tmp_path, nodes, edges):
    d = tmp_path / "export"
    d.mkdir(exist_ok=True)
    (d / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    (d / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges))
    return d


def _world(tmp_path):
    """Novato: a regular + closed pair on 2030-04-08 (both with records), one without a record, one before the
    Part A window end; Board: one untyped meeting with a record."""
    nodes = [
        _meeting(f"meeting-{NOV}-901", "2030-04-08", "City Council", "901"),
        _meeting(f"meeting-{NOV}-902", "2030-04-08", "City Council Closed Session (No Video)", "902"),
        _meeting(f"meeting-{NOV}-903", "2030-05-13", "City Council"),
        _meeting(f"meeting-{NOV}-904", "2030-05-20", "Planning Commission"),
        _meeting(f"meeting-{NOV}-800", "2026-03-01", "City Council", "800"),
        _meeting(f"meeting-{BOS}-7001", "2030-04-09", "Board of Supervisors 2030", "7001", body=BOS),
        _record("record-min-901", source_url=NOV_URL.format(901, 1)),
        _record("record-min-902", source_url=NOV_URL.format(902, 2)),
        _record("record-min-800", preferred_public_url="https://novato.granicus.com/MinutesViewer.php?clip_id=800&doc_id=x"),
        _record("record-min-7001", source_url=BOS_URL.format(7001, 1)),
    ]
    edges = [_ev(f"meeting-{NOV}-901", "record-min-901"), _ev(f"meeting-{NOV}-902", "record-min-902"),
             _ev(f"meeting-{NOV}-800", "record-min-800"), _ev(f"meeting-{BOS}-7001", "record-min-7001")]
    return _export(tmp_path, nodes, edges)


def _nov_html(date_text, kind="regular", extra=""):
    head = {"regular": "NOVATO CITY COUNCIL MEETING MINUTES", "closed": "NOVATO CITY COUNCIL CLOSED SESSION MEETING MINUTES",
            "special": "NOVATO CITY COUNCIL SPECIAL MEETING MINUTES"}[kind]
    first = ("A. CONVENE, PLEDGE OF ALLEGIANCE, AND ROLL CALL" if kind != "closed" else "A. CALL TO ORDER")
    return (f"<html><body><p>{head}</p><p>COUNCIL CHAMBERS 1 SAMPLE AVENUE NOVATO, CA</p><p>{date_text} - 6:00 PM</p>"
            f"<p>{first}</p><p>The meeting was called to order. COUNCIL PRESENT: Mayor Alder, Councilmember Birch."
            f"</p><p>{extra}</p></body></html>")


def _bos_html(date_text, clip="7001", kind="REGULAR"):
    return (f"<html><body><a href='MinutesViewer.php?view_id=33&clip_id={clip}'>x</a><p>{kind} MEETING OF THE MARIN "
            f"COUNTY BOARD OF SUPERVISORS HELD TUESDAY, {date_text}, AT 9:00 A.M.</p><p>Roll Call</p>"
            "<p>Present: Supervisor Alder; Supervisor Birch</p></body></html>")


def _save(repo, date, body, mid, text, ext="html"):
    p = repo / "data" / "raw" / "manual" / date / "minutes" / body / f"{mid}.{ext}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text) if isinstance(text, str) else p.write_bytes(text)
    return p


@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "repo"
    (repo / "data" / "ingest-runs").mkdir(parents=True)
    refresh = tmp_path / "refresh"
    refresh.mkdir()
    return repo, _world(tmp_path), refresh


# --- minutes URLs -----------------------------------------------------------------------------------------------

class TestMinutesUrl:
    def test_preferred_url_wins(self):
        assert vr.minutes_url({"preferred_public_url": "https://example.org/m.pdf", "source_url": NOV_URL.format(1, 1)},
                              NOV) == ("https://example.org/m.pdf", None)

    def test_source_url_is_normalized_and_validated(self):
        assert vr.minutes_url({"source_url": NOV_URL.format(901, 1)}, NOV) == (
            "https://novato.granicus.com/MinutesViewer.php?view_id=7&clip_id=901&doc_id=aaaa-1", None)

    @pytest.mark.parametrize("url,reason", [
        ("http://novato.granicus.com/MinutesViewer.php?clip_id=1&doc_id=a", "source_url_not_https"),
        ("https://marin.granicus.com/MinutesViewer.php?clip_id=1&doc_id=a", "source_url_wrong_host"),
        ("https://novato.granicus.com/AgendaViewer.php?clip_id=1&doc_id=a", "source_url_not_minutes_viewer"),
        ("https://novato.granicus.com/MinutesViewer.php?clip_id=x&doc_id=a", "source_url_bad_query"),
        ("https://novato.granicus.com/MinutesViewer.php?clip_id=1&clip_id=2&doc_id=a", "source_url_bad_query"),
        ("https://novato.granicus.com/MinutesViewer.php?clip_id=1", "source_url_bad_query"),
    ])
    def test_bad_source_urls(self, url, reason):
        assert vr.minutes_url({"source_url": url}, NOV) == (None, reason)

    def test_no_url(self):
        assert vr.minutes_url({}, BOS) == (None, "no_minutes_link")


# --- saved-file heading evidence ----------------------------------------------------------------------------------

class TestHeading:
    def _check(self, env, mid, text, ext="html"):
        repo, export, refresh = env
        rows = {r["meeting_id"]: r for r in vr.backlog(export, repo, refresh)[NOV if NOV in mid else BOS]}
        _save(repo, "2030-06-01", NOV if NOV in mid else BOS, mid, text, ext)
        rows = {r["meeting_id"]: r for r in vr.backlog(export, repo, refresh)[NOV if NOV in mid else BOS]}
        return rows[mid]

    def test_regular_minutes_are_accepted(self, env):
        row = self._check(env, f"meeting-{NOV}-901", _nov_html("April 8, 2030"))
        assert row["state"] == "file_saved" and row["file"]["reason"] is None

    def test_closed_session_minutes_for_the_closed_meeting(self, env):
        assert self._check(env, f"meeting-{NOV}-902", _nov_html("April 8, 2030", "closed"))["state"] == "file_saved"

    def test_same_day_closed_session_file_saved_as_the_regular_meeting(self, env):
        row = self._check(env, f"meeting-{NOV}-901", _nov_html("April 8, 2030", "closed"))
        assert row["state"] == "awaiting_file" and row["file"]["reason"] == "heading_session_mismatch:closed≠regular"

    def test_another_meetings_minutes(self, env):
        row = self._check(env, f"meeting-{NOV}-901", _nov_html("April 22, 2030"))
        assert row["file"]["reason"] == "heading_date_mismatch:2030-04-22"

    def test_approval_of_other_minutes_below_the_heading_is_not_evidence(self, env):
        text = ("<html><body><p>NOVATO CITY COUNCIL MEETING MINUTES</p><p>A. CONVENE, PLEDGE OF ALLEGIANCE</p>"
                "<p>Approve the minutes of April 8, 2030.</p></body></html>")
        assert self._check(env, f"meeting-{NOV}-901", text)["file"]["reason"] == "heading_date_missing"

    def test_two_dates_in_the_heading(self, env):
        text = _nov_html("April 8, 2030 and April 9, 2030")
        assert self._check(env, f"meeting-{NOV}-901", text)["file"]["reason"] == "heading_date_ambiguous"

    def test_wrong_jurisdiction(self, env):
        text = _nov_html("April 8, 2030").replace("NOVATO", "SAMPLEVILLE")
        assert self._check(env, f"meeting-{NOV}-901", text)["file"]["reason"] == "heading_jurisdiction_missing"

    def test_the_opening_item_line_after_a_blank_line_proves_a_regular_meeting(self, env):
        text = ("<html><body><p>NOVATO CITY COUNCIL</p><p>MEETING MINUTES</p><p>April 8, 2030 - 6:00 PM</p>"
                "<p></p><p>A.   CONVENE, PLEDGE OF ALLEGIANCE, AND ROLL CALL</p></body></html>")
        assert vr.heading_of("NOVATO CITY COUNCIL\n\nApril 8, 2030\n\n\nA.   CONVENE, PLEDGE OF ALLEGIANCE\n")[1] == \
            "A.   CONVENE, PLEDGE OF ALLEGIANCE"
        assert self._check(env, f"meeting-{NOV}-901", text)["state"] == "file_saved"

    def test_missing_session_evidence(self, env):
        text = ("<html><body><p>NOVATO CITY COUNCIL MINUTES</p><p>April 8, 2030</p><p>A. CALL TO ORDER</p>"
                "</body></html>")
        assert self._check(env, f"meeting-{NOV}-901", text)["file"]["reason"] == "heading_session_unproven"

    def test_combined_sessions(self, env):
        text = _nov_html("April 8, 2030", "closed").replace("A. CALL TO ORDER", "A. CONVENE, PLEDGE OF ALLEGIANCE")
        assert self._check(env, f"meeting-{NOV}-902", text)["file"]["reason"] == "heading_combined_sessions"
        text = _nov_html("April 8, 2030", "special").replace("SPECIAL MEETING", "SPECIAL AND REGULAR MEETING")
        assert self._check(env, f"meeting-{NOV}-901", text)["file"]["reason"] == "heading_combined_sessions"

    def test_regular_and_closed_without_pledge(self, env):
        text = ("<html><body><p>NOVATO CITY COUNCIL REGULAR MEETING AND CLOSED SESSION MINUTES</p>"
                "<p>April 8, 2030</p><p>A. CALL TO ORDER</p></body></html>")
        assert self._check(env, f"meeting-{NOV}-901", text)["file"]["reason"] == "heading_combined_sessions"

    def test_special_minutes_saved_as_a_regular_meeting(self, env):
        assert self._check(env, f"meeting-{NOV}-901", _nov_html("April 8, 2030", "special"))["file"]["reason"] == \
            "heading_session_mismatch:special≠regular"

    def test_untyped_board_meeting_needs_its_clip_id(self, env):
        assert self._check(env, f"meeting-{BOS}-7001", _bos_html("APRIL 9, 2030"))["state"] == "file_saved"
        row = self._check(env, f"meeting-{BOS}-7001", _bos_html("APRIL 9, 2030", clip="7002"))
        assert row["file"]["reason"] == "clip_id_mismatch:7002"
        no_clip = _bos_html("APRIL 9, 2030", kind="SPECIAL").replace("clip_id=7001", "")
        assert self._check(env, f"meeting-{BOS}-7001", no_clip)["file"]["reason"] == "session_identity_unproven"

    def test_other_county_board(self, env):
        text = _bos_html("APRIL 9, 2030").replace("MARIN COUNTY", "SAMPLE COUNTY")
        assert self._check(env, f"meeting-{BOS}-7001", text)["file"]["reason"] == "heading_jurisdiction_missing"

    def test_format_must_match_the_extension(self, env):
        row = self._check(env, f"meeting-{NOV}-901", _nov_html("April 8, 2030"), ext="pdf")
        assert row["file"]["reason"] == "format_mismatch:html≠pdf"

    def test_unreadable_file(self, env):
        assert self._check(env, f"meeting-{NOV}-901", b"\x00\x01garbage", ext="pdf")["file"]["reason"] == \
            "format_mismatch:unknown≠pdf"

    def test_two_files_in_one_save_dir(self, env):
        repo, export, refresh = env
        _save(repo, "2030-06-01", NOV, f"meeting-{NOV}-901", _nov_html("April 8, 2030"))
        row = self._check(env, f"meeting-{NOV}-901", b"%PDF-1.4 x", ext="pdf")
        assert row["file"]["reason"] == "several_files_saved_together"

    def test_newest_save_wins(self, env):
        repo, export, refresh = env
        _save(repo, "2030-05-01", NOV, f"meeting-{NOV}-901", _nov_html("April 22, 2030"))
        row = self._check(env, f"meeting-{NOV}-901", _nov_html("April 8, 2030"))
        assert row["state"] == "file_saved" and row["file"]["saved_on"] == "2030-06-01"


# --- the backlog ----------------------------------------------------------------------------------------------------

class TestBacklog:
    def test_known_meetings_after_the_part_a_window(self, env):
        repo, export, refresh = env
        b = vr.backlog(export, repo, refresh)
        assert [r["meeting_id"] for r in b[NOV]] == [f"meeting-{NOV}-901", f"meeting-{NOV}-902", f"meeting-{NOV}-903"]
        states = {r["meeting_id"]: r["state"] for r in b[NOV]}
        assert states[f"meeting-{NOV}-903"] == "no_minutes_record"
        assert states[f"meeting-{NOV}-901"] == "awaiting_file"
        assert [r["state"] for r in b[BOS]] == ["awaiting_file"]

    def test_target_path_names_the_body_and_meeting(self, env):
        repo, export, refresh = env
        row = vr.backlog(export, repo, refresh, today="2030-06-02")[NOV][0]
        assert row["target"] == f"data/raw/manual/2030-06-02/minutes/{NOV}/meeting-{NOV}-901.<pdf|docx|html>"
        board = vr.backlog(export, repo, refresh, today="2030-06-02")[BOS][0]
        assert board["target"] == f"data/raw/manual/2030-06-02/minutes/{BOS}/meeting-{BOS}-7001.html"

    def test_prepared_and_applied_slots(self, env):
        repo, export, refresh = env
        reg = vr.Registry(refresh)
        with reg.locked():
            reg.append({"kind": "batch", "batch": "batch-001", "bodies": [NOV], "manifest_sha256": "0" * 64,
                        "claims": [{"meeting_id": f"meeting-{NOV}-901", "slot": "minutes", "sha256": "a" * 64}]})
        (refresh / "applied.jsonl").write_text(json.dumps({"batch": "batch-000", "meeting_id": f"meeting-{NOV}-902",
                                                           "slot": "minutes", "sha256": "b" * 64}) + "\n")
        states = {r["meeting_id"]: r["state"] for r in vr.backlog(export, repo, refresh)[NOV]}
        assert states[f"meeting-{NOV}-901"] == "prepared" and states[f"meeting-{NOV}-902"] == "applied"

    def test_a_different_file_for_a_claimed_slot_is_a_version_conflict(self, env):
        repo, export, refresh = env
        reg = vr.Registry(refresh)
        with reg.locked():
            reg.append({"kind": "batch", "batch": "batch-001", "bodies": [NOV], "manifest_sha256": "0" * 64,
                        "claims": [{"meeting_id": f"meeting-{NOV}-901", "slot": "minutes", "sha256": "a" * 64}]})
            reg.append({"kind": "release", "batch": "batch-001", "reason": "abandoned"})
        _save(repo, "2030-06-01", NOV, f"meeting-{NOV}-901", _nov_html("April 8, 2030"))
        row = {r["meeting_id"]: r for r in vr.backlog(export, repo, refresh)[NOV]}[f"meeting-{NOV}-901"]
        # released ownership never frees the slot's identity: only the first file's bytes may ever be parsed
        assert row["state"] == "held" and row["conflicts"][0]["reason"] == "document_version_conflict"


# --- the registry -----------------------------------------------------------------------------------------------

class TestRegistry:
    def test_append_and_reload(self, tmp_path):
        reg = vr.Registry(tmp_path)
        with reg.locked():
            reg.append({"kind": "release", "batch": "batch-001", "reason": "x"})
        assert vr.Registry(tmp_path).records() == [{"kind": "release", "batch": "batch-001", "reason": "x"}]

    def test_append_needs_the_lock(self, tmp_path):
        with pytest.raises(vr.RefreshError, match="lock"):
            vr.Registry(tmp_path).append({"kind": "release", "batch": "b", "reason": "x"})

    def test_a_truncated_tail_is_ignored_then_quarantined_before_the_next_append(self, tmp_path):
        log = tmp_path / "registry.jsonl"
        log.write_text(json.dumps({"kind": "release", "batch": "b1", "reason": "x"}) + "\n" + '{"kind": "rel')
        assert [r["batch"] for r in vr.Registry(tmp_path).records()] == ["b1"]  # read-only: nothing repaired
        assert log.read_text().endswith('{"kind": "rel')
        reg = vr.Registry(tmp_path)
        with reg.locked():
            reg.append({"kind": "release", "batch": "b2", "reason": "y"})
        assert [r["batch"] for r in vr.Registry(tmp_path).records()] == ["b1", "b2"]
        assert list(tmp_path.glob("registry.tail-*.quarantine"))[0].read_text() == '{"kind": "rel'

    def test_a_corrupt_committed_line_refuses(self, tmp_path):
        (tmp_path / "registry.jsonl").write_text("not json\n")
        with pytest.raises(vr.RefreshError, match="corrupt"):
            vr.Registry(tmp_path).records()

    def test_a_second_writer_is_refused_while_the_lock_is_held(self, tmp_path):
        with vr.Registry(tmp_path).locked():
            with pytest.raises(vr.RefreshError, match="locked"):
                with vr.Registry(tmp_path).locked(wait=False):
                    pass


# --- listing freshness, todo, digest ------------------------------------------------------------------------------

def _run(repo, run_id, loaded, captures, saved_pages=None):
    d = repo / "data" / "ingest-runs" / run_id
    d.mkdir(parents=True)
    sources = {sid: {"capture": {"path": f"data/extracted/{sid}/{date}.json", "sha256": "0"}} for sid, date in
               captures.items()}
    (d / "state.json").write_text(json.dumps({"run_id": run_id, "loaded": loaded, "sources": sources,
                                              "saved_pages": saved_pages or {}}))


class TestFreshness:
    def test_newest_loaded_capture_per_body(self, env):
        repo, _, _ = env
        _run(repo, "2030-05-01T120000Z", [NOV, BOS], {NOV: "2030-05-01", BOS: "2030-05-01"})
        _run(repo, "2030-05-20T120000Z", [BOS], {BOS: "2030-05-20", NOV: "2030-05-20"},
             saved_pages={NOV: {"outcome": "missing"}})
        f = vr.listing_freshness(repo, "2030-06-01")
        assert f[NOV] == {"capture_date": "2030-05-01", "age_days": 31, "stale": True, "saved_page": "missing"}
        assert f[BOS] == {"capture_date": "2030-05-20", "age_days": 12, "stale": False, "saved_page": None}

    def test_no_loaded_capture(self, env):
        repo, _, _ = env
        assert vr.listing_freshness(repo, "2030-06-01")[NOV]["capture_date"] is None


class TestTodo:
    def test_todo_lists_pending_meetings_with_urls_and_states_freshness_first(self, env):
        repo, export, refresh = env
        _run(repo, "2030-05-01T120000Z", [NOV, BOS], {NOV: "2030-05-01", BOS: "2030-05-30"})
        out = vr.write_todo(export, repo, refresh, today="2030-06-02")
        md = (refresh / "todo.md").read_text()
        assert md.index("coverage of known Meetings as of 2030-05-01") < md.index("meeting-")
        assert "WARNING: listing stale" in md and "current through" not in md
        items = json.loads((refresh / "todo.json").read_text())["items"]
        assert [i["meeting_id"] for i in items] == [f"meeting-{BOS}-7001", f"meeting-{NOV}-901", f"meeting-{NOV}-902"]
        assert items[1]["url"].startswith("https://novato.granicus.com/MinutesViewer.php")
        assert out["state"] == "AWAITING_MINUTES"
        hist = [json.loads(x) for x in (refresh / "history.jsonl").read_text().splitlines()]
        assert hist[-1]["command"] == "todo" and hist[-1]["bodies"][NOV]["awaiting_file"] == 2

    def test_nothing_eligible(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / "data" / "ingest-runs").mkdir(parents=True)
        (tmp_path / "refresh").mkdir()
        export = _export(tmp_path, [_meeting(f"meeting-{NOV}-800", "2026-03-01", "City Council")], [])
        assert vr.write_todo(export, repo, tmp_path / "refresh", today="2030-06-02")["state"] == "NOTHING_ELIGIBLE"

    def test_todo_makes_no_network_request(self, env, monkeypatch):
        repo, export, refresh = env

        def refuse(*a, **k):
            raise AssertionError("network")
        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)
        vr.write_todo(export, repo, refresh, today="2030-06-02")


class TestDigest:
    def test_snapshot_is_read_only_and_renders(self, env):
        repo, export, refresh = env
        (refresh / "registry.jsonl").write_text('{"kind": "rel')  # an unrepaired tail stays as it is
        before = sorted(p.name for p in refresh.iterdir())
        snap = vr.digest_snapshot(repo, export, refresh, today="2030-06-02")
        assert sorted(p.name for p in refresh.iterdir()) == before
        lines = vr.render_digest_section(snap)
        assert lines[0] == "## Votes minutes to save" and any(f"meeting-{NOV}-901" in x for x in lines)
        assert json.loads(json.dumps(snap)) == snap  # state.json-safe

    def test_snapshot_failure_is_reported_not_raised(self, env):
        repo, _, refresh = env
        snap = vr.digest_snapshot(repo, repo / "missing-export", refresh, today="2030-06-02")
        assert "error" in snap and vr.render_digest_section(snap)[2].startswith("- unavailable")


# --- Codex b-r1 -----------------------------------------------------------------------------------------------------

def _batch(reg, batch, mid, sha, rev=1, manifest="0" * 64):
    reg.append({"kind": "batch", "batch": batch, "rev": rev, "bodies": [NOV], "manifest_sha256": manifest,
                "claims": [{"meeting_id": mid, "slot": "minutes", "sha256": sha}]})


def _manifest(refresh, batch, rev=1, body=b'{"m": 1}\n'):
    p = refresh / "batches" / batch / f"rev-{rev}" / "manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return vr._sha_bytes(body)


class TestReviewFixes:
    def test_another_marin_jurisdiction_in_a_novato_heading_is_refused(self, env):
        text = _nov_html("April 8, 2030").replace("NOVATO CITY COUNCIL MEETING MINUTES",
                                                  "SAMPLE RAFAEL CITY COUNCIL MEETING MINUTES")
        text = text.replace("SAMPLE RAFAEL", "SAN RAFAEL").replace("COUNCIL CHAMBERS",
                                                                   "Joint meeting with Novato City Council")
        assert TestHeading()._check(env, f"meeting-{NOV}-901", text)["file"]["reason"] == \
            "heading_other_jurisdiction:san rafael"

    def test_a_released_slot_is_eligible_again_with_its_own_file(self, env):
        repo, export, refresh = env
        mid = f"meeting-{NOV}-901"
        f = _save(repo, "2030-06-01", NOV, mid, _nov_html("April 8, 2030"))
        reg = vr.Registry(refresh)
        with reg.locked():
            _batch(reg, "batch-001", mid, vr._sha_bytes(f.read_bytes()), manifest=_manifest(refresh, "batch-001"))
            reg.append({"kind": "release", "batch": "batch-001", "reason": "abandoned"})
        row = {r["meeting_id"]: r for r in vr.backlog(export, repo, refresh)[NOV]}[mid]
        assert row["state"] == "file_saved" and row["conflicts"] == []

    def test_ownership_replays_in_log_order(self):
        recs = [{"kind": "batch", "batch": "b1", "rev": 1, "manifest_sha256": "0",
                 "claims": [{"meeting_id": "m", "slot": "minutes", "sha256": "s"}]},
                {"kind": "release", "batch": "b1", "reason": "rolled_back"},
                {"kind": "claim", "batch": "b1", "meeting_id": "m", "slot": "minutes", "sha256": "s"}]
        assert vr.slot_view(recs, [])[("m", "minutes")]["owner"] == "b1"
        recs.append({"kind": "release", "batch": "b1", "reason": "abandoned"})
        assert vr.slot_view(recs, [])[("m", "minutes")]["owner"] is None
        assert vr.slot_view(recs, [])[("m", "minutes")]["sha256"] == "s"

    def test_conflicts_and_rejected_files_reach_the_todo_and_are_recorded_once(self, env):
        repo, export, refresh = env
        mid = f"meeting-{NOV}-901"
        reg = vr.Registry(refresh)
        with reg.locked():
            _batch(reg, "batch-001", mid, "a" * 64, manifest=_manifest(refresh, "batch-001"))
        f = _save(repo, "2030-06-01", NOV, mid, _nov_html("April 8, 2030"))
        _save(repo, "2030-06-01", NOV, f"meeting-{NOV}-903", _nov_html("May 13, 2030"))
        for _ in range(2):
            vr.write_todo(export, repo, refresh, today="2030-06-02")
        conflicts = [r for r in vr.Registry(refresh).records() if r["kind"] == "conflict"]
        assert conflicts == [{"kind": "conflict", "meeting_id": mid, "slot": "minutes",
                              "sha256": vr._sha_bytes(f.read_bytes()), "path": f.relative_to(repo).as_posix(),
                              "held_against": "a" * 64}]
        md = (refresh / "todo.md").read_text()
        assert "document_version_conflict" in md and f.relative_to(repo).as_posix() in md
        other = {o["meeting_id"]: o for o in json.loads((refresh / "todo.json").read_text())["other"]}
        assert other[mid]["state"] == "prepared" and other[mid]["conflicts"][0]["sha256"] == conflicts[0]["sha256"]
        assert other[f"meeting-{NOV}-903"]["state"] == "file_saved"  # saved although no record lists it
        assert f"meeting-{NOV}-902" not in other  # it is on the list itself

    def test_a_missing_or_altered_manifest_blocks_its_body_and_is_reported(self, env):
        repo, export, refresh = env
        mid = f"meeting-{NOV}-901"
        reg = vr.Registry(refresh)
        with reg.locked():
            _batch(reg, "batch-001", mid, "a" * 64, manifest="f" * 64)
        problems = vr.batch_integrity(refresh, vr.Registry(refresh).records())
        assert problems == {"batch-001": "manifest rev-1 missing"}
        assert vr.blocked_bodies(refresh, vr.Registry(refresh).records()) == {NOV: ["batch-001: manifest rev-1 missing"]}
        _manifest(refresh, "batch-001", body=b"tampered\n")
        assert vr.batch_integrity(refresh, vr.Registry(refresh).records()) == {"batch-001": "manifest rev-1 altered"}
        row = {r["meeting_id"]: r for r in vr.backlog(export, repo, refresh)[NOV]}[mid]
        assert row["state"] == "prepared"  # its claim stays
        out = vr.write_todo(export, repo, refresh, today="2030-06-02")
        assert "batch-001: manifest rev-1 altered" in (refresh / "todo.md").read_text()
        assert out["blocked"] == {NOV: ["batch-001: manifest rev-1 altered"]}
