"""One lock per graph target, shared by every worktree: the two AgendaItem writers never overlap.

The agenda stage takes it around its load; the legacy extractor (scripts/extract_agenda_items.py) takes it before
it opens a driver, and refuses rather than waits when it is held.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import graph_lock as gk  # noqa: E402


@pytest.fixture(autouse=True)
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(gk.LOCK_DIR_ENV, str(tmp_path / "locks"))
    return tmp_path / "locks"


def test_a_target_is_named_by_host_and_port():
    assert gk.lock_name("bolt://localhost:7688") == "graph-localhost-7688.lock"
    assert gk.lock_name("neo4j://127.0.0.1:7688/") == "graph-127.0.0.1-7688.lock"


def test_a_fake_graph_is_named_by_its_directory():
    name = gk.lock_name("fakegraph:///tmp/rehearsal/graph")
    assert name.startswith("graph-fakegraph-") and name == gk.lock_name("fakegraph:///tmp/rehearsal/graph")
    assert name != gk.lock_name("fakegraph:///tmp/other")


def test_a_held_lock_refuses_a_second_writer(lock_dir):
    with gk.graph_lock("bolt://localhost:7688"):
        with pytest.raises(gk.GraphLockHeld, match="graph-localhost-7688.lock"):
            with gk.graph_lock("bolt://localhost:7688"):
                pass
        with gk.graph_lock("bolt://localhost:7699"):  # another target: no contention
            pass
    with gk.graph_lock("bolt://localhost:7688"):  # released
        pass
    assert (lock_dir / "graph-localhost-7688.lock").is_file()


def test_the_legacy_extractor_refuses_while_the_lock_is_held(monkeypatch):
    import extract_agenda_items as legacy

    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7688")
    monkeypatch.setenv("NEO4J_PASSWORD", "x")

    def no_driver(*a, **k):
        raise AssertionError("no driver while another writer holds the graph")

    monkeypatch.setattr(legacy, "get_driver", no_driver)
    with gk.graph_lock("bolt://localhost:7688"):
        with pytest.raises(gk.GraphLockHeld):
            legacy.main(["--source", "lakeport-town-council", "--limit", "1"])
