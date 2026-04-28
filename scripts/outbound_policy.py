"""Outbound-call gatekeeper. ALL OpenAI/Anthropic synthesis calls in the
pipeline MUST pass through this module so the per-type eligibility,
neighbor filtering, and redaction policies are uniformly enforced.

Direct `import openai` or `import anthropic` outside this module is
forbidden — see lint rule in scripts/_lint_check_outbound.py (Task 3).
"""
from __future__ import annotations

from canonical_type import ALL_TYPES

# Default-deny baseline. v2 ships the entire 21-type ontology as eligible
# because it's all-public civic data. Future sensitive lanes (criminal
# records, sealed filings, etc.) will land in INELIGIBLE_TYPES.
ELIGIBLE_TYPES: set[str] = set(ALL_TYPES)

INELIGIBLE_TYPES: set[str] = set()

# Per-type fields stripped from synthesis text before outbound. Any new
# entity type with sensitive fields must be added here.
REDACT_FIELDS: dict[str, list[str]] = {
    "Person": ["home_address", "phone", "email", "dob"],
}


def is_eligible(node_type: str) -> bool:
    """True iff a node of this type may be sent to OpenAI/Anthropic."""
    return node_type in ELIGIBLE_TYPES and node_type not in INELIGIBLE_TYPES


def _redacted_props(node: dict) -> dict:
    """Return a copy of the node with REDACT_FIELDS stripped."""
    redacted_keys = REDACT_FIELDS.get(node.get("type", ""), [])
    return {k: v for k, v in node.items() if k not in redacted_keys}


def synthesize_outbound_text(node: dict, neighbors: list[dict]) -> str:
    """Build the embedding/cluster-naming text for a node.

    Returns "" if the anchor is ineligible. Neighbors of ineligible types
    are dropped entirely from the synthesis (graph-level enforcement, not
    just node-level redaction).
    """
    anchor_type = node.get("type", "")
    if not is_eligible(anchor_type):
        return ""

    safe_anchor = _redacted_props(node)
    eligible_neighbors = [
        _redacted_props(n) for n in neighbors
        if is_eligible(n.get("type", ""))
    ]

    lines = [
        f"{anchor_type} · {safe_anchor.get('label', safe_anchor.get('id', ''))}",
    ]
    role = safe_anchor.get("role") or safe_anchor.get("description")
    if role:
        lines.append(role)
    juris = safe_anchor.get("jurisdiction_name") or safe_anchor.get("jurisdiction")
    if juris:
        lines.append(f"Jurisdiction: {juris}")
    if eligible_neighbors:
        lines.append("Recent activity:")
        for n in eligible_neighbors[:5]:
            lines.append(
                f"- {n.get('label', n.get('id', ''))} ({n.get('type', '')})"
            )
    return "\n".join(lines)


import json
import os
from datetime import datetime, timezone
from pathlib import Path


def audit_log(
    *,
    vendor: str,
    node_id: str,
    node_type: str,
    neighbor_ids_included: list[str],
    neighbor_ids_dropped: list[str],
    prompt_hash: str,
) -> None:
    """Append one outbound-call record to the JSONL audit file.

    Path overridable via OUTBOUND_AUDIT_PATH env (used by tests).
    Default: <repo>/data/outbound_audit.jsonl.
    """
    default_path = (
        Path(__file__).resolve().parent.parent / "data" / "outbound_audit.jsonl"
    )
    path = Path(os.environ.get("OUTBOUND_AUDIT_PATH", str(default_path)))
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vendor": vendor,
        "node_id": node_id,
        "node_type": node_type,
        "neighbor_ids_included": neighbor_ids_included,
        "neighbor_ids_dropped": neighbor_ids_dropped,
        "prompt_hash": prompt_hash,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
