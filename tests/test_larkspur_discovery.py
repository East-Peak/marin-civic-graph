"""Production discovery: the weekly run stages Larkspur only once it is `schedule: weekly`, and then exactly once.

`refresh_weekly.stage` with the production default registry selection (`MEETING_REGISTRIES`, not a
harness override) over copies of the real registry files. The runner records each `ingest.py --all`
and answers it the way ingest.py selects sources (its own `resolve_sources`), so what is asserted is
which registries the run stages and which sources each covers; nothing is fetched.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import ingest  # noqa: E402
import refresh_weekly as rw  # noqa: E402

SID = "larkspur-city-council"


class Recorder:
    def __init__(self, root: Path):
        self.root, self.ingests = root, []

    def __call__(self, cmd, cwd, env, timeout):
        assert Path(cmd[1]).name == "ingest.py", cmd  # the stage runs nothing else here
        registry = cmd[cmd.index("--registry") + 1]
        chosen = [s["id"] for s in ingest.resolve_sources(ingest.load_sources(self.root / registry),
                                                          all_sources=True)]
        self.ingests.append((registry, chosen))
        with (self.root / "data/ingest-runs/ledger.jsonl").open("a") as fh:
            for sid in chosen:
                fh.write(json.dumps({"source_id": sid, "run_at": "now", "rows": 0, "newest": None, "ok": False,
                                     "reasons": ["test: not fetched"]}) + "\n")
        return rw.Result(0, "")


def _stage(tmp_path, schedule: str):
    root = tmp_path / "root"
    (root / "registry").mkdir(parents=True)
    (root / "data/ingest-runs").mkdir(parents=True)
    for path in (REPO / "registry").glob("*-sources.yaml"):
        shutil.copy(path, root / "registry" / path.name)
    civicplus = root / "registry" / "civicplus-sources.yaml"
    registry = yaml.safe_load(civicplus.read_text())
    [larkspur] = [s for s in registry["sources"] if s["id"] == SID]
    assert larkspur["schedule"] == "weekly"  # as committed
    larkspur["schedule"] = schedule
    civicplus.write_text(yaml.safe_dump(registry, sort_keys=False))
    recorder = Recorder(root)
    env = {"NEO4J_URI": "bolt://localhost:7688", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "pw",
           "NEO4J_DATABASE": "neo4j", rw.CF_STAGING_ENV: str(tmp_path / "cf"), rw.VOTES_REFRESH_ENV: str(tmp_path / "v")}
    ctx = rw.Context(root=root, runner=recorder, env=env, python="py",
                     now=lambda: datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc),
                     free_bytes=lambda path: 50 * 1024**3, staged_sources={}, ping=lambda *a: None,
                     netfile_fetch=lambda url: pytest.fail("network"), sleep=lambda s: None,
                     prepare_campaign_exports=False)
    assert ctx.meeting_registries == rw.MEETING_REGISTRIES  # the production default, not an override
    state = rw.stage(ctx)
    return recorder, state


def _count(recorder) -> int:
    return sum(chosen.count(SID) for _, chosen in recorder.ingests)


def test_larkspur_is_not_staged_while_manual(tmp_path):
    recorder, state = _stage(tmp_path, "manual")
    assert "registry/civicplus-sources.yaml" in [r for r, _ in recorder.ingests]
    assert _count(recorder) == 0 and SID not in state["sources"]


def test_larkspur_is_staged_exactly_once_when_weekly(tmp_path):
    recorder, state = _stage(tmp_path, "weekly")
    assert _count(recorder) == 1
    assert [r for r, chosen in recorder.ingests if SID in chosen] == ["registry/civicplus-sources.yaml"]
    assert state["sources"][SID]["registry"] == "civicplus"
