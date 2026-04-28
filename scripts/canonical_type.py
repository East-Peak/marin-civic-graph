"""Python port of app/src/lib/canonical-type.ts. Single source of truth for
node-type resolution in the pipeline. MUST stay in sync with the TS version.
"""
from __future__ import annotations

ALL_TYPES = [
    "Person", "Organization", "Committee", "Seat", "SeatService",
    "Election", "Candidacy", "Meeting", "AgendaItem", "Decision",
    "Filing", "MoneyFlow", "Case", "Proceeding", "Project",
    "Program", "Agreement", "Amendment", "Record", "Place", "Issue",
]

ORGANIZATION_SUBTYPES = {
    "Government", "Nonprofit", "Business",
    "Political", "Court", "Department", "Commission",
}

TYPE_BY_ID_PREFIX = {
    "person-": "Person", "org-": "Organization", "committee-": "Committee",
    "seat-": "Seat", "seatservice-": "SeatService", "election-": "Election",
    "candidacy-": "Candidacy", "meeting-": "Meeting", "agendaitem-": "AgendaItem",
    "decision-": "Decision", "filing-": "Filing", "moneyflow-": "MoneyFlow",
    "case-": "Case", "proceeding-": "Proceeding", "project-": "Project",
    "program-": "Program", "agreement-": "Agreement", "amendment-": "Amendment",
    "record-": "Record", "place-": "Place", "issue-": "Issue",
    # Legacy (matches canonical-type.ts)
    "actor-": "Person", "inst-": "Organization", "eid-": "Filing",
}


def canonical_type(labels: list[str], node_id: str) -> str | None:
    """Resolve a node's canonical NodeType. Mirrors canonicalType() in TS."""
    for prefix, t in TYPE_BY_ID_PREFIX.items():
        if node_id.startswith(prefix):
            return t
    base = next((lbl for lbl in labels if lbl in ALL_TYPES), None)
    if base:
        return base
    if any(lbl in ORGANIZATION_SUBTYPES for lbl in labels):
        return "Organization"
    return None
