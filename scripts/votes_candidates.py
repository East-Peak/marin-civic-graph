#!/usr/bin/env python3
"""Votes Part A, increment c: the independent candidate scan and its dispositions.

The scan is deliberately broad and knows nothing of the parser: every vote label, motion phrase,
outcome phrase and vote-ish word in a document is a candidate. Each candidate then gets exactly one
disposition:

  named / expanded / held  — it lies in text an event consumed; the event's class
  excluded                 — affirmative evidence that it is not a vote of this body (an attendance
                             statement, a vote requirement, an election, another body's or an
                             earlier vote, prospective agenda wording), with that evidence
  held                     — anything else: an unconsumed label, or a vote word nothing accounts for

so whatever the parser missed is visible as a held orphan rather than silently gone.
"""

from __future__ import annotations

import re

from votes_text import CanonicalText

CLASSES = ("named", "expanded", "held", "excluded")

LABEL_KINDS = {"aye_label", "no_label", "absent_label", "abstain_label", "recuse_label", "vote_label", "ms",
               "moved_by", "seconded_by", "motion_outcome", "no_second"}
NARRATIVE_KINDS = {"vote_word", "roll_call", "unanimous", "aye_word", "no_word", "absent_word", "abstain_word",
                   "recuse_word"}
_VOTEISH = ("vote_word", "unanimous", "roll_call", "aye_word", "no_word")

_COLON_AFTER = re.compile(r"[ \t]*:")

_SCANS: list[tuple[str, re.Pattern]] = [
    ("ms", re.compile(r"\bM/[sS]\b")),
    ("vote_label", re.compile(r"\bvotes?(?=[ \t]*:)", re.I)),
    ("motion_outcome", re.compile(r"\bmotion\s+(?:was\s+)?(?:carried|failed|passed)\b", re.I)),
    ("aye", re.compile(r"\bayes?\b", re.I)),
    ("no", re.compile(r"\b(?:noes?|nays?)\b", re.I)),
    ("absent", re.compile(r"\bexcused\s+absence\b|\babsent\b", re.I)),
    ("abstain", re.compile(r"\babstain\w*|\babstention\w*", re.I)),
    ("recuse", re.compile(r"\brecus\w*", re.I)),
    ("moved_by", re.compile(r"\bmoved\s+by\b", re.I)),
    ("seconded_by", re.compile(r"\bseconded\s+by\b", re.I)),
    ("vote_word", re.compile(r"\bvot(?:e|ed|es|ing)\b(?![ \t]*:)", re.I)),
    ("roll_call", re.compile(r"\broll\s+call\b", re.I)),
    ("unanimous", re.compile(r"\bunanimous(?:ly)?\b", re.I)),
    ("no_second", re.compile(r"\bno\s+second\b|\black\s+of\s+a\s+second\b", re.I)),
]


def scan(ct: CanonicalText, doc_sha256: str = "0" * 64) -> list[dict]:
    text = ct.text
    found: dict[tuple[int, str], dict] = {}
    for kind, rx in _SCANS:
        for m in rx.finditer(text):
            k = kind
            if kind in ("absent", "abstain", "recuse"):
                k = f"{kind}_label" if _COLON_AFTER.match(text, m.end()) else f"{kind}_word"
            elif kind in ("aye", "no"):
                # a label in any case: a colon, the all-caps form, or a sentinel right after it
                label = (_COLON_AFTER.match(text, m.end()) or m.group(0).isupper()
                         or re.match(r"[ \t]+(?:ALL|NONE|UNANIMOUS)\b", text[m.end():]))
                k = f"{kind}_label" if label else f"{kind}_word"
            found[(m.start(), k)] = {"cand_id": f"cand-{doc_sha256[:8]}-{m.start()}-{k}", "kind": k,
                                     "text": m.group(0), "span": ct.locate(m.start(), m.end())}
    return [found[key] for key in sorted(found)]


# ---------------------------------------------------------------------------------------------
# non-vote contexts (a closed list; each is affirmative evidence, tested)

_VOTE_REQUIREMENT_RE = re.compile(
    r"\b(?:\d+/\d+(?:ths)?|two-thirds|three-fourths|four-fifths|majority|super-?majority)\s+vote\b"
    r"|\baffirmative\s+votes?\b"
    r"|\brequir\w*\b[^.]{0,60}?\bvote\b|\bvote\s+of\s+(?:available|the)\s+(?:members|board|council)\b", re.I)
_ELECTION_RE = re.compile(
    r"\b(?:voters?|ballots?|elections?|electorate|polling|precincts?|registrar|vote\s+by\s+mail"
    r"|vote\s+centers?|voting\s+(?:centers?|rights|age|locations?|machines?|system))\b", re.I)
_OTHER_BODY_RE = re.compile(
    r"\b(?:Planning\s+Commission|Commission|Committee|Board\s+of\s+Directors|Authority|Commissioners"
    r"|Court|Legislature|Senate|Assembly|voters|residents|Congress|City\s+of\s+\w+)\b"
    r"(?:\s+\w+){0,2}?\s+vot(?:ed|es|ing)\b", re.I)
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_EARLIER_RE = re.compile(rf"\b(?:previously|prior\s+to|earlier|last\s+(?:year|month|week)|in\s+(?:19|20)\d\d"
                         rf"|on\s+{_MONTH}\s+\d{{1,2}})\b", re.I)
_PROSPECTIVE_RE = re.compile(r"\b(?:possibly|may|will|to|could|would|shall|might)\s+(?:take\s+(?:a\s+)?)?vote\b"
                             r"|\bpossible\s+vote\b|\bfor\s+a\s+vote\b|\bcast\s+(?:the\s+)?(?:[\w']+\s+)?vote\b"
                             r"|\b(?:discuss|consider)\s+and\s+vote\b", re.I)
_VOTING_ROLE_RE = re.compile(r"\bvoting\s+(?:representatives?|delegates?|members?|alternates?)\b", re.I)
_NON_MEMBER_RE = re.compile(r"\b(?:Commissioners?|Applicants?|Directors?|Mr\.|Ms\.|Mrs\.|Dr\.|staff)\s+"
                            r"(?:[A-Z][\w'\-]*\s+){0,2}(?:(?:was|were|is)\s+)?(?:absent|present)\b")
_HEADING_RE = re.compile(r"^[ \t]*(?:\d{1,2}\.|[A-Z]\.(?:\d+\.?)?|C[AB]-\d+[a-z]?\.)(?:[ \t]|$)", re.M)


def _roll_call_heading(text: str, span: dict) -> bool:
    """'Roll Call' as a heading: the line is just the heading (title case, or an all-caps agenda
    heading), or the words open an attendance list ('Roll Call Present: …')."""
    ls = text.rfind("\n", 0, span["start"]) + 1
    le = text.find("\n", span["end"])
    line = text[ls:(len(text) if le == -1 else le)].strip()
    if line == "Roll Call" or (line.upper() == line and re.search(r"ROLL\s+CALL\s*$", line)):
        return True
    return bool(re.match(r"\s*Present\s*:", text[span["end"]:span["end"] + 20]))


def _sentence(text: str, pos: int) -> tuple[int, int]:
    """The candidate's own sentence: bounded by sentence ends, blank lines, and line breaks before
    an unindented line (in HTML-derived text every line is its own paragraph)."""
    lefts = [text.rfind(". ", 0, pos), text.rfind(".\n", 0, pos), text.rfind("\n\n", 0, pos)]
    lefts += [m.start() for m in re.finditer(r"\n(?=\S)", text[:pos])][-1:]
    left = max(lefts)
    left = left + 1 if left >= 0 else 0
    rights = [i for i in (text.find(". ", pos), text.find(".\n", pos), text.find("\n\n", pos)) if i != -1]
    nl = re.search(r"\n(?=\S)", text[pos:])
    if nl:
        rights.append(pos + nl.start() - 1)
    right = min(rights) + 1 if rights else len(text)
    return left, right


_COMPLETED_RE = re.compile(r"\b(?:voted|passed|carried|adopted|approved|unanimously)\b", re.I)


def _overlaps(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def _item_start(text: str, pos: int) -> int:
    starts = [m.start() for m in _HEADING_RE.finditer(text, 0, pos)]
    return starts[-1] if starts else 0


def dispose(ct: CanonicalText, candidates: list[dict], events: list[dict], *, attendance_spans: list[dict],
            transcript: bool = False) -> list[dict]:
    text = ct.text
    consumed = [(c, e) for e in events for c in e["consumed"]]
    out: list[dict] = []
    for cand in candidates:
        sp = cand["span"]
        d = {"cand_id": cand["cand_id"], "kind": cand["kind"], "class": None, "event_id": None,
             "reason": None, "evidence": None}
        if transcript:
            d.update({"class": "held", "reason": "transcript_document"})
            out.append(d)
            continue
        owners = sorted({e["event_id"] for c, e in consumed if _overlaps(sp, c)})
        if len(owners) == 1:
            ev = next(e for e in events if e["event_id"] == owners[0])
            if ev["status"] not in ("named", "expanded", "held"):
                raise ValueError(f"{ev['event_id']}: unresolved status {ev['status']!r}")
            d.update({"class": ev["status"], "event_id": ev["event_id"], "reason": "consumed"})
            out.append(d)
            continue
        if len(owners) > 1:
            classes = {next(e for e in events if e["event_id"] == o)["status"] for o in owners}
            if len(classes) == 1:  # e.g. group-scoped votes sharing one motion clause
                d.update({"class": classes.pop(), "event_id": owners[0], "reason": "consumed", "evidence": owners})
            else:
                d.update({"class": "held", "reason": "consumed_by_several_events", "evidence": owners})
            out.append(d)
            continue
        att = next((a for a in attendance_spans if a["start"] <= sp["start"] < a["end"]), None)
        if att is not None and cand["kind"] in ("absent_label", "absent_word", "roll_call", "abstain_word",
                                                 "recuse_word", "vote_word", "unanimous"):
            d.update({"class": "excluded", "reason": "roll_call_attendance", "evidence": att})
            out.append(d)
            continue
        if cand["kind"] in LABEL_KINDS:
            d.update({"class": "held", "reason": "unconsumed_label"})
            out.append(d)
            continue
        s0, s1 = _sentence(text, sp["start"])
        sent = text[s0:s1]
        evidence = ct.locate(s0, s1)
        completed = bool(_COMPLETED_RE.search(sent))
        reason = None
        if cand["kind"] == "roll_call" and _roll_call_heading(text, sp):
            reason = "roll_call_heading"
            ls = text.rfind("\n", 0, sp["start"]) + 1
            le = text.find("\n", sp["end"])
            evidence = ct.locate(ls, len(text) if le == -1 else le)
        elif cand["kind"] in ("absent_word",) and _NON_MEMBER_RE.search(sent):
            reason = "non_member_attendance"
        elif cand["kind"] in _VOTEISH:
            # a completed action is a vote record unless it is another body's or an earlier one
            if not completed and _VOTING_ROLE_RE.search(sent):
                reason = "voting_role"
            elif not completed and _VOTE_REQUIREMENT_RE.search(sent):
                reason = "vote_requirement"
            elif not completed and _ELECTION_RE.search(sent):
                reason = "election_context"
            elif _OTHER_BODY_RE.search(sent):
                reason = "other_body_vote"
            elif _EARLIER_RE.search(sent) and re.search(r"\bvot(?:ed|e)\b", sent, re.I):
                reason = "earlier_vote"
            elif _PROSPECTIVE_RE.search(sent) and not re.search(r"\bvoted\b|\bunanimously\b", sent, re.I):
                item_start = _item_start(text, sp["start"])
                if not any(c["start"] >= item_start and c["start"] < sp["start"] for c, _ in consumed):
                    reason = "agenda_description"
        if reason:
            d.update({"class": "excluded", "reason": reason, "evidence": evidence})
        else:
            d.update({"class": "held", "reason": "narrative_vote_unaccounted"
                      if cand["kind"] in _VOTEISH else "unaccounted_attendance_word"})
        out.append(d)
    return out


def events_to_hold(candidates: list[dict], events: list[dict]) -> dict[str, str]:
    """Events whose vote block holds a vote label they did not consume (a second roll call swallowed
    by an oversized block): those events cannot be trusted and are held."""
    out: dict[str, str] = {}
    for cand in candidates:
        if cand["kind"] not in LABEL_KINDS:
            continue
        sp = cand["span"]
        if any(_overlaps(sp, c) for e in events for c in e["consumed"]):
            continue
        for e in events:
            b = e.get("block")
            if b and b["start"] <= sp["start"] < b["end"]:
                out[e["event_id"]] = "unconsumed_vote_label"
    return out


_CORE = ("cand_id", "kind", "class", "event_id", "reason", "evidence")


def document_disposition(ct: CanonicalText, candidates: list[dict], *, doc_sha256: str) -> dict:
    """A document-level record, so a document with no candidates is accounted for explicitly."""
    first = next((ln.strip() for ln in ct.text.split("\n") if ln.strip() and ln.strip() != "\f"), "")
    return {"doc_sha256": doc_sha256, "class": "has_candidates" if candidates else "no_candidates",
            "candidates": len(candidates), "first_line": first[:120]}


def check_partition(candidates: list[dict], dispositions: list[dict], events: list[dict], *,
                    ct: CanonicalText | None = None, attendance_spans: list[dict] | None = None,
                    transcript: bool = False) -> list[str]:
    """Problems with the partition (empty list = every candidate has exactly one valid disposition).
    With the document's text, every disposition is also re-derived from the rules and must agree
    (ownership of consumed text, exclusion reason and evidence)."""
    problems: list[str] = []
    event_ids = [e["event_id"] for e in events]
    if len(set(event_ids)) != len(event_ids):
        problems.append("duplicate event ids")
    cand_ids = [c["cand_id"] for c in candidates]
    disp_ids = [d["cand_id"] for d in dispositions]
    status = {e["event_id"]: e["status"] for e in events}
    if len(set(cand_ids)) != len(cand_ids):
        problems.append("duplicate candidate ids")
    missing = set(cand_ids) - set(disp_ids)
    extra = set(disp_ids) - set(cand_ids)
    if missing:
        problems.append(f"{len(missing)} candidates without a disposition")
    if extra:
        problems.append(f"{len(extra)} dispositions without a candidate")
    dup = len(disp_ids) - len(set(disp_ids))
    if dup:
        problems.append(f"{dup} candidates with more than one disposition")
    for d in dispositions:
        if d["class"] not in CLASSES:
            problems.append(f"{d['cand_id']}: unknown class {d['class']!r}")
            continue
        if not d.get("reason"):
            problems.append(f"{d['cand_id']}: no reason")
        if d["event_id"] is not None:
            if d["event_id"] not in status:
                problems.append(f"{d['cand_id']}: unknown event {d['event_id']}")
            elif status[d["event_id"]] != d["class"]:
                problems.append(f"{d['cand_id']}: class {d['class']} but event is {status[d['event_id']]}")
        elif d["class"] in ("named", "expanded"):
            problems.append(f"{d['cand_id']}: {d['class']} without an event")
        if d["class"] == "excluded" and not d.get("evidence"):
            problems.append(f"{d['cand_id']}: excluded without evidence")
    if ct is not None:
        again = {d["cand_id"]: d for d in dispose(ct, candidates, events, attendance_spans=attendance_spans or [],
                                                 transcript=transcript)}
        for d in dispositions:
            want = again.get(d["cand_id"])
            if want and any(d.get(k) != want.get(k) for k in _CORE):
                problems.append(f"{d['cand_id']}: disposition differs from the rules' ({want['class']}, "
                                f"{want['reason']})")
    return problems
