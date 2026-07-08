from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from restore_neo4j_local import (  # noqa: E402
    assert_local_target,
    restore_neo4j_local,
)


class _FakeResult:
    def __init__(self, rows: list[dict] | None = None):
        self._rows = rows or []

    def __iter__(self):
        return iter(self._rows)

    def single(self) -> dict:
        return self._rows[0]


class _FakeSession:
    def __init__(self, *, existing_nodes: int = 0, summary_nodes: int = 0, summary_rels: int = 0):
        self.existing_nodes = existing_nodes
        self.summary_nodes = summary_nodes
        self.summary_rels = summary_rels
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **params):
        self.calls.append((query, dict(params)))
        if query == "MATCH (n) RETURN count(n) AS c":
            return _FakeResult([{"c": self.existing_nodes}])
        if query == "MATCH (n) RETURN count(n) AS nodes":
            return _FakeResult([{"nodes": self.summary_nodes}])
        if query == "MATCH ()-[r]->() RETURN count(r) AS relationships":
            return _FakeResult([{"relationships": self.summary_rels}])
        return _FakeResult()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeDriver:
    def __init__(self, session: _FakeSession):
        self._session = session
        self.session_calls: list[dict] = []

    def session(self, **kwargs):
        self.session_calls.append(kwargs)
        return self._session


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_export(tmp_path: Path, *, nodes: list[dict], edges: list[dict] | None = None) -> Path:
    export_dir = tmp_path / "live-graph-export"
    _write_jsonl(export_dir / "nodes.jsonl", nodes)
    _write_jsonl(export_dir / "edges.jsonl", edges or [])
    return export_dir


def _queries(session: _FakeSession) -> list[str]:
    return [query for query, _params in session.calls]


def test_node_label_combination_batches_emit_literal_label_cypher(tmp_path: Path) -> None:
    export_dir = _write_export(
        tmp_path,
        nodes=[
            {
                "id": "org-1",
                "labels": ["Organization", "Government"],
                "properties": {"name": "County"},
            },
            {
                "id": "org-2",
                "labels": ["Organization"],
                "properties": {"name": "Vendor"},
            },
            {
                "id": "person-1",
                "labels": ["Person"],
                "properties": {"name": "Ada"},
            },
        ],
    )
    session = _FakeSession(summary_nodes=3, summary_rels=0)

    restore_neo4j_local(
        _FakeDriver(session),
        database="neo4j",
        export_dir=export_dir,
        batch_size=100,
        progress=None,
    )

    queries = "\n\n".join(_queries(session))
    assert "FOR (n:`Organization`) REQUIRE n.id IS UNIQUE" in queries
    assert "FOR (n:`Person`) REQUIRE n.id IS UNIQUE" in queries
    assert "MERGE (n:`Organization` {id: row.id})" in queries
    assert "SET n:`Organization`:`Government`" in queries
    assert "SET n:`Organization`" in queries
    assert "MERGE (n:`Person` {id: row.id})" in queries
    assert "apoc" not in queries.lower()
    assert "$labels" not in queries


def test_relationship_type_batches_emit_literal_relationship_cypher(tmp_path: Path) -> None:
    export_dir = _write_export(
        tmp_path,
        nodes=[
            {"id": "org-1", "labels": ["Organization"], "properties": {}},
            {"id": "person-1", "labels": ["Person"], "properties": {}},
        ],
        edges=[
            {
                "start_id": "org-1",
                "end_id": "person-1",
                "type": "SAME_AS",
                "properties": {"assertion_id": "a1"},
            },
            {
                "start_id": "person-1",
                "end_id": "org-1",
                "type": "MEMBER",
                "properties": {},
            },
        ],
    )
    session = _FakeSession(summary_nodes=2, summary_rels=2)

    restore_neo4j_local(
        _FakeDriver(session),
        database="neo4j",
        export_dir=export_dir,
        batch_size=100,
        progress=None,
    )

    queries = "\n\n".join(_queries(session))
    assert "MERGE (s)-[r:`SAME_AS`]->(t)" in queries
    assert "MERGE (s)-[r:`MEMBER`]->(t)" in queries
    assert "$type" not in queries
    assert "apoc" not in queries.lower()


@pytest.mark.parametrize(
    "uri",
    [
        "neo4j+s://26fb9605.databases.neo4j.io",
        "bolt://local-aura-proxy",
    ],
)
def test_aura_guard_refuses_nonlocal_uris_without_explicit_override(uri: str) -> None:
    with pytest.raises(ValueError, match="Refusing to restore into non-local Neo4j URI"):
        assert_local_target(uri, override=False)

    assert_local_target(uri, override=True)


def test_wipe_runs_before_constraints_and_load(tmp_path: Path, capsys) -> None:
    export_dir = _write_export(
        tmp_path,
        nodes=[{"id": "org-1", "labels": ["Organization"], "properties": {}}],
    )
    session = _FakeSession(existing_nodes=42, summary_nodes=1, summary_rels=0)

    restore_neo4j_local(
        _FakeDriver(session),
        database="neo4j",
        export_dir=export_dir,
        batch_size=100,
        wipe=True,
    )

    queries = _queries(session)
    wipe_index = next(i for i, query in enumerate(queries) if "DETACH DELETE n" in query)
    first_constraint_or_load = next(
        i
        for i, query in enumerate(queries)
        if query.startswith("CREATE CONSTRAINT") or "MERGE (n:" in query
    )
    assert wipe_index < first_constraint_or_load
    assert "wipe requested; existing nodes=42" in capsys.readouterr().out


def test_summary_queries_are_issued_and_returned(tmp_path: Path) -> None:
    export_dir = _write_export(
        tmp_path,
        nodes=[{"id": "org-1", "labels": ["Organization"], "properties": {}}],
        edges=[],
    )
    session = _FakeSession(summary_nodes=111, summary_rels=222)

    report = restore_neo4j_local(
        _FakeDriver(session),
        database="neo4j",
        export_dir=export_dir,
        batch_size=100,
        progress=None,
    )

    assert "MATCH (n) RETURN count(n) AS nodes" in _queries(session)
    assert "MATCH ()-[r]->() RETURN count(r) AS relationships" in _queries(session)
    assert report["restored"] == {"nodes": 1, "relationships": 0}
    assert report["database_counts"] == {"nodes": 111, "relationships": 222}
