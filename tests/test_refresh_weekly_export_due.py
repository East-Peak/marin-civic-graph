"""The export-due alarm inside the weekly run: evaluated on every run, whatever else happened, and its
monitoring failures reported on the main heartbeat. Fake world, fake NetFile API, fixed clock; no network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import refresh_weekly as rw  # noqa: E402
from run_lock import run_lock  # noqa: E402
from tests.netfile_workbooks import filing, summary, write_export  # noqa: E402
from tests.test_cf_export_due import PRIVATE, FakeApi  # noqa: E402
from tests.test_refresh_weekly import (  # noqa: E402, F401 (fixtures)
    DUE, DUE_FAIL, DUE_HOST, DUE_SECRETS, FAIL, HEARTBEAT, RUN, _everything_written, _state, alarm_pings, ctx, pings, root, world,
)

SOURCE = {"id": "example-cf", "name": "Example County", "agency_code": "EXC", "adapter": "netfile",
          "portal_url": "https://netfile.example/public/EXC/campaign", "backfill_from": "2025-01-01",
          "jurisdiction_id": "place-example", "institution_id": "org-example"}


@pytest.fixture
def api(ctx) -> FakeApi:
    fake = FakeApi()
    ctx.netfile_fetch = fake
    ctx.prepare_campaign_exports = False  # the alarm alone: preparation is tests/test_cf_prepare.py's
    return fake


def _registry(root: Path, *sources: dict) -> None:
    (root / "registry/netfile-sources.yaml").write_text(yaml.safe_dump({"sources": list(sources)}))


def _export(root: Path, capture: str, year: str, rpt: str) -> None:
    write_export(root / f"data/raw/example-cf/{capture}/{year}.zip", {"Summary": [summary(filing(rpt=rpt), "A", "1", 0)]})


def _fresh(root: Path) -> None:  # the run's clock says 2026-09-28: both years are fresh
    _export(root, "2026-09-25", "2025", "2026-01-31")
    _export(root, "2026-09-25", "2026", "2026-09-25")


def _weekly(ctx) -> int:
    ctx.env[rw.HEARTBEAT_ENV] = HEARTBEAT
    return rw.main(["weekly"], ctx)


def _alarm(alarm_pings) -> list[str]:
    return [url for url, _ in alarm_pings]


def _main(pings) -> list[tuple[str, str]]:
    return list(pings)


def test_a_clean_week_with_nothing_due_pings_both_checks_plainly(ctx, alarm_pings, root, pings, api):
    _registry(root, SOURCE)
    _fresh(root)

    assert _weekly(ctx) == 0

    assert _alarm(alarm_pings) == [DUE] and [u for u, _ in _main(pings)] == [HEARTBEAT]
    body = alarm_pings[0][1]
    assert body.startswith("Open Marin: no campaign export due (2026-09-27)")  # 05:00 UTC is still Sunday in Pacific
    state = _state(root)
    assert state["export_due"]["signal"] == "success" and state["export_due"]["ping"] == {"ok": True}
    assert state["export_due"]["record"]["due"] == []
    assert "Campaign export-due alarm" in (root / f"data/ingest-runs/{RUN}/digest.md").read_text()


def test_a_due_export_pings_the_alarm_fail_with_the_steps_but_leaves_the_main_run_clean(ctx, alarm_pings, root, pings, api):
    _registry(root, SOURCE)
    _export(root, "2026-09-25", "2025", "2026-01-31")  # 2026: nothing on file

    assert _weekly(ctx) == 0

    assert _alarm(alarm_pings) == [DUE_FAIL]
    body = alarm_pings[0][1]
    assert "2026 -> save as data/raw/example-cf/2026-09-27/2026.zip" in body
    assert 'click "Export Amended"' in body and SOURCE["portal_url"] in body
    assert [u for u, _ in _main(pings)] == [HEARTBEAT]


def test_the_alarm_is_evaluated_even_when_the_main_run_fails(ctx, alarm_pings, root, world, pings, api):
    _registry(root, SOURCE)
    _export(root, "2026-09-25", "2025", "2026-01-31")
    world.exit_codes["ingest_form700.py"] = 1

    assert _weekly(ctx) == 1

    assert _alarm(alarm_pings) == [DUE_FAIL] and [u for u, _ in _main(pings)] == [FAIL]


def test_the_alarm_is_evaluated_when_an_unresolved_load_blocks_the_run(ctx, alarm_pings, root, pings, api):
    _registry(root, SOURCE)
    _fresh(root)
    blocked = root / "data/ingest-runs/2026-09-21T050000Z"
    blocked.mkdir(parents=True)
    rw.write_state(root, blocked.name, {"run_id": blocked.name, "status": "load_failed", "history": [], "sources": {}})

    assert _weekly(ctx) == 1

    assert _alarm(alarm_pings) == [DUE] and [u for u, _ in _main(pings)] == [FAIL]


def test_the_alarm_is_evaluated_read_only_when_the_lock_is_held(ctx, alarm_pings, root, pings, api):
    _registry(root, SOURCE)
    _fresh(root)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

    with run_lock(root):
        assert _weekly(ctx) == 2

    assert _alarm(alarm_pings) == [DUE] and [u for u, _ in _main(pings)] == [FAIL]
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    assert [p for p in after if p not in before and not p.endswith(".lock")] == []


@pytest.mark.parametrize("breakage,says", [
    ("no-url", "OPEN_MARIN_EXPORT_DUE_URL is not set"),
    ("bad-url", "OPEN_MARIN_EXPORT_DUE_URL is not an http(s) URL"),
    ("unparseable-url", "OPEN_MARIN_EXPORT_DUE_URL is not an http(s) URL"),
    ("no-sources", "no campaign sources"),
    ("future-backfill", "backfill_from"),
    ("no-registry", "netfile-sources.yaml"),
    ("bad-registry", "netfile-sources.yaml"),
    ("incomplete-source", "lacks agency_code"),
    ("bad-confirmation", "confirmed_unavailable"),
])
def test_missing_or_invalid_alarm_config_makes_the_main_run_not_clean(ctx, root, pings, api, breakage, says):
    source = dict(SOURCE)
    if breakage == "incomplete-source":
        del source["agency_code"]
    if breakage == "bad-confirmation":
        source["confirmed_unavailable"] = [{"year": "2025"}]
    if breakage == "future-backfill":
        source["backfill_from"] = "2027-01-01"
    _registry(root, *([] if breakage == "no-sources" else [source]))
    _fresh(root)
    if breakage == "no-url":
        del ctx.env[rw.EXPORT_DUE_ENV]
    elif breakage == "bad-url":
        ctx.env[rw.EXPORT_DUE_ENV] = "hc-ping.com/not-a-url"
    elif breakage == "unparseable-url":
        ctx.env[rw.EXPORT_DUE_ENV] = "https://[broken-9f8e7d6c5b4a/x"
    elif breakage == "no-registry":
        (root / "registry/netfile-sources.yaml").unlink()
    elif breakage == "bad-registry":
        (root / "registry/netfile-sources.yaml").write_text("sources: [unclosed\n")

    assert _weekly(ctx) == 1

    [(url, body)] = _main(pings)
    assert url == FAIL and "export-due alarm" in body and says in body


@pytest.mark.parametrize("trouble,says", [("down", "NetFile API unreachable"), ("shape", "changed shape")])
def test_an_api_failure_fails_the_main_run_and_the_alarm_still_judges_the_calendar(ctx, alarm_pings, root, pings, api,
                                                                                  trouble, says):
    _registry(root, SOURCE)
    _export(root, "2026-09-25", "2025", "2026-01-31")
    if trouble == "down":
        api.down = OSError("connection refused")
    else:
        api.shape = {"rows": []}

    assert _weekly(ctx) == 1

    assert _alarm(alarm_pings) == [DUE_FAIL]
    assert "calendar rules only" in alarm_pings[0][1]
    [(url, body)] = _main(pings)
    assert url == FAIL and says in body


def test_a_failed_alarm_ping_makes_the_main_run_not_clean(ctx, root, pings, api):
    _registry(root, SOURCE)
    _fresh(root)

    def ping(url, body):
        if url.startswith(DUE_HOST):
            raise OSError(f"cannot reach {url}")
        pings.append((url, body))
    ctx.ping = ping

    assert _weekly(ctx) == 1

    [(url, body)] = _main(pings)
    assert url == FAIL and "export-due alarm ping failed" in body
    assert _state(root)["export_due"]["ping"]["ok"] is False


def test_both_check_urls_never_leak_anywhere(ctx, alarm_pings, root, world, pings, api, capsys):
    _registry(root, SOURCE)
    _fresh(root)
    seen_envs = []

    def leaky(cmd, cwd, env, timeout):
        seen_envs.append(dict(env))
        if Path(cmd[1]).name == "ingest_form700.py":
            return rw.Result(1, f"saw {ctx.env[rw.EXPORT_DUE_ENV]} and {' '.join(DUE_SECRETS)} and {HEARTBEAT}\n")
        return world(cmd, cwd, env, timeout)
    ctx.runner = leaky
    api.down = OSError(f"refused while holding {ctx.env[rw.EXPORT_DUE_ENV]} / {DUE_SECRETS[-1]}")

    assert _weekly(ctx) == 1

    out = capsys.readouterr()
    everything = out.out + out.err + _everything_written(root) + "".join(b for _, b in pings + alarm_pings)
    assert "[redacted]" in everything
    for secret in (*DUE_SECRETS, ctx.env[rw.EXPORT_DUE_ENV]):
        assert secret not in everything
    assert seen_envs and not any(rw.EXPORT_DUE_ENV in env or rw.HEARTBEAT_ENV in env for env in seen_envs)


def test_no_contributor_field_from_the_api_is_persisted(ctx, alarm_pings, root, pings, api):
    _registry(root, SOURCE)
    _fresh(root)
    api.transactions["EXC"] = ["2026-09-26"]
    api.add_filing("EXC", "9001", filed="2026-09-26", period_end="2025-12-31")

    assert _weekly(ctx) == 0

    written = _everything_written(root) + "".join(body for _, body in pings + alarm_pings)
    assert "9001" in written  # filing ids and counts are kept …
    for value in PRIVATE.values():  # … contributor fields never are
        assert value not in written


def test_dry_run_prints_the_verdict_against_the_api_without_pinging_or_writing(ctx, alarm_pings, root, pings, api,
                                                                              capsys):
    _registry(root, SOURCE)
    _export(root, "2026-09-25", "2025", "2026-01-31")
    before = {p: p.stat().st_mtime_ns for p in root.rglob("*")}

    assert rw.main(["export-due", "--dry-run"], ctx) == 0

    out = capsys.readouterr().out
    assert "would ping: fail" in out and "2026 -> save as data/raw/example-cf/2026-09-27/2026.zip" in out
    assert api.urls and pings == [] and alarm_pings == []
    assert {p: p.stat().st_mtime_ns for p in root.rglob("*")} == before


def test_export_due_without_dry_run_pings_the_alarm_only(ctx, alarm_pings, root, pings, api):
    _registry(root, SOURCE)
    _fresh(root)

    assert rw.main(["export-due"], ctx) == 0

    assert [u for u, _ in alarm_pings] == [DUE] and pings == []
    assert not (root / f"data/ingest-runs/{RUN}").exists()


def test_dry_run_with_a_broken_config_says_why_and_exits_nonzero(ctx, root, pings, api, capsys):
    (root / "registry/netfile-sources.yaml").write_text("sources: [unclosed\n")
    assert rw.main(["export-due", "--dry-run"], ctx) == 1
    assert "netfile-sources.yaml" in capsys.readouterr().out and pings == []


def test_validation_results_are_cached_by_hash_in_the_campaign_state(ctx, root, pings, api):
    _registry(root, SOURCE)
    _fresh(root)

    assert _weekly(ctx) == 0

    cache = json.loads((root / "data/ingest-runs/campaign-finance.json").read_text())["validated"]
    assert len(cache) == 2 and {v["ok"] for v in cache.values()} == {True}


def test_fail_goes_on_the_path_not_after_the_query(ctx, alarm_pings, root, pings, api):
    _registry(root, SOURCE)
    _export(root, "2026-09-25", "2025", "2026-01-31")
    ctx.env[rw.HEARTBEAT_ENV] = HEARTBEAT + "?rid=main-run-1234"
    world_fail = rw._fail_url(ctx.env[rw.HEARTBEAT_ENV])

    rw.main(["weekly"], ctx)

    assert [u for u, _ in alarm_pings] == [DUE_FAIL]
    assert world_fail == HEARTBEAT + "/fail?rid=main-run-1234"


def test_an_unparseable_heartbeat_url_is_reported_never_raised(ctx, alarm_pings, root, pings, api):
    _registry(root, SOURCE)
    _fresh(root)
    ctx.env[rw.HEARTBEAT_ENV] = "https://[broken-heartbeat-0a1b2c3d/x"

    ctx.ping = lambda url, body: rw.http_ping(url, body) if url.startswith("https://[") else alarm_pings.append(
        (url, body))

    rw.main(["weekly"], ctx)  # nothing escapes: the failed ping is recorded

    assert _state(root)["heartbeat"]["ok"] is False
    assert "broken-heartbeat-0a1b2c3d" not in _everything_written(root)


@pytest.mark.parametrize("token", ['quote"d-secret-1', "back\\slash-secret-2", "unicodé-secret-3"])
def test_secrets_that_json_would_escape_never_reach_state(ctx, alarm_pings, root, pings, api, token):
    _registry(root, SOURCE)
    _fresh(root)
    ctx.env["COURTLISTENER_API_TOKEN"] = token
    api.down = OSError(f"refused for {token}")

    _weekly(ctx)

    written = _everything_written(root)
    assert token not in written and json.dumps(token)[1:-1] not in written


def test_a_secret_at_the_body_cut_is_scrubbed_before_the_cut(ctx, alarm_pings, root, pings, api, monkeypatch):
    import cf_export_due
    _registry(root, SOURCE)
    _fresh(root)
    secret = DUE_SECRETS[0]
    monkeypatch.setattr(cf_export_due, "render_body",
                        lambda v: "x" * (cf_export_due.BODY_CHARS - 5) + secret + "\n")

    _weekly(ctx)

    body = alarm_pings[0][1]
    assert secret[:5] not in body and len(body) <= cf_export_due.BODY_CHARS


def test_a_short_query_value_is_not_a_secret_and_never_corrupts_state(ctx, alarm_pings, root, pings, api):
    _registry(root, SOURCE)
    _fresh(root)
    ctx.env[rw.EXPORT_DUE_ENV] = DUE + "&n=2"  # "2" is in every date and count: never treated as a secret

    _weekly(ctx)

    state = _state(root)  # still valid JSON
    assert state["export_due"]["record"]["today"] == "2026-09-27" and state["run_id"] == RUN
    json.loads((root / "data/ingest-runs/campaign-finance.json").read_text())
