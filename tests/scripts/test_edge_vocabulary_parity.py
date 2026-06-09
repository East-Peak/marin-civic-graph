"""Py↔TS edge-vocabulary parity — scripts/edge_vocabulary.py is canonical,
app/src/lib/edge-vocabulary.ts is the hand-maintained mirror (its
PHASE2_WHITELIST_LIVE is a sorted snapshot, deliberately not re-derived).
This test parses the TS literals and proves both stacks agree, so an edge
added on one side without the other (the M2a MEMBER/MEMBER_OF_ORG case)
fails loudly instead of silently drifting the radial-hero/explorer
traversal away from the signature-subgraph builder.

Pure text-parse tests; no Node runtime, no Neo4j connection.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from edge_vocabulary import (  # noqa: E402
    LEGAL_EDGES_LIVE,
    MONEY_EDGES_LIVE,
    PHASE2_WHITELIST_LIVE,
    SPEC_TO_LIVE,
    UNIVERSAL_EDGES_LIVE,
)

TS_PATH = REPO_ROOT / "app" / "src" / "lib" / "edge-vocabulary.ts"
# Strip // comments so commentary like "UNDER_AGREEMENT: no strong live edge"
# can never be parsed as an entry.
TS_SOURCE = re.sub(r"//[^\n]*", "", TS_PATH.read_text())


def ts_array(name: str) -> list[str]:
    """Extract `export const <name>: string[] = [ ... ];` as a list of strings."""
    m = re.search(
        rf"export const {name}: string\[\] = \[(.*?)\];", TS_SOURCE, re.S
    )
    assert m, f"export const {name} not found in edge-vocabulary.ts"
    return re.findall(r'"([A-Z_]+)"', m.group(1))


def ts_spec_to_live() -> dict[str, list[str]]:
    """Extract the SPEC_TO_LIVE record literal as a dict of string lists."""
    m = re.search(
        r"export const SPEC_TO_LIVE: Record<string, string\[\]> = \{(.*?)\n\};",
        TS_SOURCE,
        re.S,
    )
    assert m, "export const SPEC_TO_LIVE not found in edge-vocabulary.ts"
    return {
        key: re.findall(r'"([A-Z_]+)"', values)
        for key, values in re.findall(r"(\w+):\s*\[([^\]]*)\]", m.group(1))
    }


def test_spec_to_live_parity():
    assert ts_spec_to_live() == SPEC_TO_LIVE


def test_phase2_whitelist_parity():
    # The TS snapshot must equal the Python-derived whitelist, order included
    # (both are sorted) — a stale snapshot is exactly the drift this catches.
    assert ts_array("PHASE2_WHITELIST_LIVE") == PHASE2_WHITELIST_LIVE


def test_universal_edges_parity():
    assert ts_array("UNIVERSAL_EDGES_LIVE") == UNIVERSAL_EDGES_LIVE


def test_money_edges_parity():
    assert ts_array("MONEY_EDGES_LIVE") == MONEY_EDGES_LIVE


def test_legal_edges_parity():
    assert ts_array("LEGAL_EDGES_LIVE") == LEGAL_EDGES_LIVE
