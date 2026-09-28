"""`--load-from <dir>`: load previously staged output without refetching (I5b).

Approved bytes == loaded bytes: the weekly runner stages each refetching
ingester's nodes.jsonl/edges.jsonl for review, then loads exactly those files.
Every fetch entry point is poisoned here, so a test fails loudly if load-only
mode ever touches the network. Neo4j is faked at ``neo4j_target.open_driver``,
the one chokepoint every load goes through.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import load_neo4j_v2  # noqa: E402
import neo4j_target  # noqa: E402

# module name -> (fetch entry points that must never run, fetch-only flags)
INGESTERS = {
    "ingest_socrata_permits": (
        ("fetch_page", "run_pipeline"),
        (["--load"], ["--limit", "5"], ["--output-dir", "x"]),
    ),
    "ingest_courtlistener_cases": (
        ("fetch_page", "run_pipeline"),
        (["--load"], ["--limit", "5"], ["--output-dir", "x"]),
    ),
    "ingest_form700": (
        ("_post_json", "fetch_filings_for_agency"),
        (["--load"], ["--limit", "5"], ["--output-dir", "x"], ["--floor-date", "2020-01-01"],
         ["--agency", "cmar"], ["--all"]),
    ),
}
NODES = [{"id": "n1", "node_type": "Place", "properties": {}}, {"id": "n2", "node_type": "Project", "properties": {}}]
EDGES = [{"source_id": "n2", "target_id": "n1", "relationship_type": "IN_JURISDICTION", "properties": {}}]


class FakeDriver:
    def verify_connectivity(self):
        pass

    def close(self):
        pass


@pytest.fixture
def staged(tmp_path: Path) -> Path:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in NODES))
    (staged / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in EDGES))
    return staged


@pytest.fixture
def neo4j(monkeypatch):
    """Record every driver opened and every node/edge batch loaded."""
    calls: dict[str, list] = {"open_driver": [], "nodes": [], "edges": []}

    def fake_open_driver(uri, auth=None, **kwargs):
        calls["open_driver"].append(uri)
        return FakeDriver()

    monkeypatch.setattr(neo4j_target, "open_driver", fake_open_driver)
    monkeypatch.setattr(load_neo4j_v2, "load_nodes", lambda d, nodes, **kw: calls["nodes"].extend(nodes) or {})
    monkeypatch.setattr(load_neo4j_v2, "load_edges", lambda d, edges, **kw: calls["edges"].extend(edges) or {})
    return calls


def _ingester(monkeypatch, name: str):
    module = importlib.import_module(name)
    fetchers, _ = INGESTERS[name]

    def no_fetch(*args, **kwargs):
        raise AssertionError(f"{name}: --load-from must never fetch")

    for attr in (*fetchers, "_write_jsonl"):
        monkeypatch.setattr(module, attr, no_fetch)
    return module


@pytest.mark.parametrize("name", INGESTERS)
def test_load_from_loads_staged_files_through_open_driver_without_fetching(monkeypatch, staged, neo4j, name):
    module = _ingester(monkeypatch, name)

    rc = module.main(["--load-from", str(staged), "--uri", "bolt://localhost:7688", "--password", "pw"])

    assert rc == 0
    assert neo4j["open_driver"] == ["bolt://localhost:7688"]
    assert neo4j["nodes"] == NODES
    assert neo4j["edges"] == EDGES


@pytest.mark.parametrize("name", INGESTERS)
def test_load_from_uses_the_same_load_function_as_load(monkeypatch, staged, name):
    module = _ingester(monkeypatch, name)
    loads = []
    monkeypatch.setattr(module, "_load_into_neo4j", lambda **kw: loads.append(kw))

    assert module.main(["--load-from", str(staged), "--password", "pw"]) == 0

    assert [(call["nodes"], call["edges"]) for call in loads] == [(NODES, EDGES)]


@pytest.mark.parametrize(
    "name,flag", [(name, flag) for name, (_, flags) in INGESTERS.items() for flag in flags]
)
def test_load_from_is_mutually_exclusive_with_fetching_flags(monkeypatch, staged, neo4j, name, flag):
    module = _ingester(monkeypatch, name)

    with pytest.raises(SystemExit) as exc:
        module.main(["--load-from", str(staged), "--password", "pw", *flag])

    assert exc.value.code == 2
    assert neo4j["open_driver"] == []


@pytest.mark.parametrize("name", INGESTERS)
def test_load_from_missing_staged_file_fails_before_connecting(monkeypatch, staged, neo4j, name):
    module = _ingester(monkeypatch, name)
    (staged / "edges.jsonl").unlink()

    assert module.main(["--load-from", str(staged), "--password", "pw"]) == 1
    assert neo4j["open_driver"] == []


@pytest.mark.parametrize("name", INGESTERS)
def test_load_from_requires_a_password(monkeypatch, staged, neo4j, name):
    module = _ingester(monkeypatch, name)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    assert module.main(["--load-from", str(staged), "--password", ""]) == 1
    assert neo4j["open_driver"] == []
