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
    import hashlib
    from neo4j import GraphDatabase

    sys.path.insert(0, str(REPO / "scripts"))
    from canonical_type import canonical_type
    from outbound_policy import audit_log

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    renames_path = REPO / "data" / "cluster_renames_needed.json"
    if not renames_path.exists():
        print("no cluster_renames_needed.json; nothing to rename")
        return 0
    renames_needed: list[int] = json.loads(renames_path.read_text())
    if not renames_needed:
        print("renames_needed is empty; nothing to rename")
        return 0

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, password))

    # Name each cluster that needs renaming.
    name_rows: list[dict] = []
    with driver.session(database=database) as session:
        for cid in renames_needed:
            member_rows = list(session.run(
                "MATCH (n) WHERE n.cluster_id_pending = $cid "
                "RETURN n.id AS id, labels(n) AS labels, n.label AS label, "
                "       n.search_key_fact AS key_fact, "
                "       n.jurisdiction_name AS jurisdiction_name, "
                "       n.cluster_centroid_distance_pending AS dist "
                "ORDER BY dist ASC LIMIT 10",
                cid=cid,
            ))
            members = [
                {
                    "id": r["id"],
                    "label": r["label"] or r["id"],
                    "type": canonical_type(r["labels"], r["id"]),
                    "jurisdiction_name": r["jurisdiction_name"],
                    "key_fact": r["key_fact"],
                }
                for r in member_rows
            ]

            cluster_tokens = set(_tokens(" ".join(m.get("label", "") for m in members)))
            det = deterministic_candidate(members)

            llm_proposed: str | None = None
            if not args.dry_run and os.environ.get("ANTHROPIC_API_KEY"):
                prompt = (
                    "You're naming a cluster of civic-data entities.\n"
                    f"Deterministic candidate: \"{det}\"\n"
                    "Sample members:\n"
                    + "\n".join(
                        f"- {m.get('label', '')} ({m.get('type', '')}) · {m.get('key_fact', '')}"
                        for m in members
                    )
                    + "\nReturn a 3-5 word name that describes what's documented in these entities.\n"
                      "Be factual. Avoid \"influence\", \"controversial\", \"alleged\".\n"
                      "If you can't improve on the candidate, return it unchanged.\n"
                      "Output ONLY the name, no preamble."
                )
                client = anthropic.Anthropic()
                msg = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=50,
                    messages=[{"role": "user", "content": prompt}],
                )
                llm_proposed = msg.content[0].text.strip().strip('"').strip()
                validated = llm_proposed if validate_llm_name(llm_proposed, cluster_tokens) else None
                audit_log(
                    vendor="anthropic",
                    node_id=f"cluster:{cid}",
                    node_type="Cluster",
                    neighbor_ids_included=[m["id"] for m in members],
                    neighbor_ids_dropped=[],
                    prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),
                )
            else:
                validated = None

            final_name = apply_override(
                cluster_id=cid, deterministic=det, llm_proposed=validated
            )
            name_rows.append({"cid": cid, "name": final_name})

        if args.dry_run:
            print(f"dry-run: would rename {len(name_rows)} clusters")
            for row in name_rows:
                print(f"  cluster {row['cid']} → {row['name']!r}")
            driver.close()
            return 0

        # Write final names for renamed clusters.
        WRITE_BATCH = 500
        for i in range(0, len(name_rows), WRITE_BATCH):
            session.run(
                "UNWIND $rows AS row "
                "MATCH (n) WHERE n.cluster_id_pending = row.cid "
                "SET n.cluster_label_pending = row.name",
                rows=name_rows[i:i + WRITE_BATCH],
            )

        # Carry forward labels for clusters NOT in renames_needed.
        carry_over = list(session.run(
            "MATCH (n) WHERE n.cluster_id_pending IS NOT NULL AND n.cluster_label_pending IS NULL "
            "WITH DISTINCT n.cluster_id_pending AS cid "
            "MATCH (m) WHERE m.cluster_id = cid AND m.cluster_label IS NOT NULL "
            "RETURN cid, collect(DISTINCT m.cluster_label)[0] AS label"
        ))
        carry_rows = [{"cid": r["cid"], "name": r["label"]} for r in carry_over if r["label"]]
        if carry_rows:
            for i in range(0, len(carry_rows), WRITE_BATCH):
                session.run(
                    "UNWIND $rows AS row "
                    "MATCH (n) WHERE n.cluster_id_pending = row.cid "
                    "SET n.cluster_label_pending = row.name",
                    rows=carry_rows[i:i + WRITE_BATCH],
                )

    print(f"renamed: {len(name_rows)}; carried over: {len(carry_rows)}")
    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
