"""The weekly run carries a capture's pinned Record-URL alias list (scripts/record_url_aliases.py) to its load.

The stage records `record_url_aliases_sha256` from ingest's ledger entry in the source's state; a guarded load
report must name exactly that version (or none, when none was pinned), or the load is no success. Same fake
world as tests/test_refresh_weekly_crosswalk.py: nothing touches the network or the real data/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_refresh_weekly import RUN, _state, ctx, pings, alarm_pings, root, rw  # noqa: F401  (fixtures)
from tests.test_refresh_weekly_crosswalk import ReportingWorld, _load

ALIASES = "7" * 64


class AliasWorld(ReportingWorld):
    """ingest.py also records an alias-list version for source `a`; its load report names what `pin_report` says."""

    def __init__(self, root: Path, *, pinned: bool = True):
        super().__init__(root)
        self.pinned = pinned

    def __call__(self, cmd, cwd, env, timeout):
        if Path(cmd[1]).name == "normalize_meetings.py" and cmd[cmd.index("--source") + 1] == "a":
            state = json.loads((self.root / f"data/ingest-runs/{RUN}/state.json").read_text())
            self.report = {**(self.report or {}),
                           "record_url_aliases_sha256": state["sources"]["a"].get("record_url_aliases_sha256")}
        result = super().__call__(cmd, cwd, env, timeout)
        if Path(cmd[1]).name == "ingest.py" and self.pinned:
            ledger = self.root / "data/ingest-runs/ledger.jsonl"
            lines = [json.loads(line) for line in ledger.read_text().splitlines()]
            for line in lines:
                if line["source_id"] == "a" and line["run_at"] == "now":
                    line["record_url_aliases_sha256"] = ALIASES
            ledger.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return result


@pytest.fixture
def world(root: Path) -> AliasWorld:
    return AliasWorld(root)


def test_stage_pins_the_alias_version_of_each_capture(root, ctx):
    assert rw.main(["stage"], ctx) == 0
    sources = _state(root)["sources"]
    assert sources["a"]["record_url_aliases_sha256"] == ALIASES
    assert "record_url_aliases_sha256" not in sources["b"]


def test_a_report_naming_the_pinned_version_loads(ctx):
    state = _load(ctx)
    assert state["status"] == "awaiting_publish_approval" and "a" in state["loaded"]


@pytest.mark.parametrize("pinned, claimed", [(True, None), (True, "0" * 64), (False, ALIASES)],
                         ids=["pinned-report-says-none", "pinned-report-says-another", "none-pinned-report-says-one"])
def test_a_report_naming_another_alias_version_is_a_failed_load(world, ctx, pinned, claimed):
    world.pinned = pinned
    world.report_overrides = {"record_url_aliases_sha256": claimed}
    state = _load(ctx)
    assert state["status"] == "load_failed"
    assert "record_url_aliases_sha256" in state["error"]
