"""The rehearsal's record/replay shim (scripts/crosswalk_rehearsal.py): a POST is keyed by its body, `fill`
serves what is kept, an override store (a week's listing) answers first, and replay never sends anything.
Every global the shim replaces is restored after each test."""
from __future__ import annotations

import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import adapters.base as base  # noqa: E402
import adapters.proudcity as proudcity  # noqa: E402
import crosswalk_rehearsal as cr  # noqa: E402
import ingest  # noqa: E402
import robots_gate as rg  # noqa: E402

URL = "https://www.lakeport.example/AgendaCenter/UpdateCategoryList"
FROZEN = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def restore(monkeypatch):
    for obj, name in ((base, "datetime"), (ingest, "date"), (ingest, "_now"), (rg.RobotsGate, "open"),
                      (rg.RobotsGate, "_pace"), (urllib.request.OpenerDirector, "open"), (proudcity, "time"),
                      (ingest, "time"), (time, "sleep")):
        monkeypatch.setattr(obj, name, getattr(obj, name))
    monkeypatch.setattr(rg.RobotsGate.__init__, "__kwdefaults__", dict(rg.RobotsGate.__init__.__kwdefaults__))


def _store(tmp_path, name="store"):
    store = cr.ResponseStore(tmp_path / name)
    store.put(f"https://www.lakeport.example/robots.txt", status=404, headers={}, body=b"", error=None)
    return store


def _post(body: bytes):
    return urllib.request.Request(URL, data=body, method="POST")


def test_a_post_is_kept_per_body(tmp_path):
    store = _store(tmp_path)
    store.put(URL, b"year=2025", status=200, headers={}, body=b"rows 2025", error=None)
    store.put(URL, b"year=2026", status=200, headers={}, body=b"rows 2026", error=None)
    assert store.get(URL, b"year=2025")["body"] == b"rows 2025" and store.get(URL, b"year=2026")["body"] == b"rows 2026"
    assert not store.has(URL)


def test_replay_serves_kept_posts_and_sends_nothing(tmp_path):
    store = _store(tmp_path)
    store.put(URL, b"year=2026", status=200, headers={}, body=b"rows 2026", error=None)
    cr.install_shim(store, "replay", FROZEN)
    gate = rg.RobotsGate()
    assert gate.open(_post(b"year=2026"), timeout=5).read() == b"rows 2026"
    with pytest.raises(RuntimeError, match="no recorded response"):
        gate.open(_post(b"year=2019"), timeout=5)


def test_an_override_answers_first(tmp_path):
    store, week1 = _store(tmp_path), cr.ResponseStore(tmp_path / "week1")
    store.put(URL, b"year=2026", status=200, headers={}, body=b"real listing", error=None)
    week1.put(URL, b"year=2026", status=200, headers={}, body=b"listing with two rows withheld", error=None)
    cr.install_shim(store, "fill", FROZEN, override=week1)
    assert rg.RobotsGate().open(_post(b"year=2026"), timeout=5).read() == b"listing with two rows withheld"


def test_fill_serves_kept_responses_without_pacing(tmp_path):
    store = _store(tmp_path)
    store.put(URL, b"year=2026", status=200, headers={}, body=b"kept", error=None)
    cr.install_shim(store, "fill", FROZEN)
    slept = []
    gate = rg.RobotsGate(sleep=slept.append)
    assert gate.open(_post(b"year=2026"), timeout=5).read() == b"kept"
    assert gate.open(_post(b"year=2026"), timeout=5).read() == b"kept" and slept == []
