"""The weekly run and the robots gate: saved-page sources and robots outcomes (scripts/refresh_weekly.py).

A saved-page source is never fetched. Each Monday the stage looks for the newest page the operator saved
(data/raw/manual/<YYYY-MM-DD>/granicus/<id>.html) and gives it one outcome:

  missing    no saved page ever                         informational
  stale      newest saved page older than 14 days       informational ("save a fresh page")
  unchanged  newest saved page already loaded           informational
  rejected   these bytes failed their floors before     informational (the first failure alerted)
  accepted   anything else: captured through ingest.py --saved-page, then loaded like a fetch

Only `accepted` enters state.sources, so only it is loaded and only it can fail the run or the heartbeat.
Same fake world as tests/test_refresh_weekly.py: nothing touches the network or the real data/.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.test_refresh_weekly import (  # noqa: F401  (pytest fixtures, used by name)
    DUE_HOST, ENV, RUN, FakeWorld, alarm_pings, ctx, pings, root, rw)

HEARTBEAT = "https://hc-heartbeat.example/5e2d1c0b-aaaa-4bbb-8ccc-0d1e2f3a4b5c"
SAVED = {f"town-{n}": f"https://agendas{n}.example.test/ViewPublisher.php?view_id={n}" for n in range(1, 6)}
NOW = datetime(2026, 9, 28, 5, 0, 0, tzinfo=timezone.utc)


class SavedWorld(FakeWorld):
    """FakeWorld, plus `ingest.py --saved-page`: one ledger line (and a capture) for that source only."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.saved_verdict: dict[str, list[str]] = {}  # sid -> floor reasons (empty: passes)
        self.saved_crash: set[str] = set()

    def __call__(self, cmd, cwd, env, timeout):
        if Path(cmd[1]).name == "ingest.py" and "--saved-page" in cmd:
            self.calls.append(list(cmd))
            self.timeouts.append(timeout)
            sid, page = cmd[cmd.index("--source") + 1], Path(cmd[cmd.index("--saved-page") + 1])
            assert cmd[cmd.index("--root") + 1] == str(self.root)
            if sid in self.saved_crash:
                return rw.Result(1, "Traceback: boom\n")
            sha = hashlib.sha256(page.read_bytes()).hexdigest()
            reasons = self.saved_verdict.get(sid, [])
            with (self.root / "data/ingest-runs/ledger.jsonl").open("a") as fh:
                fh.write(json.dumps({"source_id": sid, "run_at": "now", "rows": 40, "newest": None, "ok": not reasons,
                                     "reasons": reasons, "raw_origin": "saved_page", "raw_sha256": sha,
                                     "saved_page": page.relative_to(self.root).as_posix()}) + "\n")
            if not reasons:
                day = (self.today or NOW).strftime("%Y-%m-%d")
                capture = self.root / f"data/extracted/{sid}/{day}.json"
                capture.parent.mkdir(parents=True, exist_ok=True)
                capture.write_text(json.dumps({"meeting_count": 40, "raw_sha256": sha, "raw_origin": "saved_page"}))
            return rw.Result(0, "ok\n")
        return super().__call__(cmd, cwd, env, timeout)

    today: datetime | None = None


@pytest.fixture
def world(root: Path) -> SavedWorld:
    with (root / "registry/granicus-sources.yaml").open("a") as fh:
        for sid, url in SAVED.items():
            fh.write(f"  - {{id: {sid}, adapter: granicus, url: '{url}', schedule: saved-page}}\n")
    return SavedWorld(root)


def _save(root: Path, sid: str, day: str, body: bytes = b"<html>listing</html>") -> Path:
    path = root / "data/raw/manual" / day / "granicus" / f"{sid}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _at(ctx, world, when: datetime):
    """The next Monday: a later clock, and last week's snapshot already committed in the fake data repo."""
    world.today = when
    world.git["added"] = False
    return dataclasses.replace(ctx, now=lambda: when)


def _weekly(ctx) -> int:
    ctx.env[rw.HEARTBEAT_ENV] = HEARTBEAT
    return rw.main(["weekly"], ctx)


def _run_state(root: Path, when: datetime = NOW) -> dict:
    return json.loads((root / f"data/ingest-runs/{when.strftime('%Y-%m-%dT%H%M%SZ')}/state.json").read_text())


def _digest(root: Path, when: datetime = NOW) -> str:
    return (root / f"data/ingest-runs/{when.strftime('%Y-%m-%dT%H%M%SZ')}/digest.md").read_text()


def _signals(pings) -> list[str]:
    return ["fail" if url.endswith("/fail") else "success" for url, _ in pings if not url.startswith(DUE_HOST)]


def _saved_steps(world) -> list[str]:
    return [cmd[cmd.index("--source") + 1] for cmd in world.calls if "--saved-page" in cmd]


# --- a Monday with no saved pages at all ---------------------------------------------------


def test_a_monday_with_no_saved_pages_is_clean_and_lists_all_five_to_save(ctx, world, root, pings):
    assert _weekly(ctx) == 0
    state = _run_state(root)
    assert {sid: s["outcome"] for sid, s in state["saved_pages"].items()} == {sid: "missing" for sid in SAVED}
    assert not set(SAVED) & set(state["sources"])  # informational: never a source, never loaded
    assert _saved_steps(world) == []
    assert _signals(pings) == ["success"] and state["heartbeat"]["signal"] == "success"
    digest = _digest(root)
    assert "## Saved pages" in digest
    for sid, url in SAVED.items():
        assert url in digest
        assert f"save a fresh page for **{sid}**" in digest
        assert f"data/raw/manual/2026-09-28/granicus/{sid}.html" in digest
    assert not any("--saved-page" in c or any("agendas" in part for part in c) for c in world.calls)


# --- accepted ---------------------------------------------------------------------------------


def test_a_new_saved_page_is_accepted_captured_and_loaded(ctx, world, root, pings):
    page = _save(root, "town-1", "2026-09-26")
    assert _weekly(ctx) == 0
    state = _run_state(root)
    sha = hashlib.sha256(page.read_bytes()).hexdigest()
    assert state["saved_pages"]["town-1"]["outcome"] == "accepted"
    assert state["saved_pages"]["town-1"]["age_days"] == 2
    source = state["sources"]["town-1"]
    assert source["ok"] and source["kind"] == "meetings" and source["registry"] == "granicus"
    assert source["saved_page"] == {"path": "data/raw/manual/2026-09-26/granicus/town-1.html", "sha256": sha,
                                    "saved_on": "2026-09-26", "verdict": "passed"}
    assert source["capture"]["path"] == "data/extracted/town-1/2026-09-28.json"
    assert "town-1" in state["loaded"]
    assert any(c[1].endswith("normalize_meetings.py") and "town-1" in c for c in world.calls)
    assert _saved_steps(world) == ["town-1"]
    assert _signals(pings) == ["success"]
    assert page.read_bytes() == b"<html>listing</html>"  # never moved, never deleted


def test_only_the_newest_saved_page_counts(ctx, world, root, pings):
    _save(root, "town-1", "2026-09-10", b"old")
    newest = _save(root, "town-1", "2026-09-25", b"new")
    (root / "data/raw/manual/notes").mkdir(parents=True)  # stray dirs are not dates
    assert _weekly(ctx) == 0
    cmd = next(c for c in world.calls if "--saved-page" in c)
    assert cmd[cmd.index("--saved-page") + 1] == str(newest)


# --- unchanged and stale ----------------------------------------------------------------------


def test_a_loaded_page_is_unchanged_next_week_and_stale_once_older_than_14_days(ctx, world, root, pings):
    _save(root, "town-1", "2026-09-26")
    assert _weekly(ctx) == 0

    week2 = NOW + timedelta(days=7)
    assert _weekly(_at(ctx, world, week2)) == 0
    assert _run_state(root, week2)["saved_pages"]["town-1"]["outcome"] == "unchanged"
    assert "town-1" not in _run_state(root, week2)["sources"]
    assert "save a fresh page for **town-1**" not in _digest(root, week2)

    week3 = NOW + timedelta(days=14)
    assert _weekly(_at(ctx, world, week3)) == 0
    assert _run_state(root, week3)["saved_pages"]["town-1"] == {
        "outcome": "stale", "url": SAVED["town-1"], "adapter": "granicus", "path": "data/raw/manual/2026-09-26/granicus/town-1.html",
        "saved_on": "2026-09-26", "age_days": 16,
        "sha256": hashlib.sha256(b"<html>listing</html>").hexdigest()}
    assert "save a fresh page for **town-1**" in _digest(root, week3)
    assert _saved_steps(world) == ["town-1"]
    assert _signals(pings) == ["success"] * 3


def test_an_old_page_never_loaded_is_stale_and_not_ingested(ctx, world, root, pings):
    _save(root, "town-2", "2026-09-01")
    assert _weekly(ctx) == 0
    assert _run_state(root)["saved_pages"]["town-2"]["outcome"] == "stale"
    assert _saved_steps(world) == [] and "town-2" not in _run_state(root)["sources"]
    assert _signals(pings) == ["success"]


# --- the transitions -------------------------------------------------------------------------


def test_a_page_captured_but_never_loaded_is_accepted_again_next_week(ctx, world, root, pings):
    _save(root, "town-1", "2026-09-26")
    world.backup_exit = 1  # the load never happens
    assert _weekly(ctx) == 1
    world.backup_exit = 0
    week2 = NOW + timedelta(days=7)
    assert _weekly(_at(ctx, world, week2)) == 0
    assert _run_state(root, week2)["saved_pages"]["town-1"]["outcome"] == "accepted"
    assert "town-1" in _run_state(root, week2)["loaded"]
    assert _saved_steps(world) == ["town-1", "town-1"]


def test_a_floors_rejection_alerts_once_then_waits_for_new_bytes(ctx, world, root, pings):
    _save(root, "town-1", "2026-09-26")
    world.saved_verdict["town-1"] = ["pull returned 0 rows"]
    assert _weekly(ctx) == 1
    first = _run_state(root)["sources"]["town-1"]
    assert first["ok"] is False and first["saved_page"]["verdict"] == "rejected"
    assert "pull returned 0 rows" in _digest(root)

    week2 = NOW + timedelta(days=7)
    assert _weekly(_at(ctx, world, week2)) == 0
    assert _run_state(root, week2)["saved_pages"]["town-1"]["outcome"] == "rejected"
    assert "town-1" not in _run_state(root, week2)["sources"]

    del world.saved_verdict["town-1"]
    _save(root, "town-1", "2026-10-04", b"<html>fixed</html>")
    week3 = NOW + timedelta(days=8)
    assert _weekly(_at(ctx, world, week3)) == 0
    assert _run_state(root, week3)["saved_pages"]["town-1"]["outcome"] == "accepted"
    assert _saved_steps(world) == ["town-1", "town-1"]
    assert _signals(pings) == ["fail", "success", "success"]


def test_a_crashed_saved_page_step_is_not_a_rejection_and_is_retried(ctx, world, root, pings):
    _save(root, "town-1", "2026-09-26")
    world.saved_crash.add("town-1")
    assert _weekly(ctx) == 1
    source = _run_state(root)["sources"]["town-1"]
    assert source["ok"] is False and source["saved_page"]["verdict"] == "no verdict"
    assert "logs/saved-town-1.log" in source["reasons"][0]

    world.saved_crash.clear()
    week2 = NOW + timedelta(days=7)
    assert _weekly(_at(ctx, world, week2)) == 0
    assert _run_state(root, week2)["saved_pages"]["town-1"]["outcome"] == "accepted"


def test_a_capture_that_is_not_the_saved_page_is_not_loaded(ctx, world, root, pings):
    _save(root, "town-1", "2026-09-26")
    real = world.__call__

    def stale_capture(cmd, cwd, env, timeout):
        result = real(cmd, cwd, env, timeout)
        if "--saved-page" in cmd:
            (root / "data/extracted/town-1/2026-09-28.json").write_text(json.dumps({"raw_sha256": "f" * 64}))
        return result
    ctx = dataclasses.replace(ctx, runner=stale_capture)
    assert _weekly(ctx) == 1
    source = _run_state(root)["sources"]["town-1"]
    assert source["ok"] is False and "not the saved page" in source["reasons"][0]
    assert "town-1" not in _run_state(root).get("loaded", [])


# --- robots outcomes and the stage's own arguments ----------------------------------------------


def test_the_meeting_stage_runs_ingest_under_the_runs_root_with_a_shared_robots_cache(ctx, world, root):
    assert rw.main(["stage"], ctx) == 0
    cmd = next(c for c in world.calls if Path(c[1]).name == "ingest.py")
    assert Path(cmd[1]).is_absolute() and Path(cmd[1]) == rw.SCRIPTS / "ingest.py"
    assert cmd[cmd.index("--root") + 1] == str(root)
    assert cmd[cmd.index("--robots-cache") + 1] == str(root / f"data/ingest-runs/{RUN}/robots.json")
    assert cmd[cmd.index("--request-log") + 1] == str(root / f"data/ingest-runs/{RUN}/logs/requests-granicus.jsonl")


def test_a_robots_refusal_is_the_sources_outcome_in_state_and_digest_and_fails_the_heartbeat(ctx, world, root, pings):
    real = world.__call__

    def refusing(cmd, cwd, env, timeout):
        if Path(cmd[1]).name == "ingest.py" and "--all" in cmd:
            world.calls.append(list(cmd))
            run = root / f"data/ingest-runs/{RUN}"
            (run / "robots.json").write_text(json.dumps({"https://agendas.example.test": {
                "url": "https://agendas.example.test/robots.txt", "status": 200, "sha256": "ab" * 32,
                "fetched_at": "2026-09-28T05:00:01.000+00:00", "body": "User-agent: *\nDisallow: /\n"}}))
            robots = {"url": "https://agendas.example.test/x", "rule": "Disallow: /",
                      "robots_url": "https://agendas.example.test/robots.txt", "robots_status": 200}
            with (root / "data/ingest-runs/ledger.jsonl").open("a") as fh:
                fh.write(json.dumps({"source_id": "a", "run_at": "now", "rows": 0, "newest": None, "ok": False,
                                     "reasons": ["robots_disallowed: https://agendas.example.test/x (Disallow: /)"],
                                     "outcome": "robots_disallowed", "robots": robots}) + "\n")
                fh.write(json.dumps({"source_id": "b", "run_at": "now", "rows": 25, "newest": None, "ok": True,
                                     "reasons": []}) + "\n")
            capture = root / "data/extracted/b/2026-09-28.json"
            capture.parent.mkdir(parents=True, exist_ok=True)
            capture.write_text("{}")
            return rw.Result(1, "1 source(s) failed: a\n")
        return real(cmd, cwd, env, timeout)
    ctx = dataclasses.replace(ctx, runner=refusing)

    assert _weekly(ctx) == 1
    state = _run_state(root)
    a = state["sources"]["a"]
    assert a["ok"] is False and a["status"] == "robots_disallowed" and a["robots"]["rule"] == "Disallow: /"
    assert state["robots"] == {"https://agendas.example.test": {
        "url": "https://agendas.example.test/robots.txt", "status": 200, "sha256": "ab" * 32,
        "fetched_at": "2026-09-28T05:00:01.000+00:00"}}
    assert "robots_disallowed" in _digest(root) and "Disallow: /" in _digest(root)
    assert _signals(pings) == ["fail"]


def test_the_harness_can_switch_the_refetchers_off(ctx, world, root):
    ctx = dataclasses.replace(ctx, staged_sources={})
    assert rw.main(["stage"], ctx) == 0
    assert world.scripts() == ["ingest.py"]
