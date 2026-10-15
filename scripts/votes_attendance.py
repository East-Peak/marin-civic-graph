#!/usr/bin/env python3
"""Votes Part A, increment d: attendance as a state, item by item, and the ALL expansion.

The state walks the document in order: who could be present (the roster, from the roll call),
who is present, which body is in session, whether the state is certain, and transitions that
happened at an unknown point (a retrospective "arrived at 6:52 p.m." in the opening section).

Transitions: roll call; "All Supervisors were present"; timed or verbal arrivals and departures;
"X was absent"; recesses, reconvening (with or without an attendance statement); the Board
sitting as another body; and a fully named vote block (it shows exactly who was there). Any
member-anchored attendance wording that no rule reads makes the state uncertain until it is
re-established.

An `AYES: ALL` event expands only from a certain state with no pending transition, in the body's
own session: aye = present − the item's named absences, recusals, noes and abstentions − prose
recusals/abstentions in the item. Its evidence is every transition since the last
re-establishment. Named events are checked against the roster (and against a certain state).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from votes_text import CanonicalText

SEATS = {"novato-city-council": 5, "marin-county-bos": 5}

_TITLE = (r"(?:Supe\w*visors?|Councilmembers?|Council\s+Members?|Councilwoman|Councilman|"
          r"Mayor\s+Pro\s+Tem(?:pore)?|Vice\s+Mayor|Mayor|Vice\s+President|President)")
_REF = rf"(?-i:(?i:{_TITLE})\s+(?:[A-Z][\w']*\s+)?(?P<n>[A-Z][\w'\-]*))"
_TIME = r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?|AM|PM)?"

_BOS_PRESENT_RE = re.compile(r"^[ \t]*(?i:present):[ \t]*(?P<p>[^\n]*)$", re.M)
_BOS_ABSENT_LINE_RE = re.compile(r"(?:[ \t]*\n)?^[ \t]*(?i:absent)(?::|[ \t]{2,})[ \t]*(?P<a>[^\n]*)$", re.M)
_NOV_PRESENT_RE = re.compile(r"COUNCIL\s+PRESENT(?:\s+VIA\s+TELECONFERENCE)?\s*:", re.I)
_NOV_ABSENT_RE = re.compile(r"COUNCIL\s+(?:ABSENT|EXCUSED\s+ABSENCE)\s*:|^[ \t]*EXCUSED\s+ABSENCE\s*:", re.I | re.M)
_NOV_TARDY_RE = re.compile(r"COUNCIL\s+EXCUSED\s+TARDINESS\s*:", re.I)

_ALL_PRESENT_RE = re.compile(r"\bAll\s+(?:Supervisors|Board\s+members|Councilmembers|Council\s+members|members)"
                             r"(?:\s+of\s+the\s+\w+)?\s+(?:were\s+)?present\b", re.I)
_TIMED_RE = re.compile(rf"\(?\s*{_REF}\s+(?P<v>present|absent)\s+(?:at\s+)?{_TIME}\s*\)?"
                       rf"|\(\s*{_REF.replace('(?P<n>', '(?P<n2>')}\s+(?P<v2>present|absent)\s*\)", re.I)
_PAIR_RE = re.compile(rf"{_REF}\s+and\s+{_REF.replace('(?P<n>', '(?P<n2>')}\s+(?P<v>returned|arrived|rejoined|left|"
                      rf"departed|were\s+absent)\b", re.I)
_TIMED_PLURAL_RE = re.compile(r"(?-i:(?i:Supervisors|Councilmembers)\s+(?P<list>[A-Z][\w'\-]*(?:\s*,\s*[A-Z][\w'\-]*)*"
                              rf"\s*,?\s+and\s+[A-Z][\w'\-]*))\s+(?P<v>present|absent)\s+(?:at\s+)?{_TIME}", re.I)
_ARRIVE_RE = re.compile(rf"{_REF}\s+(?:arrived|returned|rejoined|joined\s+the\s+meeting)\b", re.I)
_RECUSE_LEFT_RE = re.compile(rf"{_REF}\s+recused\b[^.\n]*?\band\s+(?:left|departed|exited)\b", re.I)
_DEPART_RE = re.compile(rf"{_REF}\s+(?:left|departed|exited|stepped\s+(?:out|down|away)|was\s+excused)\b", re.I)
_WAS_ABSENT_RE = re.compile(rf"{_REF}\s+(?:(?:was|is|being)\s+)?absent\b", re.I)
_WERE_ABSENT_RE = re.compile(r"(?-i:(?i:Supervisors|Councilmembers)\s+(?P<list>[A-Z][\w'\-]*(?:\s*,\s*[A-Z][\w'\-]*)*"
                             r"\s*,?\s+and\s+[A-Z][\w'\-]*))\s+were\s+absent\b", re.I)
_RECESS_RE = re.compile(r"\brecess(?:ed)?\b|\btook\s+a\s+(?:brief\s+)?recess\b", re.I)
_RECONVENE_RE = re.compile(r"\breconven\w*|\breturned\s+at\b|\b(?:re)?convened?\s+(?:as|in)\b", re.I)
_AS_BODY_RE = re.compile(r"\b(?:to\s+meet|to\s+convene|convened?|reconvened?|sitting|recessed|recess)\s+as\s+the\s+"
                         r"(?P<b>[^.\n]+?)(?=\s+and\s+(?:re)?conven|\s+at\s+\d|\s+and\s+returned|\.|$)", re.I | re.M)
_CLOSED_RE = re.compile(r"\b(?:to\s+meet\s+in|to|into)\s+closed\s+session\b|\bRecess\s+to\s+Closed\s+Session\b", re.I)
_OPEN_RE = re.compile(r"\bin\s+open\s+session\b|\bOpen\s+Session\b", re.I)
# member-anchored attendance wording (the member is the subject): anything here that no transition
# rule read makes the state uncertain. "presented", "Department", "attending a screening" never match.
_TRIGGER_RE = re.compile(
    rf"{_REF}(?:[ \t]+\S+){{0,3}}?[ \t]+(?:(?:was|were|is|are|will\s+be|would\s+be)\s+(?:absent|present|excused|"
    rf"not\s+present|unavailable|away|attending)|arriv\w*|left\s+the\b|departed|returned\s+to\s+the\s+"
    rf"(?:meeting|dais|chambers?|room)|rejoin\w*|stepped\s+(?:out|away|down)|absent\b|present\s+at\b|excused\b)",
    re.I)
_OTHER_BODY_WORDS = re.compile(r"District|Authority|Agency|Housing|Commission|Open\s+Space|Financing|Successor|"
                               r"Joint\s+Powers|Board\s+of\s+Directors|Board\s+of\s+Commissioners|Corporation", re.I)


_NARROW_SCOPE_RE = re.compile(r"\b(?:C[AB]-?\d+[a-z]?|[A-Z]\.\d+|items?\s+[A-Z]?[\d.-]+[a-z]?|minutes)\b", re.I)


def _key(name: str) -> str:
    return name.upper().strip(".,;:")


_PLURAL_LIST_RE = re.compile(r"(?-i:(?i:Supervisors|Councilmembers)\s+(?P<list>[A-Z][\w'\-]*(?:\s*,\s*[A-Z][\w'\-]*)*"
                             r"(?:\s*,?\s+and\s+[A-Z][\w'\-]*)?))")


def _names_in(fragment: str) -> list[str]:
    """Member surnames in a roll-call fragment: titled references ("Supervisor X") and plural
    lists ("Supervisors X, Y and Z")."""
    names = [_key(m.group("n")) for m in re.finditer(_REF, fragment)]
    for m in _PLURAL_LIST_RE.finditer(fragment):
        names += [_key(n) for n in re.findall(r"[A-Z][\w'\-]*", m.group("list"))]
    return sorted(set(names), key=names.index)


_LATE_IN_ROLL_RE = re.compile(rf"{_REF}\s*\(?\s*(?:arrived|present)\s+(?:at\s+)?{_TIME}", re.I)


def _late_in(fragment: str) -> list[str]:
    """Members a roll call lists with an arrival time: not there when it was taken."""
    return [_key(m.group("n")) for m in _LATE_IN_ROLL_RE.finditer(fragment)]


def _fully_named(fragment: str) -> bool:
    """Every word of a member list is a title, a name it reads, or a connector."""
    names = set(_names_in(fragment))
    if not names:
        return False
    rest = re.sub(_REF, " ", fragment)
    rest = _PLURAL_LIST_RE.sub(" ", rest)
    return not re.sub(r"(?i)\b(?:and|or)\b|[,;.()\s-]", "", rest)


_STATEMENT_STOP_RE = re.compile(r"\n[ \t]*\n|\n(?=[ \t]*(?:\d{1,2}\.|[A-Z]\.|M/s|AYES|NOES|Vote|Present|Absent|"
                                r"COUNCIL\b|The\s+Board\b))")


def _statement_rest(text: str, pos: int) -> str:
    """The rest of a statement's sentence after pos: up to its period, across PDF line wraps, but
    never past a blank line or a line that starts something else."""
    stop = _STATEMENT_STOP_RE.search(text, pos)
    limit = stop.start() if stop else len(text)
    period = re.search(r"\.(?:\s|$)", text[pos:limit])
    return text[pos:pos + (period.start() if period else limit - pos)]


def _vacancies(fragment: str) -> int:
    return len(re.findall(r"\bvacan(?:t|cy)\b", fragment, re.I))


@dataclass
class _T:
    start: int
    end: int
    kind: str
    present: frozenset = frozenset()
    absent: frozenset = frozenset()
    pending: frozenset = frozenset()
    vacancies: int = 0
    member: str | None = None
    body: str | None = None
    retro: bool = False
    reset: bool = False
    markers: tuple = ()


@dataclass
class _State:
    roster: set = field(default_factory=set)
    vacancies: int = 0
    present: set = field(default_factory=set)
    pending_arrival: set = field(default_factory=set)
    pending_departure: set = field(default_factory=set)
    certain: bool = False
    body: str = "main"
    before_closed: str = "main"
    statement_from: tuple | None = None
    statement_absent: set = field(default_factory=set)
    known: bool = False
    evidence: list = field(default_factory=list)

    def complete(self, seats: int) -> bool:
        return self.known and len(self.roster) + self.vacancies == seats


def _body_of(name: str, body: str) -> str:
    # "the Board of Supervisors and Flood Control District, …": the first body named decides
    n = re.split(r",|\s+and\s+(?=(?:the\s+)?[A-Z])", name.strip())[0].strip()
    if body == "marin-county-bos":
        if re.match(r"(?:the\s+)?(?:Marin\s+County\s+|Fictional\s+County\s+)?Board\s+of\s+Supervisors\b", n, re.I) \
                and not _OTHER_BODY_WORDS.search(n.split(",")[0]):
            return "main"
    elif re.match(r"(?:the\s+)?(?:Novato\s+)?City\s+Council\b", n, re.I) and not _OTHER_BODY_WORDS.search(n):
        return "main"
    return "other:" + re.sub(r"\s+", " ", n.split(",")[0]).strip()[:80]


def _shadow(text: str) -> str:
    """The text with periods inside times and common abbreviations blanked (same length), so
    sentence boundaries are real ones: "recessed at 10:00 a.m. to meet as …" is one sentence."""
    return re.sub(r"\b([ap])\.([m])\.", lambda m: f"{m.group(1)}_{m.group(2)}_",
                  re.sub(r"\b(No|St|Dr|Mr|Ms|Mrs|Inc)\.", lambda m: m.group(1) + "_", text, flags=re.I), flags=re.I)


def _transitions(ct: CanonicalText, body: str, skip: list[tuple[int, int]]) -> list[_T]:
    text = _shadow(ct.text)
    out: list[_T] = []

    def skipped(pos: int) -> bool:
        return any(s <= pos < e for s, e in skip)

    # roll calls
    if body == "marin-county-bos":
        for m in _BOS_PRESENT_RE.finditer(text):
            line = m.group("p")
            end = m.end()
            # a PDF roll call wraps onto indented lines (a surname may break at its hyphen)
            while True:
                nxt_line = re.match(r"\n([ \t]+)(\S[^\n]*)", text[end:])
                if not nxt_line or re.match(r"(?:Absent|Present)\s*:", nxt_line.group(2)) \
                        or not re.search(_REF, nxt_line.group(2)) and not re.match(r"[a-z]", nxt_line.group(2)):
                    break
                cont = nxt_line.group(2).strip()
                line = (line[:-1] + cont) if line.rstrip().endswith("-") else (line + " " + cont)
                end += nxt_line.end()
            parts = re.split(r"(?i)absent:", line, maxsplit=1)
            pres_part, abs_part = (parts[0], parts[1]) if len(parts) == 2 else (line, "")
            nxt = _BOS_ABSENT_LINE_RE.match(text, m.end() + 1) if m.end() < len(text) else None
            if nxt:
                abs_part = (abs_part + " " + nxt.group("a")).strip()
                end = nxt.end()
            late = frozenset(_late_in(pres_part))
            out.append(_T(m.start() + len(m.group(0)) - len(m.group(0).lstrip()), end, "roll_call",
                          present=frozenset(_names_in(pres_part)) - late, absent=frozenset(_names_in(abs_part)),
                          pending=late, vacancies=_vacancies(abs_part)))
    else:
        for m in _NOV_PRESENT_RE.finditer(text):
            stop = re.compile(r"\n[ \t]*\n|STAFF\s+PRESENT|COUNCIL\s+ABSENT|COUNCIL\s+EXCUSED|^[ \t]*EXCUSED|"
                              r"^[ \t]*[A-Z]\.[ \t]", re.I | re.M).search(text, m.end())
            pres_end = stop.start() if stop else min(len(text), m.end() + 400)
            late_here = _late_in(text[m.end():pres_end])
            present = [n for n in _names_in(text[m.end():pres_end]) if n not in late_here]
            absent: list[str] = []
            pending: list[str] = list(late_here)
            vac = 0
            end = pres_end
            window_end = min(len(text), pres_end + 600)
            for am in _NOV_ABSENT_RE.finditer(text, pres_end, window_end):
                line_end = text.find("\n", am.end())
                line_end = len(text) if line_end == -1 else line_end
                frag = text[am.end():line_end]
                absent += _names_in(frag)
                vac += _vacancies(frag)
                end = max(end, line_end)
            for tm in _NOV_TARDY_RE.finditer(text, pres_end, window_end):
                line_end = text.find("\n", tm.end())
                line_end = len(text) if line_end == -1 else line_end
                pending += _names_in(text[tm.end():line_end])
                end = max(end, line_end)
            out.append(_T(m.start(), end, "roll_call", present=frozenset(present), absent=frozenset(absent),
                          pending=frozenset(pending), vacancies=vac))

    if body != "marin-county-bos":
        merged: list[_T] = []
        for t in sorted(out, key=lambda t: t.start):
            prev = merged[-1] if merged else None
            gap = text[prev.end:t.start] if prev else ""
            if prev and prev.end <= t.start and not gap.strip():
                merged[-1] = _T(prev.start, max(prev.end, t.end), "roll_call", present=prev.present | t.present,
                                absent=(prev.absent | t.absent) - (prev.present | t.present),
                                pending=prev.pending | t.pending, vacancies=max(prev.vacancies, t.vacancies))
            elif prev and t.start < prev.end:
                merged[-1] = _T(prev.start, max(prev.end, t.end), "roll_call", present=prev.present | t.present,
                                absent=(prev.absent | t.absent) - (prev.present | t.present),
                                pending=prev.pending | t.pending, vacancies=max(prev.vacancies, t.vacancies))
            else:
                merged.append(t)
        out = merged

    roll_spans = [(t.start, t.end) for t in out]

    def inside_roll(pos: int) -> bool:
        return any(s <= pos < e for s, e in roll_spans)

    # a statement inside a roll call's own paragraph is a summary, not a placed event
    paragraphs = list(roll_spans) if body == "marin-county-bos" else []
    for s0, e0 in (roll_spans if body != "marin-county-bos" else []):
        stop = re.compile(r"^[ \t]*[A-Z]\.(?:[ \t]|$)", re.M).search(text, e0)
        paragraphs.append((s0, stop.start() if stop else len(text)))

    def retrospective(pos: int) -> bool:
        return any(s0 <= pos < e0 for s0, e0 in paragraphs)

    claimed: list[tuple[int, int]] = []

    def add(t: _T) -> None:
        out.append(t)
        claimed.append((t.start, t.end))

    # members may also be named by surname alone once a roll call has named them
    roster_names = sorted({n for t in out for n in (t.present | t.absent | t.pending)}, key=len, reverse=True)
    bare = None
    if roster_names:
        alts = "|".join(re.escape(v) for n in roster_names for v in {n.title(), n})
        bare = rf"(?<![\w'\-])(?P<n>{alts})(?![\w'\-])"

    def coordinated(m, kind: str) -> None:
        """'left the meeting at 9:40 a.m. and returned at 10:00 a.m.': the same subject's second verb."""
        end = text.find(". ", m.end())
        end = len(text) if end == -1 else end
        nl = text.find("\n\n", m.end())
        end = min(end, nl) if nl != -1 else end
        follow = re.compile(r"\band\s+(?:later\s+)?(?:returned|rejoined)\b" if kind == "depart"
                            else r"\band\s+(?:later\s+)?(?:left|departed)\b", re.I).search(text, m.end(), end)
        if follow:
            add(_T(follow.start(), follow.end(), "arrive" if kind == "depart" else "depart",
                   member=_key(m.group("n")), retro=retrospective(follow.start())))

    for m in _ALL_PRESENT_RE.finditer(text):
        if not skipped(m.start()) and not inside_roll(m.start()):
            # the statement is the whole sentence: nothing more → everyone; an exception list → everyone
            # but them; anything else ("…for the afternoon", "…attending remotely") → uncertain
            rest = _statement_rest(text, m.end())
            ex = re.fullmatch(r"\s*[,;:(\-]*\s*(?:except(?:\s+for)?|with\s+the\s+exception\s+of|but|other\s+than)\s+"
                              r"([^()]*?)\)?\s*", rest)
            end = m.end() + len(rest)
            if not rest.strip(" \t\n,;:"):
                add(_T(m.start(), m.end(), "all_present"))
            elif ex and _fully_named(ex.group(1)):
                add(_T(m.start(), end, "all_present", absent=frozenset(_names_in(ex.group(1)))))
            else:
                add(_T(m.start(), end, "uncertain"))
    for m in _TIMED_RE.finditer(text):
        if skipped(m.start()) or inside_roll(m.start()):
            continue
        verb, name = (m.group("v"), m.group("n")) if m.group("v") else (m.group("v2"), m.group("n2"))
        kind = "arrive" if verb.lower() == "present" else "depart"
        add(_T(m.start(), m.end(), kind, member=_key(name), retro=retrospective(m.start())))
    for m in _PAIR_RE.finditer(text):
        if skipped(m.start()) or inside_roll(m.start()):
            continue
        kind = "arrive" if m.group("v").lower() in ("returned", "arrived", "rejoined") else "depart"
        for name in (m.group("n"), m.group("n2")):
            add(_T(m.start(), m.end(), kind, member=_key(name), retro=retrospective(m.start())))
    for m in _TIMED_PLURAL_RE.finditer(text):
        if skipped(m.start()) or inside_roll(m.start()):
            continue
        kind = "arrive" if m.group("v").lower() == "present" else "depart"
        for n in re.findall(r"[A-Z][\w'\-]*", m.group("list")):
            add(_T(m.start(), m.end(), kind, member=_key(n), retro=retrospective(m.start())))
    for m in _RECUSE_LEFT_RE.finditer(text):
        if not skipped(m.start()) and not inside_roll(m.start()):
            add(_T(m.start(), m.end(), "depart", member=_key(m.group("n")), retro=retrospective(m.start())))
    rules = [(_ARRIVE_RE, "arrive"), (_DEPART_RE, "depart"), (_WAS_ABSENT_RE, "absent_statement")]
    if bare:
        verbs = {"arrive": r"(?:arrived|returned|rejoined|joined\s+the\s+meeting)\b",
                 "depart": r"(?:left|departed|exited|stepped\s+(?:out|down|away)|was\s+excused)\b",
                 "absent_statement": r"(?:was|is)\s+absent\b"}
        rules += [(re.compile(rf"{bare}\s+{v}"), k) for k, v in verbs.items()]
    for rx, kind in rules:
        for m in rx.finditer(text):
            if skipped(m.start()) or inside_roll(m.start()) or any(s <= m.start() < e for s, e in claimed):
                continue
            add(_T(m.start(), m.end(), kind, member=_key(m.group("n")), retro=retrospective(m.start())))
            if kind in ("arrive", "depart"):
                coordinated(m, kind)
    for m in _WERE_ABSENT_RE.finditer(text):
        if skipped(m.start()) or inside_roll(m.start()):
            continue
        for n in re.findall(r"[A-Z][\w'\-]*", m.group("list")):
            add(_T(m.start(), m.end(), "absent_statement", member=_key(n), retro=retrospective(m.start())))

    # recess / reconvene / body changes, one per sentence
    for m in re.finditer(r"[^.\n]*(?:\brecess|\breconven|\bconvene|\bsitting\s+as|\breturned\s+at)[^.\n]*\.?", text, re.I):
        s, e = m.start(), m.end()
        if skipped(s) or inside_roll(s):
            continue
        sent = m.group(0)
        lead = len(sent) - len(sent.lstrip())
        s += lead
        recess = bool(_RECESS_RE.search(sent))
        reconvene = bool(_RECONVENE_RE.search(sent))
        # every body-changing clause, in order; the state machine walks them
        markers: list[tuple[int, str, str | None]] = []
        for bm in _AS_BODY_RE.finditer(sent):
            if re.match(r"recess", bm.group(0), re.I):
                markers.append((bm.start("b"), "as", "recess"))
            else:
                markers.append((bm.start("b"), "as", _body_of(bm.group("b"), body)))
        for cm in _CLOSED_RE.finditer(sent):
            markers.append((cm.end(), "closed", None))
        for om in _OPEN_RE.finditer(sent):
            markers.append((om.end(), "generic", None))
        for rm in _RECONVENE_RE.finditer(sent):
            if rm.group(0).lower().startswith("returned") and re.search(rf"{_REF}\s*$", sent[:rm.start()]):
                continue  # a member returning, not the body
            if not _AS_BODY_RE.match(sent, rm.start()):
                markers.append((rm.end(), "generic", None))
        markers.sort()
        # "reconvened in open session" is one return, not two
        markers = [mk for i, mk in enumerate(markers)
                   if not (mk[1] == "generic" and i and markers[i - 1][1] == "generic")]
        if not markers and not reconvene and not recess:
            continue
        add(_T(s, e, "reconvene" if reconvene else "recess",
               markers=tuple((k, v) for _, k, v in markers)))

    # member-anchored attendance wording no rule read: uncertainty
    triggers = [_TRIGGER_RE]
    if bare:
        triggers.append(re.compile(_TRIGGER_RE.pattern.replace(_REF, bare, 1), re.I))
    starts = sorted({r.start() for r in re.finditer(_REF, text)}
                    | ({r.start() for r in re.finditer(bare, text)} if bare else set()))
    for pos in starts:
        m = next((mm for mm in (rx.match(text, pos) for rx in triggers) if mm), None)
        if m is None:
            continue
        if skipped(m.start()) or inside_roll(m.start()):
            continue
        if any(s <= m.start() < e or s < m.end() <= e for s, e in claimed):
            continue
        add(_T(m.start(), m.end(), "uncertain", member=_key(m.group("n"))))
        claimed.append((m.start(), m.end()))

    out.sort(key=lambda t: (t.start, t.kind))
    return out


def _span(ct: CanonicalText, start: int, end: int) -> dict:
    return ct.locate(start, end)


def resolve(ct: CanonicalText, *, body: str, events: list[dict]) -> tuple[list[dict], list[dict]]:
    """(events with attendance decided, attendance trace)."""
    seats = SEATS[body]
    # attendance never reads a vote block as a transition (the validator verifies blocks); it reads
    # everything else, motion wording included (a recusal sentence may also say who left the room)
    skip = [(ev["block"]["start"], ev["block"]["end"]) for ev in events if ev.get("block")]
    transitions = _transitions(ct, body, skip)
    items: list[tuple[int, int, str, object]] = [(t.start, 0, "t", t) for t in transitions]
    for ev in events:
        pos = ev["block"]["start"] if ev.get("block") else (ev["motion"]["span"]["start"] if ev["motion"] else 0)
        items.append((pos, 1, "e", ev))
    items.sort(key=lambda x: (x[0], x[1]))

    st = _State()
    trace: list[dict] = []
    out_events: list[dict] = []

    def re_establish(span: dict) -> None:
        st.evidence = [span]
        st.certain = st.complete(seats) and not st.pending_arrival and not st.pending_departure

    for _, _, what, obj in items:
        if what == "t":
            t: _T = obj  # type: ignore[assignment]
            span = _span(ct, t.start, t.end)
            if t.kind == "roll_call":
                st.roster = set(t.present | t.absent | t.pending)
                st.vacancies = t.vacancies
                st.present = set(t.present)
                # an unplaced arrival stays pending until the member is seen present (fold 11)
                st.pending_arrival = (st.pending_arrival - t.present) | set(t.pending)
                st.pending_departure = st.pending_departure - t.absent
                st.known = True
                re_establish(span)
            elif t.kind == "all_present":
                if st.known:
                    st.present = set(st.roster) - t.absent
                    st.pending_arrival.clear()
                    st.pending_departure.clear()
                re_establish(span)
            elif (t.kind == "absent_statement" and st.known and st.statement_from is not None
                  and st.statement_from[0] <= t.start <= st.statement_from[1] + 3 and t.member in st.roster):
                # "The Board reconvened at 2:00 p.m. Supervisor X was absent.": a statement of who is there
                st.statement_absent.add(t.member)
                st.present = set(st.roster) - st.statement_absent
                st.pending_departure -= st.statement_absent
                re_establish(span)
                st.statement_from = (st.statement_from[0], max(st.statement_from[1], t.end))
            elif t.kind in ("arrive", "depart", "absent_statement"):
                if t.retro and t.member and st.known and t.member not in st.roster:
                    st.roster.add(t.member)  # a summarized late arrival is a member all the same
                if t.member and st.known and t.member not in st.roster:
                    st.certain = False
                    st.evidence.append(span)
                elif t.retro:
                    (st.pending_arrival if t.kind == "arrive" else st.pending_departure).add(t.member)
                    if t.kind == "arrive":
                        st.present.discard(t.member)
                    st.certain = False
                    st.evidence.append(span)
                else:
                    if t.kind == "arrive":
                        st.present.add(t.member)
                        st.pending_arrival.discard(t.member)
                    else:
                        st.present.discard(t.member)
                        st.pending_departure.discard(t.member)
                    st.evidence.append(span)
                    st.certain = st.certain or False
            elif t.kind in ("recess", "reconvene"):
                entered_here = False
                for kind, value in t.markers:
                    if kind == "as":
                        st.body = value
                        entered_here = value != "main"
                    elif kind == "closed":
                        st.before_closed = st.body
                        st.body = "closed"
                    else:  # a generic reconvene / open session
                        if st.body == "closed":
                            st.body = st.before_closed
                        elif st.body != "main":
                            if st.body.startswith("other:") and not entered_here:
                                st.certain = False  # back from another body: who returned is unstated
                            st.body = "main"
                st.evidence.append(span)
                if t.kind == "reconvene":
                    st.statement_from, st.statement_absent = (t.start, t.end), set()
            elif t.kind == "uncertain":
                st.certain = False
                st.evidence.append(span)
            if t.kind not in ("reconvene", "absent_statement"):
                st.statement_from = None
            trace.append({"kind": t.kind, "span": span, "member": t.member, "body_after": st.body,
                          "present_after": sorted(st.present), "certain_after": st.certain,
                          "pending_after": sorted(st.pending_arrival | st.pending_departure)})
            continue

        ev = dict(obj)  # type: ignore[arg-type]
        ev["categories"] = {k: list(v) for k, v in ev["categories"].items()}
        ev["hold_reasons"] = list(ev["hold_reasons"])
        named = {c: {n["name"] for n in ev["categories"][c]} for c in ev["categories"]}
        listed = set().union(*named.values()) if named else set()
        reasons: list[str] = []
        if ev["status"] == "needs_attendance":
            if not st.known or not st.complete(seats) or not st.certain:
                reasons.append("pending_transition" if (st.pending_arrival or st.pending_departure)
                               else "ambiguous_attendance")
            elif st.body != "main" or (ev["motion"] and ev["motion"].get("acting_as")):
                reasons.append("body_unclear")
            else:
                parties = {(ev["motion"] or {}).get(k) for k in ("mover", "seconder")} - {None}
                if parties & st.roster - st.present:
                    reasons.append("mover_not_present")  # whoever moved or seconded was there: the state is wrong
                if ev.get("consent") and any(_NARROW_SCOPE_RE.search(ct.text[x["span"]["start"]:x["span"]["end"]
                                                                               + 120].split(".")[0])
                                             for x in ev.get("item_exceptions", [])):
                    reasons.append("exception_scope_conflict")  # stood aside from part of the calendar only
            unknown = listed - st.roster if st.known else set()
            if unknown:
                reasons.append("name_unknown")
            if not reasons:
                excluded = (named["absent"] | named["recused"] | named["no"] | named["abstain"]
                            | {x["name"] for x in ev.get("item_exceptions", [])})
                aye = sorted(st.present - excluded)
                ev["categories"]["aye"] = [{"name": n, "raw": None, "span": None, "inferred": True} for n in aye]
                tally = ev.get("tally")
                if tally and not tally.get("unrecognized"):
                    if tally["a"] != len(aye) or tally["n"] != len(named["no"]):
                        reasons.append("tally_mismatch")
                    if tally.get("x") is not None and tally["x"] != len(named["abstain"] | named["recused"]
                                                                        | named["absent"]):
                        reasons.append("tally_mismatch")
                    for key, count in (tally.get("keyed") or {}).items():
                        if count != len(named[key]):
                            reasons.append("tally_mismatch")
                if reasons:
                    ev["categories"]["aye"] = []
            ev["status"] = "held" if reasons else "expanded"
            ev["hold_reasons"] = sorted(set(reasons))
        elif ev["status"] == "named":
            if st.known and not st.complete(seats):
                new = listed - st.roster
                if new and len(st.roster) + st.vacancies + len(new) <= seats:
                    st.roster |= new  # the block itself names the members the roll call left out
                    ev.setdefault("flags", [])
                    ev["flags"] = list(ev["flags"]) + ["roster_completed_by_block"]
            if st.known:
                unknown = listed - st.roster
                if unknown:
                    reasons.append("name_unknown")
                elif st.certain and st.body == "main":
                    present_named = named["aye"] | named["no"] | named["abstain"]
                    if present_named - st.present:
                        reasons.append("named_not_present")
            elif "delimiter_repaired" in ev.get("flags", []):
                reasons.append("roster_unknown")
            if reasons:
                ev["status"] = "held"
                ev["hold_reasons"] = sorted(set(reasons))
        ev["attendance"] = {"present": sorted(st.present), "roster": sorted(st.roster), "certain": st.certain,
                            "body_in_session": st.body,
                            "pending": sorted(st.pending_arrival | st.pending_departure),
                            "evidence": list(st.evidence) if ev["status"] == "expanded" else []}
        out_events.append(ev)

        # what an accepted named block shows about attendance
        if ev["status"] == "named" and st.known and listed:
            seen_present = named["aye"] | named["no"] | named["abstain"] | named["recused"]
            st.pending_arrival -= seen_present
            st.pending_departure -= named["absent"]
            st.present |= seen_present & st.roster
            st.present -= named["absent"]
            if ev.get("block"):
                st.evidence.append(ev["block"])
            if listed == st.roster and all(len([c for c in named if n in named[c]]) == 1 for n in listed):
                st.present = set(st.roster) - named["absent"]
                re_establish(ev["block"])
        elif ev["status"] == "held" and ev.get("block") and st.certain and \
                {"named_not_present", "name_unknown"} & set(ev["hold_reasons"]):
            st.certain = False
            st.evidence.append(ev["block"])
    return out_events, trace
