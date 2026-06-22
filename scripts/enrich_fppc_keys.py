"""enrich_fppc_keys.py — Open Marin Identity Enrichment, Lane 3 (`committee_id`).

Attaches the FPPC committee id (the CA SOS Cal-Access FILER_ID) as a hard
identity key to campaign-committee `Organization` (`org-*`) contributor nodes,
so the shipped graph-org-dedup deterministic tier merges name-variant committee
dups and keeps different-election-cycle committees DISTINCT (Bonta-AG-2022 vs
-2026 carry different FPPC ids). Third lane on the shipped machinery (Lane 1 EIN
`enrich_org_keys`, Lane 2 CA-SOS `enrich_casos_keys`); `org_resolution.py` is
NEVER edited — the `committee_id` normalizer is registered at runtime.

Sources (both read from disk; no network/DB in the loop):
  - tier 1: the `committee-netfile-*` filer nodes in the normalized campaign
    bundle already carry `netfile_filer_id` = the FPPC committee id.
  - tier 2: an operator-staged Cal-Access `FILERNAME_CD` extract (committee
    registry) for state committees + name aliases.

The lane proposes name(+election-year)-gated `committee_id` candidates; the
operator approves; approval attaches `committee_id` via the Identity Control A
ledger. A NAME match NEVER attaches a key without audited approval, and the lane
NEVER collapses two distinct FILER_IDs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from org_resolution import KEY_NORMALIZERS

_YEAR_TOKEN = re.compile(r"\b(?:19|20)\d{2}\b")


def _normalize_committee_id(value: Any) -> str | None:
    """Strict numeric FPPC committee id. Accepts a clean 1–9 digit numeric value
    (CAL Format allows ≤9); whitespace stripped; ints coerced. Anything else —
    `Pending`/`Unknown`, empty, overlength (>9 digits), or any non-digit
    character (letters, dots, an SOS-style `C` prefix) — is None (never a
    fabricated or wrong-shape key)."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text.isdigit() and 1 <= len(text) <= 9 else None


def register_committee_id_normalizer() -> None:
    """Idempotently register `_normalize_committee_id` under `"committee_id"` in
    the shared `KEY_NORMALIZERS`. Refuses to clobber a foreign registration (a
    stray mutation fails loud rather than silently winning). Called by every
    module that uses the key — `org_resolution.py` itself is never edited."""
    existing = KEY_NORMALIZERS.get("committee_id")
    if existing is None:
        KEY_NORMALIZERS["committee_id"] = _normalize_committee_id
    elif existing is not _normalize_committee_id:
        raise RuntimeError(
            "KEY_NORMALIZERS['committee_id'] is already registered to a different "
            f"callable ({existing!r}); refusing to clobber it"
        )


# ---------------------------------------------------------------------------
# Election-year token — the ONLY election_year source (Predeclared 4, Codex r2):
# a name-token regex. NEVER MoneyFlow.source_year (that's report year). A name
# with no year, or with >1 distinct year, yields None (ambiguous → withhold).
# ---------------------------------------------------------------------------


def _election_year(name: str) -> str | None:
    years = set(_YEAR_TOKEN.findall(name or ""))
    return next(iter(years)) if len(years) == 1 else None


# ---------------------------------------------------------------------------
# Tier 1 — filer spine (Predeclared 2). The `committee-netfile-*` nodes in the
# normalized campaign bundle already carry netfile_filer_id = the FPPC id.
# ---------------------------------------------------------------------------

_FILER_PREFIX = "committee-netfile-"


def filer_spine_refs(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keyed committee refs from `committee-netfile-*` Committee nodes (Pending
    skipped; non-committee nodes ignored). Each ref carries the normalized
    `committee_id`, display label, committee_type, and name-derived election_year."""
    refs: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("node_type") != "Committee" or not node.get("id", "").startswith(_FILER_PREFIX):
            continue
        props = node.get("properties", {})
        committee_id = _normalize_committee_id(props.get("netfile_filer_id"))
        if committee_id is None:
            continue  # "Pending"/unset — no FPPC id yet
        name = node.get("display_label") or props.get("name") or node["id"]
        refs.append({
            "committee_id": committee_id,
            "display_label": name,
            "committee_type": props.get("committee_type"),
            "election_year": _election_year(name),
            "source": "filer_spine",
        })
    return refs


def load_filer_spine(nodes_path: Path) -> list[dict[str, Any]]:
    """Filer spine from a normalized campaign bundle's nodes.jsonl on disk."""
    nodes = [
        json.loads(line)
        for line in Path(nodes_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return filer_spine_refs(nodes)


# ---------------------------------------------------------------------------
# Tier 2 — Cal-Access FILERNAME_CD (Predeclared 2/3). Operator-staged; the loop
# consumes a staged extract or a committed fixture (NEVER fetches). CP1252
# decode; allowlist committee FILER_TYPEs (NOT lobbying/individual); PRESERVE
# every (FILER_ID, NAML) alias as a matchable name (latest EFFECT_DT is display
# only — old aliases match historical contribution names).
# ---------------------------------------------------------------------------

# Committee-relevant FILER_TYPE descriptions (allowlist, NOT denylist — an
# unrecognized type is excluded). VERIFY against FILER_TYPES_CD.DESCRIPTION when
# staging the real dbwebexport (the exact strings can drift; this is a tunable
# constant, not a hard contract).
_CALACCESS_COMMITTEE_FILER_TYPES: frozenset[str] = frozenset({
    "RECIPIENT COMMITTEE", "CANDIDATE", "CANDIDATE/OFFICEHOLDER",
    "MAJOR DONOR", "INDEPENDENT EXPENDITURE COMMITTEE",
    "SLATE MAILER ORGANIZATION", "PROPONENT",
})


def parse_filername(path: Path, *, allowlist: frozenset[str] | None = None) -> list[dict[str, Any]]:
    """Parse a Cal-Access FILERNAME_CD extract (CP1252, tab-delimited, header
    row) into committee refs — one per (FILER_ID, NAML) alias row (all aliases
    preserved). Rows whose FILER_TYPE is not in the committee allowlist, or whose
    FILER_ID does not normalize to a clean committee_id, are dropped."""
    allow = allowlist if allowlist is not None else _CALACCESS_COMMITTEE_FILER_TYPES
    lines = Path(path).read_bytes().decode("cp1252").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    idx = {col: i for i, col in enumerate(header)}
    refs: list[dict[str, Any]] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")

        def cell(col: str) -> str:
            i = idx.get(col)
            return cells[i].strip() if i is not None and i < len(cells) else ""

        if cell("FILER_TYPE").upper() not in allow:
            continue
        committee_id = _normalize_committee_id(cell("FILER_ID"))
        if committee_id is None:
            continue
        name = cell("NAML")
        refs.append({
            "committee_id": committee_id,
            "display_label": name,
            "filer_type": cell("FILER_TYPE"),
            "election_year": _election_year(name),
            "xref_filer_id": cell("XREF_FILER_ID") or None,
            "status": cell("STATUS") or None,
            "source": "cal_access",
        })
    return refs
