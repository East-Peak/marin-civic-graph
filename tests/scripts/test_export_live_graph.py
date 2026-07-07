from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from export_live_graph import (  # noqa: E402
    EDGES_PAGE_Q,
    NODES_PAGE_Q,
    collect_gate_counts,
    export_live_graph,
    main,
)


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def single(self) -> dict:
        return self._rows[0]

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self, nodes: list[dict] | None = None, edges: list[dict] | None = None):
        self.nodes = nodes or []
        self.edges = edges or []
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **params):
        self.calls.append((query, dict(params)))
        if query == NODES_PAGE_Q:
            skip = params["skip"]
            limit = params["limit"]
            return _FakeResult(self.nodes[skip : skip + limit])
        if query == EDGES_PAGE_Q:
            skip = params["skip"]
            limit = params["limit"]
            return _FakeResult(self.edges[skip : skip + limit])
        count_map = {
            "MATCH (n) RETURN count(n) AS c": 4,
            "MATCH ()-[r]->() RETURN count(r) AS c": 3,
            "MATCH (n:Membership) RETURN count(n) AS c": 2,
            "MATCH (n:EconomicInterest) RETURN count(n) AS c": 1,
            "MATCH ()-[r:SAME_AS]->() WHERE r.assertion_id IS NOT NULL RETURN count(r) AS c": 5,
            "MATCH ()-[r:INTEREST_IN]->() RETURN count(r) AS c": 7,
            "MATCH ()-[r:DISCLOSED_AS]->() RETURN count(r) AS c": 11,
            "MATCH ()-[r:MEMBER]->() RETURN count(r) AS c": 13,
            "MATCH ()-[r:MEMBER_OF_ORG]->() RETURN count(r) AS c": 17,
            "MATCH ()-[r:DERIVED_FROM_RECORD]->() RETURN count(r) AS c": 19,
        }
        if query in count_map:
            return _FakeResult([{"c": count_map[query]}])
        raise AssertionError(f"unexpected query: {query!r}")

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


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_export_writer_streams_mocked_driver_rows_in_pages(
    tmp_path: Path,
    capsys,
) -> None:
    session = _FakeSession(
        nodes=[
            {"id": "node-a", "labels": ["Organization"], "properties": {"name": "A"}},
            {"id": "node-b", "labels": ["Person"], "properties": {"name": "B"}},
            {"id": "node-c", "labels": ["Organization"], "properties": {"name": "C"}},
        ],
        edges=[
            {
                "start_id": "node-a",
                "end_id": "node-b",
                "type": "SAME_AS",
                "properties": {"assertion_id": "assertion-a"},
            },
            {
                "start_id": "node-b",
                "end_id": "node-c",
                "type": "MEMBER",
                "properties": {},
            },
        ],
    )
    driver = _FakeDriver(session)

    report = export_live_graph(
        driver,
        database="neo4j",
        out_dir=tmp_path,
        batch_size=2,
    )

    assert driver.session_calls == [{"database": "neo4j"}]
    assert _read_jsonl(tmp_path / "nodes.jsonl") == session.nodes
    assert _read_jsonl(tmp_path / "edges.jsonl") == session.edges
    assert report["totals"] == {"nodes": 3, "edges": 2}
    assert "nodes batch skip=0 wrote=2 total=2" in capsys.readouterr().out


def test_export_strips_embedding_umap_pending_and_payload_json_at_write(
    tmp_path: Path,
) -> None:
    session = _FakeSession(
        nodes=[
            {
                "id": "node-a",
                "labels": ["Organization"],
                "properties": {
                    "name": "A",
                    "embedding": [0.1],
                    "umap": "drop",
                    "umap_x": 1.2,
                    "umapVersion": 9,
                    "cluster_id_pending": "drop",
                    "payload_json": "{}",
                },
            }
        ],
        edges=[
            {
                "start_id": "node-a",
                "end_id": "node-b",
                "type": "RELATED_TO",
                "properties": {
                    "basis": "keep",
                    "embedding": [0.2],
                    "umap_y": 3.4,
                    "review_pending": True,
                    "payload_json": "{}",
                },
            }
        ],
    )

    export_live_graph(_FakeDriver(session), database="neo4j", out_dir=tmp_path, batch_size=50)

    node_props = _read_jsonl(tmp_path / "nodes.jsonl")[0]["properties"]
    edge_props = _read_jsonl(tmp_path / "edges.jsonl")[0]["properties"]
    assert node_props == {"name": "A"}
    assert edge_props == {"basis": "keep"}


def test_pagination_boundary_fetches_empty_page_after_exact_multiple(
    tmp_path: Path,
) -> None:
    session = _FakeSession(
        nodes=[
            {"id": "node-a", "labels": ["Organization"], "properties": {}},
            {"id": "node-b", "labels": ["Organization"], "properties": {}},
            {"id": "node-c", "labels": ["Organization"], "properties": {}},
            {"id": "node-d", "labels": ["Organization"], "properties": {}},
        ],
        edges=[
            {"start_id": "node-a", "end_id": "node-b", "type": "REL", "properties": {}},
            {"start_id": "node-c", "end_id": "node-d", "type": "REL", "properties": {}},
        ],
    )

    export_live_graph(_FakeDriver(session), database="neo4j", out_dir=tmp_path, batch_size=2)

    node_skips = [
        params["skip"] for query, params in session.calls if query == NODES_PAGE_Q
    ]
    edge_skips = [
        params["skip"] for query, params in session.calls if query == EDGES_PAGE_Q
    ]
    assert node_skips == [0, 2, 4]
    assert edge_skips == [0, 2]
    assert [row["id"] for row in _read_jsonl(tmp_path / "nodes.jsonl")] == [
        "node-a",
        "node-b",
        "node-c",
        "node-d",
    ]


def test_export_output_is_byte_deterministic(tmp_path: Path) -> None:
    session = _FakeSession(
        nodes=[
            {"id": "node-a", "labels": ["Organization"], "properties": {"b": 2, "a": 1}},
            {"id": "node-b", "labels": ["Person"], "properties": {"name": "B"}},
        ],
        edges=[
            {
                "start_id": "node-a",
                "end_id": "node-b",
                "type": "REL",
                "properties": {"z": 1, "a": 2},
            }
        ],
    )
    driver = _FakeDriver(session)

    export_live_graph(driver, database="neo4j", out_dir=tmp_path, batch_size=1)
    first_nodes = (tmp_path / "nodes.jsonl").read_bytes()
    first_edges = (tmp_path / "edges.jsonl").read_bytes()

    export_live_graph(driver, database="neo4j", out_dir=tmp_path, batch_size=1)

    assert (tmp_path / "nodes.jsonl").read_bytes() == first_nodes
    assert (tmp_path / "edges.jsonl").read_bytes() == first_edges


def test_counts_only_collects_g1_gate_counts() -> None:
    counts = collect_gate_counts(_FakeSession())

    assert counts == {
        "total_nodes": 4,
        "total_relationships": 3,
        "SAME_AS_with_assertion_id": 5,
        "Membership": 2,
        "EconomicInterest": 1,
        "INTEREST_IN": 7,
        "DISCLOSED_AS": 11,
        "MEMBER": 13,
        "MEMBER_OF_ORG": 17,
        "DERIVED_FROM_RECORD": 19,
    }


def test_cli_fails_clearly_when_neo4j_env_is_absent(monkeypatch, capsys) -> None:
    for key in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
        monkeypatch.delenv(key, raising=False)

    assert main(["--counts-only"]) == 1
    assert (
        "Missing required environment variables: NEO4J_URI, NEO4J_USER, "
        "NEO4J_PASSWORD, NEO4J_DATABASE"
    ) in capsys.readouterr().err
