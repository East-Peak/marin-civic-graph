#!/usr/bin/env python3
"""Votes Part A, increment e: the reconciliation table between existing Decision nodes and the new
vote events, both ways.

A Decision pairs with events of the same meeting whose motion wording matches (equal, or one a
prefix of the other — the old Board parser cut the text at its first period); several candidates
are told apart by mover and seconder. A pairing is accepted only when it is one-to-one both ways:

  matched      one Decision ↔ one event, and every field the old pipeline recorded agrees
  conflicting  one ↔ one, with the differing fields listed
  ambiguous    several candidates either way; every Decision involved, with the competing ids
  unmatched    no candidate; reason: the meeting's inventory gap, no event in the meeting, or
               the motion wording matches nothing
  new          (events) no candidate Decision; proposed id = the event's stable id

Never by the old positional `vote-<i>` index. Fields the old pipeline never recorded (the Board's
noes/recusals/absences, Novato's absences, abstentions everywhere) are not compared.
"""

from __future__ import annotations

import re

NOT_RECORDED = {"marin-county-bos": {"no", "recused", "absent", "abstain", "tally"},
                "novato-city-council": {"absent", "abstain"}}
_DECISION_FIELD = {"aye": "ayes", "no": "noes", "recused": "recused", "absent": "absent"}


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _text_match(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 15 and long_.startswith(short)


def _key(name: str | None) -> str | None:
    return name.upper().strip(" .,;") if name else None


def _decision_names(values: list) -> tuple[set[str], bool]:
    """Names in an old array; ("NONE", "NONE.") empty it; a merged "ALPHA BRAVO" is split (noted)."""
    out: set[str] = set()
    merged = False
    for v in values or []:
        v = (v or "").strip().rstrip(".").upper()
        if not v or v == "NONE":
            continue
        parts = v.split()
        merged = merged or len(parts) > 1
        out |= set(parts)
    return out, merged


def _event_names(ev: dict, cat: str) -> set[str]:
    return {n["name"] for n in ev["categories"].get(cat, [])}


def _has_all(ev: dict) -> bool:
    return any(s["token"] in ("ALL", "UNANIMOUS") for s in ev.get("sentinels", []))


def compare(dec: dict, ev: dict) -> tuple[dict, list[str]]:
    differences: dict[str, list] = {}
    notes: list[str] = []
    skip = NOT_RECORDED.get(dec.get("source_id"), set())
    for field in ("mover", "seconder"):
        d, e = _key(dec.get(field)), _key((ev.get("motion") or {}).get(field))
        if d and e and d != e:
            differences[field] = [d, e]
    d_out, e_out = dec.get("outcome"), ev.get("outcome")
    if d_out in ("carried", "failed") and e_out in ("carried", "failed") and d_out != e_out:
        differences["outcome"] = [d_out, e_out]
    if "tally" not in skip:
        d_t, e_t = dec.get("tally"), (ev.get("tally") or {}).get("printed")
        if d_t and e_t and d_t != e_t:
            differences["tally"] = [d_t, e_t]
    for cat, field in _DECISION_FIELD.items():
        if cat in skip:
            continue
        d_names, merged = _decision_names(dec.get(field))
        if merged:
            notes.append("decision_array_merged_names")
        e_names = _event_names(ev, cat)
        if cat == "aye" and d_names == {"ALL"}:
            if _has_all(ev):
                continue  # the same sentinel; an expanded set is its reading, not a difference
            differences["aye"] = [["ALL"], sorted(e_names)]
            continue
        if cat == "aye" and ev["status"] == "held" and not e_names and _has_all(ev):
            continue
        if d_names != e_names:
            differences[cat] = [sorted(d_names), sorted(e_names)]
    return differences, sorted(set(notes))


def reconcile(decisions: list[dict], events: list[dict], meeting_gaps: dict[str, str]) -> list[dict]:
    decisions = sorted(decisions, key=lambda d: d["id"])
    events = sorted(events, key=lambda e: e["event_id"])
    by_meeting: dict[str, list[dict]] = {}
    for ev in events:
        by_meeting.setdefault(ev["meeting_id"], []).append(ev)

    cands: dict[str, list[str]] = {}
    for d in decisions:
        same = [e for e in by_meeting.get(d["meeting_id"], [])
                if e.get("motion") and _text_match(d.get("motion_text"), e["motion"].get("text"))]
        if len(same) > 1:
            told = [e for e in same if _key(e["motion"].get("mover")) == _key(d.get("mover"))
                    and _key(e["motion"].get("seconder")) == _key(d.get("seconder"))]
            if told:
                same = told
        cands[d["id"]] = [e["event_id"] for e in same]
    claimed: dict[str, list[str]] = {}
    for did, eids in cands.items():
        for eid in eids:
            claimed.setdefault(eid, []).append(did)

    ev_by_id = {e["event_id"]: e for e in events}
    rows: list[dict] = []
    involved: set[str] = set()
    for d in decisions:
        eids = cands[d["id"]]
        row = {"kind": "decision", "decision_id": d["id"], "meeting_id": d["meeting_id"], "status": None,
               "event_id": None, "candidates": eids, "reason": None, "differences": {}, "notes": []}
        involved |= set(eids)
        if len(eids) == 1 and len(claimed[eids[0]]) == 1:
            diffs, notes = compare(d, ev_by_id[eids[0]])
            row.update(status="conflicting" if diffs else "matched", event_id=eids[0], differences=diffs,
                       notes=notes)
        elif eids:
            row.update(status="ambiguous", reason="several_candidates")
        else:
            gap = meeting_gaps.get(d["meeting_id"])
            reason = gap if gap else ("no_event_in_meeting" if not by_meeting.get(d["meeting_id"])
                                      else "text_mismatch")
            row.update(status="unmatched", reason=reason)
        rows.append(row)
    for ev in events:
        if ev["event_id"] not in involved:
            rows.append({"kind": "event", "event_id": ev["event_id"], "meeting_id": ev["meeting_id"],
                         "status": "new", "proposed_id": ev["event_id"], "event_status": ev["status"]})
    return rows


def check_reconciliation(decisions: list[dict], events: list[dict], rows: list[dict]) -> list[str]:
    problems: list[str] = []
    d_rows = [r for r in rows if r["kind"] == "decision"]
    ids = [r["decision_id"] for r in d_rows]
    want = {d["id"] for d in decisions}
    if set(ids) != want:
        problems.append(f"{len(want - set(ids))} decisions missing, {len(set(ids) - want)} unknown")
    if len(ids) != len(set(ids)):
        problems.append(f"{len(ids) - len(set(ids))} decisions listed twice")
    for r in d_rows:
        if r["status"] not in ("matched", "conflicting", "ambiguous", "unmatched"):
            problems.append(f"{r['decision_id']}: status {r['status']!r}")
    paired = [r["event_id"] for r in d_rows if r["status"] in ("matched", "conflicting")]
    if len(paired) != len(set(paired)):
        problems.append("an event paired with two decisions")
    new = [r["event_id"] for r in rows if r["kind"] == "event"]
    known = {e["event_id"] for e in events}
    if set(new) - known:
        problems.append("a new row for an unknown event")
    if set(new) & {e for r in d_rows for e in r["candidates"]}:
        problems.append("an event both new and a candidate")
    return problems
