#!/usr/bin/env python3
"""Votes Part A: combined-evidence validation of every accepted vote event (goal Design 4).

For each `named` or `expanded` event, nothing the event says about its own evidence is trusted:

1. Category regions are re-derived from the raw text with this module's own label grammar: each
   cited category span must begin at a label of that category and end before the next label, and
   no two category spans may overlap — so swapping two categories (names, spans or both) fails.
2. Every explicitly named member's span must lie inside their own category's span, read exactly
   their written name, and carry the key that name gives.
3. Inferred names exist only in an expanded event's aye category, which must hold the ALL /
   UNANIMOUS sentinel; the whole attendance trace is re-run from the document's start and must
   derive exactly the same ayes from a certain state, citing exactly the same evidence spans.

Deliberately imports neither the parser nor the candidate scanner.
"""

from __future__ import annotations

import copy
import re

from votes_attendance import resolve
from votes_text import CanonicalText

_GRAMMAR = {
    "aye": r"(?:AYES?|Ayes?)",
    "no": r"(?:NOES?|NAYS?|Noes?|Nays?)",
    "abstain": r"(?:ABSTAIN\w*|ABSTENTION\w*|Abstain\w*|Abstention\w*)",
    "recused": r"(?:RECUS\w*|Recus\w*)",
    "absent": r"(?:EXCUSED\s+ABSENCE|ABSENT|Absent)",
}
_ANY_LABEL_RE = re.compile(r"(?<![\w-])(?:" + "|".join(_GRAMMAR.values()) + r"|Vote)[ \t]*:")
_OUTCOME_RE = re.compile(r"\b(?:The\s+)?[Mm]otion\s+(?:carried|failed|passed)\b|\bMOTION\s+(?:CARRIED|FAILED)\b")


def _key(raw: str) -> str:
    return raw.upper().strip(".,;:")


def _check_categories(ct: CanonicalText, ev: dict) -> list[str]:
    text = ct.text
    eid = ev["event_id"]
    problems: list[str] = []
    spans = ev.get("category_spans") or {}
    block = ev.get("block")
    cats_used = [c for c, names in ev["categories"].items()
                 if any(not n.get("inferred") for n in names)]
    cats_used += [s["category"] for s in ev.get("sentinels", [])]
    for cat in sorted(set(cats_used)):
        sp = spans.get(cat)
        if not sp:
            problems.append(f"{eid}: {cat} has names or a sentinel but no category span")
            continue
        m = re.compile(_GRAMMAR[cat] + r"[ \t]*:").match(text, sp["start"])
        if not m:
            problems.append(f"{eid}: the {cat} span does not begin at a {cat} label")
            continue
        nxt = _ANY_LABEL_RE.search(text, m.end(), block["end"] if block else len(text))
        out = _OUTCOME_RE.search(text, m.end(), block["end"] if block else len(text))
        limit = min(x.start() for x in (nxt, out) if x) if (nxt or out) else (block["end"] if block else len(text))
        if sp["end"] > limit:
            problems.append(f"{eid}: the {cat} span runs past the end of its region")
        if block and not (block["start"] <= sp["start"] and sp["end"] <= block["end"]):
            problems.append(f"{eid}: the {cat} span lies outside the vote block")
    used = sorted((spans[c]["start"], spans[c]["end"], c) for c in set(cats_used) if c in spans)
    for (s1, e1, c1), (s2, e2, c2) in zip(used, used[1:]):
        if s2 < e1:
            problems.append(f"{eid}: the {c1} and {c2} spans overlap")
    for cat, names in ev["categories"].items():
        for n in names:
            if n.get("inferred"):
                if ev["status"] != "expanded" or cat != "aye":
                    problems.append(f"{eid}: inferred {n['name']} outside an expanded event's ayes")
                continue
            sp, csp = n.get("span"), spans.get(cat)
            if not sp or not csp:
                problems.append(f"{eid}: {n.get('name')} in {cat} without a span")
                continue
            if not (csp["start"] <= sp["start"] and sp["end"] <= csp["end"]):
                problems.append(f"{eid}: {n['name']} is not inside the {cat} span")
            written = text[sp["start"]:sp["end"]]
            if written != n.get("raw") or _key(written) != n["name"]:
                problems.append(f"{eid}: {n['name']} does not read {written!r} at its span")
    return problems


def _pre_attendance(events: list[dict]) -> list[dict]:
    """The events as the attendance stage received them: an expanded event back to
    needs_attendance with its inferred ayes removed; everything else as decided."""
    out = []
    for ev in events:
        e = copy.deepcopy(ev)
        e.pop("attendance", None)
        if e["status"] == "expanded":
            e["status"] = "needs_attendance"
            e["categories"]["aye"] = [n for n in e["categories"]["aye"] if not n.get("inferred")]
            e["hold_reasons"] = []
        out.append(e)
    return out


def validate_document(ct: CanonicalText, body: str, events: list[dict]) -> list[str]:
    problems: list[str] = []
    accepted = [e for e in events if e["status"] in ("named", "expanded")]
    for ev in accepted:
        problems += _check_categories(ct, ev)
    expanded = [e for e in accepted if e["status"] == "expanded"]
    if not expanded:
        return problems
    rerun, _ = resolve(ct, body=body, events=_pre_attendance(events))
    by_id = {e["event_id"]: e for e in rerun}
    for ev in expanded:
        eid = ev["event_id"]
        sentinels = [s for s in ev.get("sentinels", []) if s["token"] in ("ALL", "UNANIMOUS")]
        aye_span = (ev.get("category_spans") or {}).get("aye")
        if not sentinels or not aye_span or not any(
                aye_span["start"] <= s["span"]["start"] and s["span"]["end"] <= aye_span["end"]
                and ct.text[s["span"]["start"]:s["span"]["end"]].upper() == s["token"] for s in sentinels):
            problems.append(f"{eid}: no ALL/UNANIMOUS sentinel inside the aye region")
        again = by_id.get(eid)
        if again is None or again["status"] != "expanded":
            problems.append(f"{eid}: the attendance trace does not expand this event")
            continue
        if sorted(n["name"] for n in again["categories"]["aye"]) != sorted(n["name"] for n in ev["categories"]["aye"]):
            problems.append(f"{eid}: the attendance trace derives different ayes")
        cited = [(s["start"], s["end"]) for s in ev.get("attendance", {}).get("evidence", [])]
        derived = [(s["start"], s["end"]) for s in again["attendance"]["evidence"]]
        if cited != derived:
            problems.append(f"{eid}: the cited attendance evidence differs from the trace's")
    return problems
