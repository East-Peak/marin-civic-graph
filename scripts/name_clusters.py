"""Deterministic candidate + Haiku improvement + validation + override.

Spec §9.6. Pure functions tested in isolation; the LLM call (anthropic
SDK) lives in run_llm_naming(), only invoked by main() during the
rehearsal.

CLI:
  python scripts/name_clusters.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# `anthropic` import allowed only here per outbound_policy lint rule.
import anthropic  # noqa: F401

REPO = Path(__file__).resolve().parent.parent

BANNED_TERMS = {
    "influence", "controversial", "scandal", "scandalous", "alleged",
    "corrupt", "corruption", "shady", "questionable",
}

STOP_WORDS = {
    "the", "a", "an", "of", "for", "and", "or", "in", "on", "at",
    "to", "by", "with", "from", "is", "as", "this",
}


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-zA-Z]+", (s or "").lower())
            if t and t not in STOP_WORDS]


def deterministic_candidate(members: list[dict]) -> str:
    """Build a baseline name without LLM: jurisdiction + type + top-token."""
    if not members:
        return "Unnamed cluster"
    juris = Counter(m.get("jurisdiction_name") for m in members
                    if m.get("jurisdiction_name"))
    types = Counter(m.get("type") for m in members if m.get("type"))
    tokens: Counter[str] = Counter()
    for m in members:
        for t in _tokens(m.get("label", "")):
            tokens[t] += 1
    parts = []
    if juris:
        parts.append(juris.most_common(1)[0][0])
    if types:
        parts.append(types.most_common(1)[0][0])
    top_tok = [t for t, _ in tokens.most_common(3)]
    if top_tok:
        parts.append(top_tok[0])
    return " · ".join(parts) if parts else "Unnamed cluster"


def validate_llm_name(name: str, cluster_tokens: set[str]) -> bool:
    """True iff the proposed LLM name passes spec §9.6 validation."""
    name = (name or "").strip()
    if not name:
        return False
    words = name.split()
    if len(words) < 2 or len(words) > 7:
        return False
    lower = name.lower()
    for banned in BANNED_TERMS:
        if banned in lower:
            return False
    name_toks = set(_tokens(name))
    return bool(name_toks & cluster_tokens)


def apply_override(*, cluster_id: int, deterministic: str,
                   llm_proposed: str | None) -> str:
    """Override registry > validated LLM > deterministic candidate."""
    path = Path(os.environ.get(
        "CLUSTER_NAME_OVERRIDES_PATH",
        str(REPO / "scripts" / "cluster_name_overrides.json"),
    ))
    if path.exists():
        try:
            registry = json.loads(path.read_text())
        except json.JSONDecodeError:
            registry = {}
        if str(cluster_id) in registry:
            return registry[str(cluster_id)]
    if llm_proposed:
        return llm_proposed
    return deterministic


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # run_llm_naming() body filled in during Task 16 rehearsal — sends
    # samples to claude-haiku-4-5-20251001 via outbound_policy.audit_log.
    print("name_clusters.main() is a stub at this commit (Task 16 fills it in)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
