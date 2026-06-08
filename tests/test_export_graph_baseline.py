import json, hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from export_graph_baseline import (
    assert_live_graph_floors, canonical_node_record, canonical_rel_record, export_sha256,
    assert_expected_host, export_baseline, EXPECTED_AURA_HOST,
    COUNT_NODES_Q, COUNT_RELS_Q, PER_LABEL_Q, NODES_Q, RELS_Q,
)

def test_floors_reject_undersized_graph():
    # ~112K nodes expected; a 6K stale/local graph must be rejected
    import pytest
    with pytest.raises(ValueError, match="below floor"):
        assert_live_graph_floors(total_nodes=6000, total_rels=20000,
                                 per_label={"Person": 6000})

def test_floors_accept_live_sized_graph():
    assert_live_graph_floors(
        total_nodes=112000, total_rels=140000,
        per_label={"Person": 6000, "Organization": 1300, "MoneyFlow": 11000,
                   "Filing": 10000, "Project": 49000},
    )  # returns None, no raise

def test_canonical_node_record_is_stable_and_sorted():
    rec = canonical_node_record(
        {"id": "person-x", "labels": ["Person"], "props": {"b": 2, "a": 1}})
    assert list(rec["props"].keys()) == ["a", "b"]   # sorted for stable hashing
    assert rec["id"] == "person-x"


class _FakeDateTime:
    """Stands in for neo4j.time.DateTime — not JSON-serializable, has isoformat()."""
    def isoformat(self): return "2020-01-02T03:04:05"


class _FakePoint:
    def __str__(self): return "POINT(-122.5 37.9)"


def test_canonical_node_record_coerces_neo4j_temporal_props_to_json():
    # Live Aura props include neo4j.time.DateTime values; canonical facts must be
    # JSON-serializable so the baseline JSONL can be written and re-read.
    rec = canonical_node_record(
        {"id": "filing-1", "labels": ["Filing"],
         "props": {"filed_at": _FakeDateTime(), "loc": _FakePoint(), "n": 3}})
    assert rec["props"]["filed_at"] == "2020-01-02T03:04:05"
    assert rec["props"]["loc"] == "POINT(-122.5 37.9)"
    assert rec["props"]["n"] == 3
    json.dumps(rec)  # must not raise


def test_canonical_rel_record_coerces_neo4j_temporal_props_to_json():
    rec = canonical_rel_record(
        {"source": "a", "target": "b", "type": "FILED_BY",
         "props": {"observed_at": _FakeDateTime()}})
    assert rec["props"]["observed_at"] == "2020-01-02T03:04:05"
    json.dumps(rec)  # must not raise

def test_export_sha256_is_deterministic():
    rows = [{"id": "a"}, {"id": "b"}]
    assert export_sha256(rows) == export_sha256(list(rows))


# --- live-preflight guardrails (no real DB; a fake driver stands in) ---

def test_assert_expected_host_rejects_localhost():
    # load_neo4j_v2.py defaults to bolt://localhost:7687 — a wrong/local graph
    # must never be accepted, even if it happened to clear the floors.
    with pytest.raises(ValueError, match="expected"):
        assert_expected_host("bolt://localhost:7687")
    with pytest.raises(ValueError, match="expected"):
        assert_expected_host("neo4j+s://127.0.0.1:7687")


def test_assert_expected_host_accepts_production_aura():
    host = assert_expected_host(f"neo4j+s://{EXPECTED_AURA_HOST}")
    assert host == EXPECTED_AURA_HOST == "26fb9605.databases.neo4j.io"


class _FakeResult:
    def __init__(self, rows): self._rows = rows
    def single(self): return self._rows[0]
    def __iter__(self): return iter(self._rows)


class _FakeSession:
    """Returns floor-clearing counts and empty node/rel streams."""
    def __init__(self): self.queries = []
    def run(self, query, **kw):
        self.queries.append(query)
        if query == COUNT_NODES_Q: return _FakeResult([{"c": 112000}])
        if query == COUNT_RELS_Q: return _FakeResult([{"c": 140000}])
        if query == PER_LABEL_Q:
            return _FakeResult([
                {"label": "Person", "c": 6000}, {"label": "Organization", "c": 1300},
                {"label": "MoneyFlow", "c": 11000}, {"label": "Filing", "c": 10000},
                {"label": "Project", "c": 49000}])
        if query in (NODES_Q, RELS_Q): return _FakeResult([])
        raise AssertionError(f"unexpected query: {query!r}")
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _FakeDriver:
    def __init__(self, session): self._session = session; self.session_calls = []
    def session(self, **kw): self.session_calls.append(kw); return self._session


def test_export_uses_database_scoped_session(tmp_path):
    # load_neo4j_v2.py uses a BARE driver.session(); the exporter must scope to
    # the configured database so it cannot read the wrong (default) database.
    driver = _FakeDriver(_FakeSession())
    result = export_baseline(driver, database="neo4j", out_dir=tmp_path,
                             host=EXPECTED_AURA_HOST, timestamp="20260608T000000Z")
    assert driver.session_calls == [{"database": "neo4j"}]
    assert result["total_nodes"] == 112000 and result["total_rels"] == 140000


def test_export_refuses_to_overwrite_existing_baseline(tmp_path):
    (tmp_path / f"{EXPECTED_AURA_HOST}-20260608T000000Z.jsonl").write_text("pre-existing")
    driver = _FakeDriver(_FakeSession())
    with pytest.raises(FileExistsError):
        export_baseline(driver, database="neo4j", out_dir=tmp_path,
                        host=EXPECTED_AURA_HOST, timestamp="20260608T000000Z")
