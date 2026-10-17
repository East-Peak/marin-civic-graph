"""The weekly run and crosswalk-required sources (scripts/refresh_weekly.py).

A crosswalk-required source's ids come from a reviewed crosswalk (scripts/crosswalk.py). The stage pins
the crosswalk version each capture was made with, so the load can refuse a capture whose crosswalk
changed since. Same fake world as tests/test_refresh_weekly.py: nothing touches the network or the real data/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_refresh_weekly import (  # noqa: F401  (pytest fixtures, used by name)
    ENV, RUN, FakeWorld, _state, alarm_pings, ctx, pings, root, rw)

PINNED = "5" * 64


class CrosswalkWorld(FakeWorld):
    """FakeWorld whose ingest.py records a crosswalk version for source `a`, as ingest.py does."""

    def __call__(self, cmd, cwd, env, timeout):
        result = super().__call__(cmd, cwd, env, timeout)
        if Path(cmd[1]).name == "ingest.py":
            ledger = self.root / "data/ingest-runs/ledger.jsonl"
            lines = [json.loads(line) for line in ledger.read_text().splitlines()]
            for line in lines:
                if line["source_id"] == "a" and line["run_at"] == "now":
                    line["crosswalk_sha256"] = PINNED
            ledger.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return result


@pytest.fixture
def world(root: Path) -> CrosswalkWorld:
    return CrosswalkWorld(root)


def test_stage_pins_the_crosswalk_version_of_each_capture(ctx, root):
    assert rw.main(["stage"], ctx) == 0
    sources = _state(root)["sources"]
    assert sources["a"]["crosswalk_sha256"] == PINNED
    assert "crosswalk_sha256" not in sources["b"]
