#!/usr/bin/env python3
"""Votes Part A, increment f: roster evidence for Stuart's review. Nothing is written to the graph.

Part B resolves voters to Person nodes on reviewed rosters, so Part A drafts every member term of
each body from 2019 to today, each with cited evidence:

- term evidence in the minutes we already hold (canvass resolutions, reorganizations, oaths,
  resignations, vacancy appointments) — `term_evidence`;
- observed service from roll calls (first and last meeting each member sat, name forms, titles) —
  supporting evidence only, never a term boundary — `observed_service`;
- official public pages captured into staging (at most 40 per body).

The draft terms themselves are authored from that evidence (a JSON file per body); `verify_drafts`
proves every quoted excerpt appears in its cited source and that every start and end has support.
Existing SeatService terms are validated against the drafts, a per-seat coverage matrix lists the
gaps, and the review batch uses the goal-4a short answers: `batch <id>` then `<item> <option>`.
"""

from __future__ import annotations

import re
from datetime import date

OPTIONS = ("confirm", "correct", "reject", "defer")

_EVIDENCE = [
    ("canvass", re.compile(r"canvass\w*\s+of\s+(?:the\s+)?election|declar\w*\s+the\s+results?|results?\s+of\s+the\s+"
                           r"canvass", re.I)),
    ("reorganization", re.compile(r"\breorganiz\w*", re.I)),
    ("resignation", re.compile(r"\bresign(?:ed|ing|ation)?\b[^.]{0,80}(?:council|board|seat|district)", re.I)),
    ("oath", re.compile(r"oath\s+of\s+office|\bsworn\s+in\b|swearing[\s-]in", re.I)),
    ("vacancy", re.compile(r"fill\s+(?:the|a)\s+vacancy|vacancy\s+(?:on|in)\s+(?:the\s+)?(?:city\s+council|board|"
                           r"district)", re.I)),
]
_TITLE = (r"(?:Supe\w*visors?|Councilmember|Council\s+Member|Councilwoman|Councilman|Mayor\s+Pro\s+Tem(?:pore)?|"
          r"Vice\s+Mayor|Mayor|Vice\s+President|President)")
_NOT_NAMES = {"PRO", "TEM", "TEMPORE", "ABSENT", "PRESENT", "AND", "VIA", "TELECONFERENCE"}
_FULL_NAME_RE = re.compile(rf"(?-i:(?P<t>(?i:{_TITLE}))\s+(?:(?P<g>[A-Z][\w'\-]*)\s+)?(?P<s>[A-Z][\w'\-]*))")


class RosterError(Exception):
    pass


def term_evidence(ct) -> list[dict]:
    """Excerpts in a minutes document that bear on who held a seat when (one per sentence)."""
    text = ct.text
    found: list[dict] = []
    seen_sentences: set[tuple[int, int]] = set()
    for kind, rx in _EVIDENCE:
        for m in rx.finditer(text):
            s = max(text.rfind(". ", 0, m.start()), text.rfind(".\n", 0, m.start()),
                    text.rfind("\n\n", 0, m.start()))
            s = 0 if s < 0 else s + 2
            ends = [i for i in (text.find(". ", m.end()), text.find(".\n", m.end())) if i != -1]
            e = min(ends) + 1 if ends else len(text)
            if (s, e) in seen_sentences:
                continue
            seen_sentences.add((s, e))
            found.append({"kind": kind, "span": ct.locate(s, e),
                          "excerpt": re.sub(r"\s+", " ", text[s:e]).strip()})
    found.sort(key=lambda x: x["span"]["start"])
    return found


def observed_service(rolls: list[tuple[str, str]]) -> dict[str, dict]:
    """rolls: (meeting date, roll-call text). Per member surname key: first/last date seen, number of
    meetings, the full-name forms and titles the minutes used."""
    out: dict[str, dict] = {}
    for day, text in sorted(rolls):
        text = re.sub(r"-\s*\n\s*", "-", text)  # a surname broken at its hyphen across lines
        seen_here: set[str] = set()
        for m in _FULL_NAME_RE.finditer(text):
            surname, given = m.group("s"), m.group("g")
            if surname.upper() in _NOT_NAMES:  # "Supervisor Alder Absent": the name is the word before
                if not given or given.upper() in _NOT_NAMES:
                    continue
                surname, given = given, None
            if given and given.upper() in _NOT_NAMES:
                given = None
            key = surname.upper()
            rec = out.setdefault(key, {"first_seen": day, "last_seen": day, "meetings": 0, "names": [],
                                       "titles": []})
            rec["last_seen"] = max(rec["last_seen"], day)
            rec["first_seen"] = min(rec["first_seen"], day)
            name = f"{given} {surname}" if given else None
            title = re.sub(r"\s+", " ", m.group("t")).title().replace("Pro Tem", "Pro Tem")
            title = {"Councilmember": "Councilmember", "Mayor": "Mayor"}.get(title, title)
            if name and name not in rec["names"]:
                rec["names"].append(name)
            if title not in rec["titles"]:
                rec["titles"].append(title)
            if key not in seen_here:
                rec["meetings"] += 1
                seen_here.add(key)
    for rec in out.values():
        rec["names"].sort()
        rec["titles"].sort()
    return out


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def verify_drafts(drafts: dict, sources: dict, *, max_web_sources: int = 40) -> list[str]:
    """Problems with a body's draft terms (empty = every quote is in its cited source, and every
    start, end and seat has support)."""
    web = [k for k in sources if k.startswith("web:")]
    if len(web) > max_web_sources:
        raise RosterError(f"{len(web)} web sources for one body; the cap is {max_web_sources}")
    problems: list[str] = []
    for t in drafts["terms"]:
        tid = t["draft_id"]
        supported: set[str] = set()
        for ev in t.get("evidence", []):
            src = sources.get(ev["source"])
            if src is None:
                problems.append(f"{tid}: unknown source {ev['source']}")
                continue
            if _ws(ev["quote"]) not in _ws(src["text"]):
                problems.append(f"{tid}: quote not found in {ev['source']}")
                continue
            supported |= set(ev.get("supports", []))
        needed = {"start"} | ({"end"} if t.get("end") else set())
        if "unstated" not in (t.get("seat") or ""):
            needed.add("seat")
        for field in sorted(needed - supported):
            problems.append(f"{tid}: no cited evidence for its {field}")
    return problems


def validate_seatservices(drafts: dict, services: list[dict]) -> list[dict]:
    """Each existing SeatService against the drafted term for the same member and seat."""
    rows = []
    for s in sorted(services, key=lambda x: x["id"]):
        cands = [t for t in drafts["terms"] if t.get("key") == s["key"] and t.get("seat") == s["seat"]]
        overlapping = [t for t in cands if (t.get("start") or "") <= (s.get("ended_at") or "9999")
                       and (t.get("end") or "9999") >= (s.get("started_at") or "")]
        best = (overlapping or cands or [None])[0]
        if best is None:
            rows.append({"seatservice_id": s["id"], "verdict": "no_evidence", "draft_id": None, "differences": {}})
            continue
        diffs = {}
        if s.get("started_at") != best.get("start"):
            diffs["started_at"] = [s.get("started_at"), best.get("start")]
        if (s.get("ended_at") or None) != (best.get("end") or None):
            diffs["ended_at"] = [s.get("ended_at"), best.get("end")]
        rows.append({"seatservice_id": s["id"], "verdict": "disagree" if diffs else "agree",
                     "draft_id": best["draft_id"], "differences": diffs})
    return rows


def coverage(drafts: dict, seats: list[str], start: str, end: str) -> dict[str, dict]:
    """Per seat: the drafted terms in the window, and the gaps no term covers."""
    out = {}
    for seat in seats:
        terms = sorted(([t["start"], t.get("end") or end] for t in drafts["terms"] if t.get("seat") == seat),
                       key=lambda x: x[0])
        gaps, cursor = [], start
        for s, e in terms:
            if s > cursor:
                gaps.append([cursor, s])
            cursor = max(cursor, e)
        if cursor < end:
            gaps.append([cursor, end])
        out[seat] = {"terms": terms, "gaps": gaps}
    return out


def render_batch(batch_id: str, drafts_by_body: dict, validations_by_body: dict, coverage_by_body: dict, *,
                 sources: dict, as_of: str | None = None) -> tuple[str, list[dict]]:
    """(markdown, items) for the review batch: one item per drafted term, with its evidence; the
    SeatService validations and the coverage gaps follow for context."""
    as_of = as_of or date.today().isoformat()
    items: list[dict] = []
    lines = [f"# Roster review — {batch_id}, as of {as_of}", "",
             "Each item is a drafted term of office for the vote ledger's Part B (voters → Person nodes). "
             "Nothing is written to the graph from this file.", "",
             "To answer: start a file with the line `batch " + batch_id + "`, then one line per item you decide: "
             "`<item> confirm`, `<item> reject`, `<item> defer`, or `<item> correct: <what is right>`. "
             "Skipping an item is fine.", ""]
    n = 0
    for body in sorted(drafts_by_body):
        lines += [f"## {body}", ""]
        for t in drafts_by_body[body]["terms"]:
            n += 1
            item = str(n)
            items.append({"item": item, "body": body, "draft_id": t["draft_id"], "options": list(OPTIONS)})
            lines.append(f"### {item}. {t['member']} — {t['seat']}, {t['start']} → {t.get('end') or 'present'} "
                         f"({t['basis']}, {t.get('confidence', 'unrated')})")
            if t.get("notes"):
                lines.append(f"_{t['notes']}_")
            for ev in t.get("evidence", []):
                src = sources.get(ev["source"], {})
                where = src.get("url") or ev["source"]
                lines.append(f"- {', '.join(ev.get('supports', []))}: “{_ws(ev['quote'])}” — {where}")
            lines += ["", f"Answer: `{item} confirm` · `{item} correct: …` · `{item} reject` · `{item} defer`", ""]
        rows = validations_by_body.get(body, [])
        if rows:
            lines += ["### Existing SeatService terms checked against the drafts", ""]
            for r in rows:
                diff = "; ".join(f"{k}: graph {v[0]} vs draft {v[1]}" for k, v in sorted(r["differences"].items()))
                lines.append(f"- `{r['seatservice_id']}` — {r['verdict']}" + (f" ({diff})" if diff else ""))
            lines.append("")
        cov = coverage_by_body.get(body, {})
        if cov:
            lines += ["### Coverage 2019 → today", ""]
            for seat, c in sorted(cov.items()):
                gaps = ", ".join(f"{a} → {b}" for a, b in c["gaps"]) or "none"
                lines.append(f"- {seat}: gaps {gaps}")
            lines.append("")
    return "\n".join(lines) + "\n", items


def parse_answers(text: str, batch_id: str, items: list[dict]) -> list[dict]:
    """The answer file's decisions; any malformed, unknown or repeated line rejects the whole file."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines or lines[0] != f"batch {batch_id}":
        raise RosterError(f"the first line must be `batch {batch_id}`")
    known = {i["item"] for i in items}
    out, seen = [], set()
    for ln in lines[1:]:
        m = re.fullmatch(r"(\S+)\s+(confirm|reject|defer)|(\S+)\s+correct:\s*(\S.*)", ln)
        if not m:
            raise RosterError(f"line {ln[:20]!r}… is not `<item> <option>` (correct needs `: <what is right>`)")
        item = m.group(1) or m.group(3)
        if item not in known:
            raise RosterError(f"item {item} is not in batch {batch_id}")
        if item in seen:
            raise RosterError(f"item {item} is answered twice")
        seen.add(item)
        out.append({"item": item, "option": m.group(2) or "correct", "note": m.group(4)})
    return out
