#!/usr/bin/env python3
"""verify_neo4j_v2.py — Verification script for the Marin Civic Graph Neo4j v2 load.

Runs count checks and investigation smoke tests against a live Neo4j instance
that has been loaded with the migrated graph-v2 data.  This script IS the test
suite for the loaded graph; it should be run manually after load_neo4j_v2.py
completes.

Usage:
    python scripts/verify_neo4j_v2.py --password <secret>
    NEO4J_PASSWORD=secret python scripts/verify_neo4j_v2.py
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_gt(actual: Any, expected: Any, msg: str) -> None:
    assert actual > expected, f"{msg}: got {actual}, expected > {expected}"


def assert_eq(actual: Any, expected: Any, msg: str) -> None:
    assert actual == expected, f"{msg}: got {actual}, expected {expected}"


# ---------------------------------------------------------------------------
# Core verification runner
# ---------------------------------------------------------------------------

def run_verification(driver) -> dict:
    """Run all verification checks.

    Returns a dict with keys:
        checks      — list of {name, passed, error} dicts
        passed      — int count of passing checks
        failed      — int count of failing checks
    """
    checks: list[dict] = []

    def check(name: str, query: str, assertion_fn: Callable[[list[dict]], None]) -> None:
        with driver.session() as session:
            result = session.run(query)
            records = [dict(r) for r in result]
        try:
            assertion_fn(records)
            checks.append({"name": name, "passed": True, "error": None})
            print(f"  PASS  {name}")
        except AssertionError as e:
            checks.append({"name": name, "passed": False, "error": str(e)})
            print(f"  FAIL  {name} — {e}")

    # -----------------------------------------------------------------------
    # Node count checks
    # -----------------------------------------------------------------------

    check(
        "Person nodes exist",
        "MATCH (n:Person) RETURN count(n) AS cnt",
        lambda rs: assert_gt(rs[0]["cnt"], 0, "Person count"),
    )

    check(
        "Organization nodes exist",
        "MATCH (n:Organization) RETURN count(n) AS cnt",
        lambda rs: assert_gt(rs[0]["cnt"], 0, "Organization count"),
    )

    check(
        "Decision nodes exist (>1000)",
        "MATCH (n:Decision) RETURN count(n) AS cnt",
        lambda rs: assert_gt(rs[0]["cnt"], 1000, "Decision count"),
    )

    check(
        "Meeting nodes exist (>200)",
        "MATCH (n:Meeting) RETURN count(n) AS cnt",
        lambda rs: assert_gt(rs[0]["cnt"], 200, "Meeting count"),
    )

    check(
        "Filing nodes exist (>200)",
        "MATCH (n:Filing) RETURN count(n) AS cnt",
        lambda rs: assert_gt(rs[0]["cnt"], 200, "Filing count"),
    )

    check(
        "Record nodes exist (>500)",
        "MATCH (n:Record) RETURN count(n) AS cnt",
        lambda rs: assert_gt(rs[0]["cnt"], 500, "Record count"),
    )

    check(
        "No CaseParticipation nodes (migrated away)",
        "MATCH (n:CaseParticipation) RETURN count(n) AS cnt",
        lambda rs: assert_eq(rs[0]["cnt"], 0, "CaseParticipation count"),
    )

    check(
        "No Actor nodes (migrated away)",
        "MATCH (n:Actor) RETURN count(n) AS cnt",
        lambda rs: assert_eq(rs[0]["cnt"], 0, "Actor count"),
    )

    check(
        "No Institution nodes (migrated away)",
        "MATCH (n:Institution) RETURN count(n) AS cnt",
        lambda rs: assert_eq(rs[0]["cnt"], 0, "Institution count"),
    )

    check(
        "No EconomicInterestDisclosure nodes (migrated to Filing)",
        "MATCH (n:EconomicInterestDisclosure) RETURN count(n) AS cnt",
        lambda rs: assert_eq(rs[0]["cnt"], 0, "EconomicInterestDisclosure count"),
    )

    # -----------------------------------------------------------------------
    # Relationship checks
    # -----------------------------------------------------------------------

    check(
        "CAST_VOTE edges exist",
        "MATCH ()-[r:CAST_VOTE]->() RETURN count(r) AS cnt",
        lambda rs: assert_gt(rs[0]["cnt"], 0, "CAST_VOTE count"),
    )

    check(
        "PARTY_TO edges exist (from CaseParticipation conversion)",
        "MATCH ()-[r:PARTY_TO]->() RETURN count(r) AS cnt",
        lambda rs: assert_gt(rs[0]["cnt"], 0, "PARTY_TO count"),
    )

    check(
        "No CAST_VOTE_ON edges (renamed to CAST_VOTE)",
        "MATCH ()-[r:CAST_VOTE_ON]->() RETURN count(r) AS cnt",
        lambda rs: assert_eq(rs[0]["cnt"], 0, "CAST_VOTE_ON count"),
    )

    check(
        "No DECIDED_BY_INSTITUTION edges (renamed to DECIDED_BY)",
        "MATCH ()-[r:DECIDED_BY_INSTITUTION]->() RETURN count(r) AS cnt",
        lambda rs: assert_eq(rs[0]["cnt"], 0, "DECIDED_BY_INSTITUTION count"),
    )

    check(
        "EVIDENCED_BY edges exist (>5000)",
        "MATCH ()-[r:EVIDENCED_BY]->() RETURN count(r) AS cnt",
        lambda rs: assert_gt(rs[0]["cnt"], 5000, "EVIDENCED_BY count"),
    )

    # -----------------------------------------------------------------------
    # Investigation smoke tests
    # -----------------------------------------------------------------------

    check(
        "Kate Colin is a Person with CAST_VOTE edges (>50)",
        """
        MATCH (p:Person {id: 'person-kate-colin'})-[v:CAST_VOTE]->(d:Decision)
        RETURN p.name AS name, count(v) AS vote_count
        """,
        lambda rs: (
            assert_eq(len(rs), 1, "Kate Colin result row count"),
            assert_eq(rs[0]["name"], "Kate Colin", "Kate Colin name"),
            assert_gt(rs[0]["vote_count"], 50, "Kate Colin vote_count"),
        ),
    )

    check(
        "Boyd case has PARTY_TO edges",
        """
        MATCH (party)-[r:PARTY_TO]->(c:Case {id: 'case-boyd-v-city-of-san-rafael'})
        RETURN party.name AS name, r.role AS role
        ORDER BY role
        """,
        lambda rs: assert_gt(len(rs), 0, "Boyd PARTY_TO result count"),
    )

    check(
        "Merrydale project has linked decisions",
        """
        MATCH (d:Decision)-[:ABOUT_PROJECT]->(p:Project)
        WHERE p.id CONTAINS 'merrydale'
        RETURN count(d) AS cnt
        """,
        lambda rs: assert_gt(rs[0]["cnt"], 0, "Merrydale decision count"),
    )

    check(
        "MoneyFlow nodes have amounts",
        """
        MATCH (m:MoneyFlow) WHERE m.amount IS NOT NULL AND m.amount > 0
        RETURN count(m) AS cnt
        """,
        lambda rs: assert_gt(rs[0]["cnt"], 0, "MoneyFlow with amount count"),
    )

    check(
        "Multi-label Organization:Government nodes exist",
        "MATCH (o:Organization:Government) RETURN count(o) AS cnt",
        lambda rs: assert_gt(rs[0]["cnt"], 0, "Organization:Government count"),
    )

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------

    passed = sum(1 for c in checks if c["passed"])
    failed = sum(1 for c in checks if not c["passed"])

    return {"checks": checks, "passed": passed, "failed": failed}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Neo4j graph-v2 load")
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD"))
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    args = parser.parse_args()

    if not args.password:
        print("ERROR: --password or NEO4J_PASSWORD is required", file=sys.stderr)
        sys.exit(1)

    try:
        from neo4j import GraphDatabase  # noqa: PLC0415
    except ImportError:
        print("ERROR: neo4j driver not installed. Run: pip install neo4j", file=sys.stderr)
        sys.exit(1)

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Cannot connect to Neo4j at {args.uri} — {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Connected to Neo4j at {args.uri} (database={args.database})")
    print()

    results = run_verification(driver)
    driver.close()

    print()
    print(f"Results: {results['passed']} passed, {results['failed']} failed out of {len(results['checks'])} checks")

    if results["failed"]:
        print()
        print("Failed checks:")
        for c in results["checks"]:
            if not c["passed"]:
                print(f"  - {c['name']}: {c['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
