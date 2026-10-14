#!/usr/bin/env python3
"""Votes Part A: prose recusals and abstentions ("Supervisor X recused himself from this item",
"Councilmembers A and B announced that they would be recusing themselves").

A neutral module: the parser records an event's exceptions with it, and the validator re-derives
them from the source text with it, so an event's own list of exceptions is never trusted.
"""

from __future__ import annotations

import re

TITLE = (r"(?:Supe\w*visors?|Councilmember|Council\s+Member|Councilwoman|Councilman|"
         r"(?:Mayor\s+Pro\s+Tem(?:pore)?|Vice\s+Mayor|Mayor)(?:\s*/\s*Board\s*Member)?|Board\s*Member|"
         r"Vice\s+President|President|Pres\.|Vice\s+Chair|Chair|Director|Commissioner)")
_REF = rf"(?-i:(?i:{TITLE})\s+(?:[A-Z][\w']*\s+)?[A-Z][\w'\-]*)"
EXCEPTION_RE = re.compile(
    rf"(?P<group>{_REF}(?:\s*,?\s*(?:and\s+)?{_REF})*)\s+"
    rf"(?:(?:announced|stated|indicated|advised)\s+(?:that\s+)?(?:she|he|they)\s+)?"
    rf"(?:(?:would|will)\s+(?:also\s+)?be\s+|had\s+|(?:needed|had|would\s+have|will\s+have)\s+to\s+)?"
    rf"(?P<v>recused|recusing|recuse|abstained|abstaining|abstain|did\s+not\s+participate)"
    rf"(?:\s+(?:himself|herself|themselves|themself))?", re.I)
_NAME_RE = re.compile(rf"(?-i:(?i:{TITLE})\s+(?:[A-Z][\w']*\s+)?(?P<n>[A-Z][\w'\-]*))")


def find_exceptions(text: str, start: int, end: int, skip: list[tuple[int, int]] = ()) -> list[dict]:
    """[{name, kind ('recused' | 'abstain'), start, end}] in text[start:end], outside `skip`."""
    out: list[dict] = []
    for m in EXCEPTION_RE.finditer(text, start, end):
        if any(s <= m.start() < e for s, e in skip):
            continue
        kind = "abstain" if m.group("v").lower().startswith("abstain") else "recused"
        for nm in _NAME_RE.finditer(m.group("group")):
            out.append({"name": nm.group("n").upper(), "kind": kind, "start": m.start(), "end": m.end()})
    return out
