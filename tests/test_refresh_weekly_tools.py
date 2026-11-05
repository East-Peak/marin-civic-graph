"""The weekly run's external tools (scripts/refresh_weekly.py TOOLS): resolved in the run's own environment, and a
missing one is a named failure of exactly the steps that need it (never a traceback from deep in a child), listed
in the digest. Same fake world as tests/test_refresh_weekly.py."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from tests.test_refresh_weekly import (  # noqa: F401  (pytest fixtures, used by name)
    RUN, _state, alarm_pings, ctx, pings, root, rw, world)
from tests.test_refresh_weekly_agenda import AgendaWorld, _load


def _without(*missing: str):
    return lambda tool, path=None: None if tool in missing else f"/stub/bin/{tool}"


def test_every_tool_the_run_names_is_inventoried_with_its_consumers():
    assert rw.TOOLS["pdftotext"] == ("agenda-items", "votes-minutes")
    assert set(rw.TOOLS["git"]) == {"snapshot-", "cf-normalize-", "cf-plan-"}  # step families
    for tool in ("bash", "date", "mkdir", "cp", "shasum", "dirname", "mktemp"):
        assert "reconciliation" in rw.TOOLS[tool]
    assert {"dirname", "mkdir", "wc", "mv", "ls", "cut", "date"} <= set(rw.WRAPPER_TOOLS)


def test_tools_resolve_on_the_runs_own_path_not_this_process(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("pdftotext", "git"):
        (bin_dir / tool).write_text("#!/bin/sh\n")
        (bin_dir / tool).chmod(0o755)
    found = rw.resolve_tools({"PATH": str(bin_dir)}, shutil.which)
    assert found["pdftotext"] == str(bin_dir / "pdftotext") and found["git"] == str(bin_dir / "git")
    assert found["bash"] is None  # only what that PATH holds
    assert set(found) == set(rw.TOOLS) | set(rw.WRAPPER_TOOLS)


def test_a_missing_tool_fails_its_steps_by_name_and_the_runner_never_sees_them(root, ctx):
    world = AgendaWorld(root)
    ctx.runner, ctx.which = world, _without("pdftotext")
    state = _load(ctx)
    agenda = state["agenda_items"]
    assert agenda["ok"] is False
    assert "pdftotext not found on the run's PATH" in agenda["error"] and "Traceback" not in agenda["error"]
    assert "agenda_items.py" not in world.scripts()  # refused before any subprocess
    log = (rw.run_dir(root, RUN) / "logs" / "agenda-items.log").read_text()
    assert "pdftotext not found on the run's PATH" in log
    assert state["tools"]["missing"] == {"pdftotext": ["agenda-items", "votes-minutes"]}
    digest = (rw.run_dir(root, RUN) / "digest.md").read_text()
    tools = digest.split("## Tools", 1)[1].split("##", 1)[0]
    assert "pdftotext" in tools and "agenda-items" in tools
    assert state["status"] == "awaiting_publish_approval"  # the meetings are loaded either way


def test_the_steps_that_do_not_need_it_still_run(root, ctx):
    world = AgendaWorld(root)
    ctx.runner, ctx.which = world, _without("pdftotext")
    _load(ctx)
    assert "normalize_meetings.py" in world.scripts() and "export_live_graph.py" in world.scripts()


def test_every_tool_present_means_no_tools_section_and_the_stage_runs(root, ctx):
    world = AgendaWorld(root)
    ctx.runner = world
    state = _load(ctx)
    assert state["agenda_items"]["ok"] is True and state["tools"]["missing"] == {}
    assert "## Tools" not in (rw.run_dir(root, RUN) / "digest.md").read_text()


def test_a_missing_git_refuses_the_snapshot_and_campaign_steps_by_family():
    for name in ("snapshot-add", "snapshot-push", "cf-normalize-cmar", "cf-plan-cmar"):
        assert rw.blocking_tools(name, {"git": None}) == ["git"]
    for name in ("cf-export", "agenda-pre", "load-permits", "snapshot", "agenda-items-pre"):
        assert rw.blocking_tools(name, {"git": None, "pdftotext": None}) == []
    assert rw.blocking_tools("reconciliation", {"mktemp": None, "bash": None}) == ["bash", "mktemp"]


def test_a_missing_pdftotext_makes_the_votes_list_unavailable_by_name_not_unreadable_files(root, ctx, monkeypatch):
    calls = []
    monkeypatch.setattr(rw.votes_refresh, "digest_snapshot", lambda *a, **k: calls.append(a) or {"items": []})
    ctx.which = _without("pdftotext")
    snap = rw._votes_minutes(ctx)
    assert snap["error"] == "pdftotext not found on the run's PATH; saved PDF minutes cannot be checked"
    assert calls == []
    ctx.which = _without()
    assert rw._votes_minutes(ctx) == {"items": []} and len(calls) == 1


def test_a_later_manual_load_with_the_tool_present_re_resolves(root, ctx):
    world = AgendaWorld(root)
    ctx.runner, ctx.which = world, _without("pdftotext")
    ctx.agenda_items = True
    assert rw.main(["stage"], ctx) == 0
    assert _state(root)["tools"]["missing"] == {"pdftotext": ["agenda-items", "votes-minutes"]}
    ctx.which = _without()
    rw.main(["load", RUN], ctx)
    state = _state(root)
    assert state["tools"]["missing"] == {} and state["agenda_items"]["ok"] is True


def test_the_wrapper_path_helper_is_tracked_and_holds_homebrew_first():
    helper = Path(rw.ROOT) / "ops" / "launchd" / "path.sh"
    text = helper.read_text()
    assert 'export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"' in text
    assert "weekly.env" not in json.dumps(text.splitlines()[-1:])  # the helper never sources secrets
    assert os.access(helper, os.R_OK)


def test_the_votes_list_checks_the_path_its_in_process_extractor_will_search(root, ctx, monkeypatch, tmp_path):
    # votes_text runs pdftotext from this process, so this process's PATH is the one that counts.
    has = tmp_path / "has"
    has.mkdir()
    (has / "pdftotext").write_text("#!/bin/sh\n")
    (has / "pdftotext").chmod(0o755)
    monkeypatch.setattr(rw.votes_refresh, "digest_snapshot", lambda *a, **k: {"items": []})
    ctx.which, ctx.env["PATH"] = shutil.which, str(has)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert "pdftotext not found" in rw._votes_minutes(ctx)["error"]
    monkeypatch.setenv("PATH", str(has))
    assert rw._votes_minutes(ctx) == {"items": []}


def test_relative_path_entries_resolve_against_where_the_program_runs(tmp_path: Path):
    (tmp_path / "bin").mkdir()
    for d in ("bin", "."):
        (tmp_path / d / "pdftotext").write_text("#!/bin/sh\n")
        (tmp_path / d / "pdftotext").chmod(0o755)
    assert rw.resolve_tools({"PATH": "bin"}, shutil.which, cwd=tmp_path)["pdftotext"] == str(tmp_path / "bin/pdftotext")
    assert rw.resolve_tools({"PATH": ""}, shutil.which, cwd=tmp_path)["pdftotext"] == str(tmp_path / "pdftotext")
    assert rw.resolve_tools({"PATH": "bin"}, shutil.which, cwd=tmp_path / "bin")["pdftotext"] is None
