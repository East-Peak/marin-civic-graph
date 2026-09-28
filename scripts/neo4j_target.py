"""The single chokepoint for opening Neo4j drivers in pipeline scripts.

Why this exists: on the operator machine, port 7687 is the default Homebrew
Neo4j store, which holds an UNRELATED family-tree database. Open Marin's
operator graph is a dedicated instance at bolt://localhost:7688. Aura
(*.neo4j.io) was deleted 2026-07-08. A script that silently defaulted to 7687,
or still pointed at Aura, could read the wrong graph or, via --wipe, destroy
one. So every script opens drivers through ``open_driver``, and a repo test
enforces that no script calls ``GraphDatabase.driver`` directly.

Escape hatch: ``OPEN_MARIN_ALLOW_UNSAFE_TARGET=1`` (prints a loud warning).
"""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from urllib.parse import urlsplit

from neo4j import GraphDatabase

FAMILY_TREE_PORT = 7687  # also the bolt/neo4j scheme default when no port is given
ESCAPE_HATCH = "OPEN_MARIN_ALLOW_UNSAFE_TARGET"
_REFUSED_HOST_MARKERS = ("neo4j.io", "aura")


class UnsafeNeo4jTarget(RuntimeError):
    """Raised instead of connecting to a Neo4j that isn't Open Marin's."""


def check_target(uri: str | None, env: Mapping[str, str] = os.environ) -> str:
    """Return ``uri`` if it is a safe Open Marin target, else raise."""
    if not uri:
        raise UnsafeNeo4jTarget(
            "NEO4J_URI is not set. Open Marin's operator graph is bolt://localhost:7688 "
            "(see app/.env.local); there is deliberately no default."
        )
    parts = urlsplit(uri)
    host = (parts.hostname or "").lower()
    port = parts.port or FAMILY_TREE_PORT

    reason = None
    if port == FAMILY_TREE_PORT:
        reason = (
            f"port {FAMILY_TREE_PORT} is the default Homebrew Neo4j store, which holds an "
            "unrelated family-tree database. Open Marin uses bolt://localhost:7688"
        )
    elif any(marker in host for marker in _REFUSED_HOST_MARKERS):
        reason = "Aura (neo4j.io) was deleted 2026-07-08; Open Marin uses bolt://localhost:7688"

    if reason is None:
        return uri
    if env.get(ESCAPE_HATCH) == "1":
        print(f"WARNING: UNSAFE Neo4j target {uri!r} allowed by {ESCAPE_HATCH}=1 — {reason}",
              file=sys.stderr)
        return uri
    raise UnsafeNeo4jTarget(f"refusing to connect to {uri!r}: {reason}. "
                            f"(Override with {ESCAPE_HATCH}=1 only if you are certain.)")


def open_driver(uri: str | None, auth=None, **kwargs):
    """Validate ``uri`` with ``check_target``, then open a driver."""
    return GraphDatabase.driver(check_target(uri), auth=auth, **kwargs)
