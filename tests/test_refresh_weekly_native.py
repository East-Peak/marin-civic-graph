"""The weekly run and `identity: native-only` sources (scripts/refresh_weekly.py).

The stage pins the identity a capture was made under; at load such a source goes through the guarded
load like a crosswalk source (its report decides loaded / held), with no crosswalk version to pin. Same
fake world as tests/test_refresh_weekly.py: nothing touches the network or the real data/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_refresh_weekly import (  # noqa: F401  (pytest fixtures, used by name)
    ENV, RUN, FakeWorld, _state, alarm_pings, ctx, pings, root, rw)


class NativeWorld(FakeWorld):
    """ingest.py records `identity: native-only` for source `a`; its load writes the guarded report."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.report: dict | None = {"outcome": "loaded", "holds": []}

    def __call__(self, cmd, cwd, env, timeout):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        if script == "normalize_meetings.py" and cmd[cmd.index("--source") + 1] == "a" and self.report is not None:
            source = json.loads((self.root / f"data/ingest-runs/{RUN}/state.json").read_text())["sources"]["a"]
            out = Path(cmd[cmd.index("--report") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"source_id": "a", "capture_sha256": source["capture"]["sha256"],
                                       "crosswalk_sha256": None, **self.report}))
        result = super().__call__(cmd, cwd, env, timeout)
        if script == "ingest.py":
            ledger = self.root / "data/ingest-runs/ledger.jsonl"
            lines = [json.loads(line) for line in ledger.read_text().splitlines()]
            for line in lines:
                if line["source_id"] == "a" and line["run_at"] == "now":
                    line["identity"] = "native-only"
            ledger.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return result


@pytest.fixture
def world(root: Path) -> NativeWorld:
    return NativeWorld(root)


def test_stage_pins_the_identity_a_capture_was_made_under(root, ctx, world):
    assert rw.main(["stage"], ctx) == 0
    sources = _state(root)["sources"]
    assert sources["a"]["identity"] == "native-only" and "identity" not in sources["b"]


def test_a_native_source_loads_through_its_guarded_report(root, ctx, world):
    assert rw.main(["stage"], ctx) == 0
    rw.main(["load", RUN], ctx)
    state = _state(root)
    assert state["status"] == "awaiting_publish_approval" and "a" in state["loaded"]
    assert state["sources"]["a"]["load_report"]["outcome"] == "loaded"


def test_a_native_source_without_its_report_is_a_failed_load(root, ctx, world):
    world.report = None
    assert rw.main(["stage"], ctx) == 0
    rw.main(["load", RUN], ctx)
    state = _state(root)
    assert state["status"] == "load_failed" and "load report" in state["error"]


def test_a_held_native_source_names_its_hold_in_the_digest(root, ctx, world):
    world.report = {"outcome": "held", "holds": [{"reason": "listing_item_missing", "archive_item_id": 9533}]}
    assert rw.main(["stage"], ctx) == 0
    rw.main(["load", RUN], ctx)
    digest = (rw.run_dir(root, RUN) / "digest.md").read_text()
    assert "**a**" in digest and "listing_item_missing" in digest


def test_an_adapter_error_names_its_row_in_the_state_and_the_digest(root, ctx, world):
    world.meetings["a"] = (0, ["1 adapter error (max 0): a partial pull",
                               "adapter error: unresolved row ADID 9533: no_type_word: October 7, 2026, Council Retreat"])
    assert rw.main(["stage"], ctx) in (0, 1)
    state = _state(root)
    assert any("ADID 9533" in r for r in state["sources"]["a"]["reasons"])
    digest = (rw.run_dir(root, RUN) / "digest.md").read_text()
    assert "ADID 9533: no_type_word" in digest.split("## Failures", 1)[1]
