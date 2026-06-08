"""Safety: load_neo4j_v2 write paths must use database-scoped sessions.

Regression test for the Phase 0 finding that `--database` was parsed but never
passed to `driver.session()`, so an operator targeting a scratch DB would
silently write to the default (live) database.

Run: pytest tests/test_load_neo4j_v2_database_scope.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from load_neo4j_v2 import load_nodes, load_edges, apply_schema


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, *a, **k):
        return None


def _driver_recording_db():
    """Return (driver, calls) where calls['database'] captures the session db arg."""
    driver = MagicMock()
    calls = {"database": "__UNSCOPED__"}

    def session(**kwargs):
        # bare driver.session() (no database=) is the bug we forbid
        calls["database"] = kwargs.get("database", "__UNSCOPED__")
        return _FakeSession()

    driver.session.side_effect = session
    return driver, calls


def test_load_nodes_uses_database_scoped_session():
    driver, calls = _driver_recording_db()
    nodes = [{"id": "person-1", "labels": ["Person"], "node_type": "Person", "properties": {}}]
    load_nodes(driver, nodes, database="scratchdb")
    assert calls["database"] == "scratchdb"


def test_load_edges_uses_database_scoped_session():
    driver, calls = _driver_recording_db()
    edges = [{"relationship_type": "FILED_BY", "source_id": "a", "target_id": "b", "properties": {}}]
    load_edges(driver, edges, database="scratchdb")
    assert calls["database"] == "scratchdb"


def test_apply_schema_uses_database_scoped_session(tmp_path):
    driver, calls = _driver_recording_db()
    schema = tmp_path / "schema.cypher"
    schema.write_text("CREATE CONSTRAINT x IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE;")
    apply_schema(driver, schema, database="scratchdb")
    assert calls["database"] == "scratchdb"
