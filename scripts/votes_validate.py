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
from votes_exceptions import find_exceptions
from votes_text import CanonicalText

_GRAMMAR = {
    "aye": r"(?:AYES?|Ayes?)",
    "no": r"(?:NOES?|NAYS?|Noes?|Nays?)",
    "abstain": r"(?:ABSTAIN\w*|ABSTENTION\w*|Abstain\w*|Abstention\w*)",
    "recused": r"(?:RECUS\w*|Recus\w*)",
    "absent": r"(?:EXCUSED\s+ABSENCE|ABSENT|Absent)",
}
_LABEL_AT = {c: re.compile(rf"{p}[ \t]*:" + (r"|AYES(?=[ \t]+(?:ALL|UNANIMOUS)\b)" if c == "aye" else ""))
             for c, p in _GRAMMAR.items()}
_ANY_LABEL_RE = re.compile(r"(?<![\w-])(?:(?:" + "|".join(_GRAMMAR.values()) + r"|Vote|VACANT)[ \t]*:"
                           r"|AYES(?=[ \t]+(?:ALL|UNANIMOUS)\b))")
_TITLES = re.compile(r"^(?:(?:Supe\w*visors?|Councilmembers?|Council\s+Members?|Councilwoman|Councilman|"
                     r"Mayor\s+Pro\s+Tem(?:pore)?|Vice\s+Mayor|Mayor|Vice\s+President|President|Pres\.|Vice\s+Chair|"
                     r"Chair|Board\s*Member|Director|Commissioner)(?:\s*/\s*Board\s*Member)?\s+)+", re.I)
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
        m = _LABEL_AT[cat].match(text, sp["start"])
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


def _own_names(value: str) -> set[str] | None:
    """The members a category value names, by this module's own reading (None = unreadable)."""
    value = re.sub(r"(?m)^\s*(?:\f|\d{1,3})\s*$", " ", value)
    names: set[str] = set()
    for chunk in re.split(r"[,;&]|\s+and\s+", value):
        chunk = chunk.strip().rstrip(".").strip()
        if not chunk or chunk.upper() in ("NONE", "ALL", "UNANIMOUS"):
            continue
        titled = bool(_TITLES.match(chunk))
        chunk = _TITLES.sub("", chunk).strip()
        tokens = chunk.split()
        if not tokens or not all(re.fullmatch(r"[A-Z][A-Za-z'\-]*\.?", t) for t in tokens):
            return None
        if not titled and len(tokens) > 1 and all(t.isupper() for t in tokens):
            names |= {_key(t) for t in tokens}
        else:
            names.add(_key(tokens[-1]))
    return names


def _check_membership(ct: CanonicalText, ev: dict) -> list[str]:
    """Every category label in the block, read independently, must name exactly the members the
    event lists for that category (an empty or deleted category included)."""
    text = ct.text
    block = ev.get("block")
    if not block:
        return []
    problems: list[str] = []
    found: dict[str, set[str]] = {}
    labels = list(_ANY_LABEL_RE.finditer(text, block["start"], block["end"]))
    for i, lab in enumerate(labels):
        cat = next((c for c, rx in _LABEL_AT.items() if rx.match(text, lab.start())), None)
        if cat is None:
            continue
        stop = labels[i + 1].start() if i + 1 < len(labels) else block["end"]
        out = _OUTCOME_RE.search(text, lab.end(), stop)
        names = _own_names(text[lab.end():out.start() if out else stop])
        if names is None:
            problems.append(f"{ev['event_id']}: the {cat} value is unreadable to the validator")
            continue
        found[cat] = found.get(cat, set()) | names
    for cat, names in ev["categories"].items():
        listed = {n["name"] for n in names if not n.get("inferred")}
        if listed != found.get(cat, set()):
            problems.append(f"{ev['event_id']}: {cat} lists {sorted(listed)} but the text names {sorted(found.get(cat, set()))}")
    return problems


_HEADING_LINE_RE = re.compile(r"^[ \t]*(?:\d{1,2}\.|[A-Z]\.(?:\d+\.?)?|C[AB]-\d+[a-z]?\.|[a-z]\.|[ivx]{1,4}\.)(?:[ \t]|$)",
                              re.M)


def _derived_exceptions(ct: CanonicalText, ev: dict, events: list[dict]) -> tuple[list[dict], list[str]]:
    """The event's prose exceptions, re-read from the source over its exception region, after
    checking that region: it ends at the vote block, and it starts at the start of the text, at
    another event's block or motion clause end, or at a heading line — and no exception phrase
    lies between the latest earlier boundary and that start without a heading between them."""
    text = ct.text
    eid = ev["event_id"]
    reg, block = ev.get("exception_region"), ev.get("block")
    if not reg or not block:
        return [], ([] if not block else [f"{eid}: no exception region"])
    problems: list[str] = []
    if reg["end"] != block["end"]:
        problems.append(f"{eid}: the exception region does not end at the vote block")
    ends = {0} | {c["end"] for e in events if e is not ev
                  for c in ([e.get("block")] + ([e["motion"]["span"]] if e.get("motion") else [])
                            + list(e.get("consumed", []))) if c}
    headings = {m.start() for m in _HEADING_LINE_RE.finditer(text)}
    if reg["start"] not in ends | headings:
        problems.append(f"{eid}: the exception region does not start at a boundary")
    prior = max([b for b in ends | headings if b <= reg["start"]], default=0)
    for x in find_exceptions(text, prior, reg["start"]):
        if not any(x["end"] <= h <= reg["start"] for h in headings):
            problems.append(f"{eid}: an exception before the region start is left out")
            break
    skip = [(c["start"], c["end"]) for c in (ev.get("category_spans") or {}).values()]
    found = find_exceptions(text, reg["start"], reg["end"], skip)
    derived = [{"name": x["name"], "kind": x["kind"], "span": ct.locate(x["start"], x["end"])} for x in found]
    if sorted((x["name"], x["kind"]) for x in derived) != sorted((x["name"], x["kind"])
                                                                 for x in ev.get("item_exceptions", [])):
        problems.append(f"{eid}: its prose exceptions differ from the source's")
    return derived, problems


def _pre_attendance(events: list[dict], derived: dict[str, list[dict]]) -> list[dict]:
    """The events as the attendance stage received them: an expanded event back to
    needs_attendance with its inferred ayes removed; everything else as decided."""
    out = []
    for ev in events:
        e = copy.deepcopy(ev)
        e.pop("attendance", None)
        # what attendance must not read as transitions: the vote block and the motion clause only
        e["consumed"] = [c for c in ([e.get("block")] + ([e["motion"]["span"]] if e.get("motion") else [])) if c]
        if e["event_id"] in derived:
            e["item_exceptions"] = derived[e["event_id"]]
        if e["status"] == "expanded":
            e["status"] = "needs_attendance"
            e["categories"]["aye"] = [n for n in e["categories"]["aye"] if not n.get("inferred")]
            e["hold_reasons"] = []
        out.append(e)
    return out


def validate_document(ct: CanonicalText, body: str, events: list[dict]) -> list[str]:
    problems: list[str] = []
    accepted = [e for e in events if e["status"] in ("named", "expanded")]
    derived: dict[str, list[dict]] = {}
    for ev in accepted:
        problems += _check_categories(ct, ev)
        problems += _check_membership(ct, ev)
        derived[ev["event_id"]], exc_problems = _derived_exceptions(ct, ev, events)
        problems += exc_problems
    expanded = [e for e in accepted if e["status"] == "expanded"]
    if not expanded:
        return problems
    rerun, _ = resolve(ct, body=body, events=_pre_attendance(events, derived))
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
