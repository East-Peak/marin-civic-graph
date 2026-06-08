"""Frozen baseline exporter with live-graph preflight (Open Marin Phase 0, Milestone A).

Read-only against the live Aura graph. Connects, asserts the connected host is
*exactly* the production Aura host (a wrong large graph must not satisfy the
floors), asserts count floors, and streams a canonical node+rel export to
``data/baseline/<host>-<ts>.jsonl`` plus a ``.sha256`` sidecar and a small
manifest. It NEVER writes/MERGEs/wipes the graph.

The pure helpers below are unit-tested without a live DB.
"""
from __future__ import annotations
import json, hashlib, os, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# The one production Aura host this exporter is allowed to read. A wrong large
# graph (or a stale local one that happened to clear the floors) must not pass.
EXPECTED_AURA_HOST = "26fb9605.databases.neo4j.io"

# Read-only Cypher. These are module constants so tests can stand in a fake
# session that recognises each query exactly.
COUNT_NODES_Q = "MATCH (n) RETURN count(n) AS c"
COUNT_RELS_Q = "MATCH ()-[r]->() RETURN count(r) AS c"
PER_LABEL_Q = "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS c"
NODES_Q = "MATCH (n) RETURN n AS n"
RELS_Q = ("MATCH (s)-[r]->(t) "
          "RETURN s.id AS source, t.id AS target, type(r) AS type, properties(r) AS props")

# Hard floors derived from the verified live graph (2026-06): ~112K nodes / ~140K rels.
FLOORS = {"total_nodes": 100_000, "total_rels": 120_000,
          "labels": {"Person": 5_000, "Organization": 1_000, "MoneyFlow": 9_000,
                     "Filing": 8_000, "Project": 40_000}}


def assert_live_graph_floors(total_nodes, total_rels, per_label):
    if total_nodes < FLOORS["total_nodes"]:
        raise ValueError(f"total_nodes {total_nodes} below floor {FLOORS['total_nodes']}")
    if total_rels < FLOORS["total_rels"]:
        raise ValueError(f"total_rels {total_rels} below floor {FLOORS['total_rels']}")
    for label, floor in FLOORS["labels"].items():
        if per_label.get(label, 0) < floor:
            raise ValueError(f"label {label} count {per_label.get(label,0)} below floor {floor}")


def _jsonify(value):
    """Coerce a Neo4j property value to a JSON-serializable form.

    Live props include neo4j.time temporal types (DateTime/Date/Time) and
    spatial Points which json.dumps cannot encode. Temporals expose
    ``isoformat()``; everything else unknown falls back to ``str()``. Native
    JSON types and (nested) lists/dicts pass through unchanged.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return iso()
    return str(value)


def canonical_node_record(node):
    return {"id": node["id"], "labels": sorted(node["labels"]),
            "props": {k: _jsonify(v) for k, v in sorted(node["props"].items())}}


def canonical_rel_record(rel):
    return {"source": rel["source"], "target": rel["target"], "type": rel["type"],
            "props": {k: _jsonify(v) for k, v in sorted(rel["props"].items())}}


def export_sha256(rows):
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def aura_host(uri: str) -> str:
    return urlparse(uri).hostname or ""


def assert_expected_host(uri: str) -> str:
    """Assert the URI points at the one production Aura host. Returns the host."""
    host = aura_host(uri)
    if host != EXPECTED_AURA_HOST:
        raise ValueError(
            f"connected host {host!r} is not the expected Aura host "
            f"{EXPECTED_AURA_HOST!r} — refusing to export (uri={uri!r})")
    return host


# ---------------------------------------------------------------------------
# Live read-only export (requires a driver; exercised by a fake in tests)
# ---------------------------------------------------------------------------

def graph_counts(session):
    """Count total nodes, total rels and per-label node counts (read-only)."""
    total_nodes = session.run(COUNT_NODES_Q).single()["c"]
    total_rels = session.run(COUNT_RELS_Q).single()["c"]
    per_label = {row["label"]: row["c"] for row in session.run(PER_LABEL_Q)}
    return total_nodes, total_rels, per_label


def iter_node_records(session):
    for row in session.run(NODES_Q):
        node = row["n"]
        yield canonical_node_record(
            {"id": node["id"], "labels": list(node.labels), "props": dict(node)})


def iter_rel_records(session):
    for row in session.run(RELS_Q):
        yield canonical_rel_record(
            {"source": row["source"], "target": row["target"],
             "type": row["type"], "props": dict(row["props"])})


def _row_line(row) -> str:
    """Canonical one-line JSON for a row — identical bytes to export_sha256's."""
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def export_baseline(driver, *, database, out_dir, host, timestamp):
    """Stream a frozen, canonical node+rel baseline within a DATABASE-SCOPED
    session. Refuses to overwrite an existing baseline. Pure reads only.

    NOTE: load_neo4j_v2.py opens a BARE ``driver.session()`` — do NOT copy that.
    We scope to ``database`` so we cannot accidentally read the default db.
    """
    out_dir = Path(out_dir)
    baseline_path = out_dir / f"{host}-{timestamp}.jsonl"
    if baseline_path.exists():
        raise FileExistsError(f"refusing to overwrite existing baseline {baseline_path}")

    with driver.session(database=database) as session:
        total_nodes, total_rels, per_label = graph_counts(session)
        assert_live_graph_floors(total_nodes, total_rels, per_label)

        out_dir.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        with baseline_path.open("w", encoding="utf-8") as fh:
            for rec in iter_node_records(session):
                line = _row_line({"kind": "node", **rec})
                h.update(line.encode()); fh.write(line + "\n")
            for rec in iter_rel_records(session):
                line = _row_line({"kind": "rel", **rec})
                h.update(line.encode()); fh.write(line + "\n")
    sha256 = h.hexdigest()

    sha_path = baseline_path.with_suffix(baseline_path.suffix + ".sha256")
    sha_path.write_text(f"{sha256}  {baseline_path.name}\n", encoding="utf-8")
    manifest = {"host": host, "database": database, "timestamp": timestamp,
                "total_nodes": total_nodes, "total_rels": total_rels,
                "per_label": per_label, "sha256": sha256,
                "baseline_file": baseline_path.name}
    manifest_path = baseline_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    return {**manifest, "baseline_path": str(baseline_path)}


def load_env_file(path) -> dict:
    """Parse a KEY=VALUE .env file explicitly (no reliance on process env)."""
    env = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        env[key.strip()] = val
    return env


def main(argv=None) -> int:
    from neo4j import GraphDatabase

    repo_root = Path(__file__).resolve().parent.parent
    env = load_env_file(repo_root / "app" / ".env.local")
    uri = env["NEO4J_URI"]
    user = env["NEO4J_USER"]
    password = env["NEO4J_PASSWORD"]
    database = env.get("NEO4J_DATABASE", "neo4j")

    host = assert_expected_host(uri)  # hard stop unless it's the production host
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = repo_root / "data" / "baseline"

    print(f"Connecting read-only to {host} (database={database})")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        result = export_baseline(driver, database=database, out_dir=out_dir,
                                 host=host, timestamp=timestamp)
    finally:
        driver.close()

    print(f"host asserted: {result['host']}")
    print(f"total_nodes:   {result['total_nodes']}")
    print(f"total_rels:    {result['total_rels']}")
    print(f"per_label:     {json.dumps(result['per_label'], sort_keys=True)}")
    print(f"sha256:        {result['sha256']}")
    print(f"baseline:      {result['baseline_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
