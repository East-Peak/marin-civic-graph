"""Guard against connecting pipeline scripts to the wrong Neo4j.

Port 7687 on the operator machine is an UNRELATED family-tree database (the
default brew store); Open Marin's operator graph is bolt://localhost:7688.
Aura (neo4j.io) was deleted 2026-07-08. Every script must open drivers via
neo4j_target.open_driver so the guard is a chokepoint, not a convention.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from neo4j_target import UnsafeNeo4jTarget, check_target, open_driver  # noqa: E402


@pytest.mark.parametrize(
    "uri",
    [
        "bolt://localhost:7687",
        "neo4j://127.0.0.1:7687",
        "bolt://localhost",  # scheme default port is 7687
        "neo4j+s://26fb9605.databases.neo4j.io",
        "neo4j+s://something.aura.example",
    ],
)
def test_refuses_family_tree_port_and_aura(uri):
    with pytest.raises(UnsafeNeo4jTarget):
        check_target(uri, env={})


def test_allows_the_open_marin_operator_graph():
    assert check_target("bolt://localhost:7688", env={}) == "bolt://localhost:7688"


def test_missing_uri_is_an_error_not_a_silent_default():
    with pytest.raises(UnsafeNeo4jTarget, match="NEO4J_URI"):
        check_target(None, env={})
    with pytest.raises(UnsafeNeo4jTarget, match="NEO4J_URI"):
        check_target("", env={})


def test_escape_hatch_allows_with_loud_warning(capsys):
    uri = check_target("bolt://localhost:7687", env={"OPEN_MARIN_ALLOW_UNSAFE_TARGET": "1"})
    assert uri == "bolt://localhost:7687"
    assert "UNSAFE" in capsys.readouterr().err


def test_open_driver_refuses_before_connecting(monkeypatch):
    import neo4j_target

    called = []
    monkeypatch.setattr(neo4j_target.GraphDatabase, "driver", lambda *a, **k: called.append(a))
    monkeypatch.delenv("OPEN_MARIN_ALLOW_UNSAFE_TARGET", raising=False)
    with pytest.raises(UnsafeNeo4jTarget):
        open_driver("bolt://localhost:7687", auth=("neo4j", "x"))
    assert called == []
    open_driver("bolt://localhost:7688", auth=("neo4j", "x"))
    assert len(called) == 1


_SCRIPT_FILES = sorted(p for p in SCRIPTS.glob("*.py") if p.name != "neo4j_target.py")


@pytest.mark.parametrize("path", _SCRIPT_FILES, ids=lambda p: p.name)
def test_no_script_bypasses_the_chokepoint(path):
    text = path.read_text()
    assert "bolt://localhost:7687" not in text, "hard-coded family-tree port"
    assert not re.search(r"GraphDatabase\.driver\(", text), (
        "open Neo4j drivers via neo4j_target.open_driver, never GraphDatabase.driver"
    )
