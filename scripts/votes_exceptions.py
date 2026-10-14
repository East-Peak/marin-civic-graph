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
_PLURAL = (r"(?-i:(?i:Supervisors|Councilmembers|Council\s+Members)\s+[A-Z][\w'\-]*(?:\s*,\s*[A-Z][\w'\-]*)*"
           r"\s*,?\s+and\s+[A-Z][\w'\-]*)")
EXCEPTION_RE = re.compile(
    rf"(?P<group>{_PLURAL}|{_REF}(?:\s*,?\s*(?:and\s+)?{_REF})*)\s+(?:(?:both|also)\s+)?"
    rf"(?:(?:announced|stated|indicated|advised|noted)\s+(?:that\s+)?(?:she|he|they)\s+)?"
    rf"(?:(?:was|were|is|are)\s+|(?:would|will)\s+(?:also\s+)?(?:be\s+|need\s+(?:to\s+)?)?|had\s+|"
    rf"(?:needed|had|would\s+have|will\s+have)\s+to\s+)?"
    rf"(?P<v>recused|recusing|recuse|abstained|abstaining|abstain|did\s+not\s+participate)"
    rf"(?:\s+(?:himself|herself|themselves|themself))?"
    rf"|(?P<noun>abstention|recusal)\s+of\s+(?P<group2>{_REF})"
    rf"|(?P<group3>{_REF})'s\s+(?P<noun3>recusal|abstention)", re.I)
_NAME_RE = re.compile(rf"(?-i:(?i:{TITLE})\s+(?:[A-Z][\w']*\s+)?(?P<n>[A-Z][\w'\-]*))")
_PLURAL_HEAD_RE = re.compile(r"(?i)^(?:Supervisors|Councilmembers|Council\s+Members)\s+")
_EXCEPTION_WORD_RE = re.compile(r"\brecus\w*|\babstain\w*|\babstention\w*|\bdid\s+not\s+participate\b", re.I)


def find_exceptions(text: str, start: int, end: int, skip: list[tuple[int, int]] = ()) -> list[dict]:
    """[{name, kind ('recused' | 'abstain'), start, end}] in text[start:end], outside `skip`."""
    out: list[dict] = []
    for m in EXCEPTION_RE.finditer(text, start, end):
        if any(s <= m.start() < e for s, e in skip):
            continue
        verb = (m.group("v") or m.group("noun") or m.group("noun3")).lower()
        kind = "abstain" if verb.startswith(("abstain", "abstention")) else "recused"
        group = m.group("group") or m.group("group2") or m.group("group3")
        head = _PLURAL_HEAD_RE.match(group)
        names = ([n for n in re.findall(r"[A-Z][\w'\-]*", group[head.end():])] if head
                 else [nm.group("n") for nm in _NAME_RE.finditer(group)])
        for n in names:
            out.append({"name": n.upper(), "kind": kind, "start": m.start(), "end": m.end()})
    return out


def unread_exception_words(text: str, start: int, end: int, read: list[tuple[int, int]],
                           skip: list[tuple[int, int]] = ()) -> list[int]:
    """Positions of recusal/abstention wording in text[start:end] that no exception read: the
    item says someone stood aside, but not in a form this module can attribute."""
    out = []
    for m in _EXCEPTION_WORD_RE.finditer(text, start, end):
        if any(s <= m.start() < e for s, e in list(read) + list(skip)):
            continue
        out.append(m.start())
    return out
