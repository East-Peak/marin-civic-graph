"""Agenda text -> items, for the weekly agenda-items stage (scripts/agenda_items.py).

A parser takes an agenda's text (pdftotext -layout) and returns

    {"printed_date": "YYYY-MM-DD" | None,   # the meeting date the agenda prints in its header
     "header": str,                         # the text before the agenda body (names the body that meets)
     "notice": None | "cancellation",       # a notice, not an agenda: nothing to load
     "items": [{"section_number", "item_number", "key", "heading", "title"}, ...]}

or raises `Unparseable`. Each parser has a version; a source's registry entry records the parser and version its
accuracy was measured at (`agenda_items.qualified`), so changing a parser un-qualifies every source on it until the
hand-check is run again.
"""
from __future__ import annotations

import re
import string
import subprocess
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

PDFTOTEXT_TIMEOUT = 60
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
_DATE = re.compile(rf"\b({'|'.join(_MONTHS)})\s+(\d{{1,2}}),?\s+(\d{{4}})", re.IGNORECASE)
_CALL = re.compile(r"\bCALL\s+TO\s+ORDER\b", re.IGNORECASE)
_TIME = r"(?:\d{1,2}:\d{2}\s*[ap]\.?\s*m\.?\s*[–—-]?\s*)?"
_BODY_START = re.compile(rf"^\s*(?:1\.\s*)?{_TIME}CALL\s+TO\s+ORDER\b", re.IGNORECASE)  # begins an agenda body
_NUMBERED_END = re.compile(rf"^(\d{{1,2}})\.\s*{_TIME}ADJOURN(?:MENT)?\b(?!\s+TO\b)", re.IGNORECASE)
_BARE_END = re.compile(r"^ADJOURN(?:MENT)?\.?$", re.IGNORECASE)
_RULE = re.compile(r"^\*{5,}$")
_POSTED = re.compile(r"^THIS MEETING WAS PROPERLY NOTICED", re.IGNORECASE)  # no ADJOURN: the posting notice ends it
# a link printed like an entry: exactly "Staff Report and Attachment(s)", "Attachment N", or a file name
_ATTACHMENT = re.compile(r"^(Staff\s+Report\s+and\s+Attachments?|Attachments?(\s+\w+)?)\.?$|\.pdf$", re.IGNORECASE)
_EXCLUDED = re.compile(rf"^{_TIME}(CALL\s+TO\s+ORDER|ROLL\s+CALL|PLEDGE|SALUTE\s+TO\s+THE\s+FLAG|ADJOURN)",
                       re.IGNORECASE)
_NONE = re.compile(r"(^|:\s*)NONE\.?$", re.IGNORECASE)
_TERMINATORS = (".", "?", "!", ":", ")")
_STOP = re.compile(r"^(Recommendation|Staff\s+Recommendation|Attachment)|^[•*\-–]\s", re.IGNORECASE)
_ODD = re.compile("[\ue000-\uf8ff]")  # private-use glyphs (a PDF's link arrows)


class Unparseable(ValueError):
    """The text is not an agenda this parser can read; the meeting holds with `reason`."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class Parser:
    version: int
    parse: Callable[[str], dict]


def _clean(text: str) -> list[str]:
    return [_ODD.sub("", line).replace("\xa0", " ").rstrip() for line in text.splitlines()]


def _canon(label: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", label).upper()


def title_of(lines: list[str], label: str) -> str:
    """The reviewer brief's mechanical title rule: the entry's first line, then the next lines while the text does
    not yet end a sentence (. ? ! : )), stopping before a blank, recommendation, attachment or bullet line."""
    text = " ".join(_ODD.sub("", lines[0]).split())
    for line in lines[1:]:
        nxt = _ODD.sub("", line).strip()
        if text.endswith(_TERMINATORS) or not nxt or _STOP.match(nxt) or nxt.lower().endswith(".pdf") \
                or _canon(nxt.split()[0]) == _canon(label):
            break
        text = f"{text} {' '.join(nxt.split())}"
    return text.strip()


def _heading(text: str) -> str:
    text = re.sub(r"\s*\([^)]*\)\s*$", "", " ".join(text.split())).rstrip(":").strip()
    return string.capwords(text) if not re.search(r"[a-z]", text) else text


def _printed_date(lines: list[str], pattern: re.Pattern = _DATE) -> str | None:
    for line in lines:
        m = pattern.search(line)
        if m:
            try:
                return date(int(m.group(3)), _MONTHS.index(m.group(1).lower()) + 1, int(m.group(2))).isoformat()
            except ValueError:
                return None
    return None


def _start(lines: list[str]) -> int | None:
    return next((i for i, line in enumerate(lines) if _CALL.search(line)), None)


def _no_body(text: str, lines: list[str]) -> dict:
    """No CALL TO ORDER: a cancellation notice is a notice; anything else is no agenda this parser reads."""
    if re.search(r"\bcancel+ed\b|notice of cancellation", text, re.IGNORECASE):
        return {"printed_date": _printed_date(lines), "header": "\n".join(lines), "notice": "cancellation",
                "items": []}
    raise Unparseable("unparseable", "no CALL TO ORDER line")


def _none_below(lines: list[str]) -> bool:
    """The entry's own continuation (up to a blank line) is just NONE: an empty section printed as an entry."""
    following = []
    for line in lines[1:]:
        if not line.strip():
            break
        following.append(line.strip())
    return len(following) == 1 and bool(re.fullmatch(r"NONE\.?", following[0], re.IGNORECASE))


def _excluded(first_line: str) -> bool:
    text = " ".join(first_line.split())
    return bool(_EXCLUDED.match(text) or _NONE.search(text))


# --- outline: numbered entries with lettered sub-entries ---------------------------------------------------


@dataclass
class _Entry:
    level: int
    parts: tuple  # (number,), (number, letter), (number, letter, n)
    label: str
    indent: int
    lines: list = field(default_factory=list)
    children: int = 0
    parent: "_Entry | None" = None
    next_child: int = 0  # index of the letter (or number) the next child must carry
    child_indent: int | None = None  # the indent of its bare-letter children (a deeper list is description)
    child_style: str | None = None  # "numbered" (4.A), "upper" (A.) or "lower" (a.): fixed by the first child
    skipped_link: int | None = None  # the letter index a link-like "N.L. Staff Report…" line was printed with


_L2_NUMBERED = re.compile(r"^(\d{1,2})\.?([A-Za-z])(?:\.\s*|\s+)(\S.*)$")
_L2_BARE = re.compile(r"^([A-Za-z])[.)]\s+(\S.*)$")
_L3 = re.compile(r"^\((\d{1,2})\)\s+(\S.*)$")
_L1 = re.compile(r"^(\d{1,2})\.\s*(\S.*)$")


def parse_outline(text: str) -> dict:
    lines = _clean(text)
    start = _start(lines)
    if start is None:
        return _no_body(text, lines)
    entries: list[_Entry] = []
    l1 = l2 = None
    top_indent = None  # the first entry's indent: a top-level entry never sits deeper (a list in a description does)
    deepest = None
    end, by_notice = None, False
    for i in range(start, len(lines)):
        raw = lines[i]
        line, indent = raw.strip(), len(raw) - len(raw.lstrip())
        if not line:
            if deepest:
                deepest.lines.append("")
            continue
        if i > start and _BODY_START.match(line):  # another meeting's agenda begins inside this one's body
            raise Unparseable("multi_session_agenda", "a second CALL TO ORDER inside the agenda's body")
        top = top_indent is None or indent <= top_indent + 3
        numbered_end = _NUMBERED_END.match(line) if top else None
        if (numbered_end and int(numbered_end.group(1)) == (l1.parts[0] + 1 if l1 else 1)) or _BARE_END.match(line):
            end = i
            break
        if l1 and (_POSTED.match(line) or (_RULE.match(line) and any(
                _POSTED.match(x.strip()) for x in [y for y in lines[i + 1:i + 6] if y.strip()][:2]))):
            end, by_notice = i, True
            break
        m3 = _L3.match(line)
        m2 = _L2_NUMBERED.match(line)
        b2 = _L2_BARE.match(line)
        m1 = _L1.match(line)
        entry, form = None, None
        if l2 and m3 and int(m3.group(1)) == l2.next_child + 1:
            entry = _Entry(3, (*l2.parts, int(m3.group(1))), f"{l2.label}.({m3.group(1)})", indent, [m3.group(2)],
                           parent=l2)
        elif l1 and m2 and int(m2.group(1)) != l1.parts[0] and l1.parts[0] - 3 <= int(m2.group(1)) < l1.parts[0] \
                and not _ATTACHMENT.search(m2.group(3)):
            raise Unparseable("label_out_of_sequence", f"{m2.group(1)}.{m2.group(2)} printed under section {l1.parts[0]}")
        elif l1 and m2 and int(m2.group(1)) == l1.parts[0] and l1.skipped_link is not None \
                and m2.group(2).upper() == string.ascii_uppercase[l1.skipped_link + 1]:
            raise Unparseable("ambiguous_attachment",
                              f"{m2.group(1)}.{m2.group(2)} follows a link-like {string.ascii_uppercase[l1.skipped_link]}")
        elif l1 and m2 and int(m2.group(1)) == l1.parts[0] and m2.group(2).upper() == string.ascii_uppercase[l1.next_child] \
                and l1.child_style in (None, "numbered") and not _ATTACHMENT.search(m2.group(3)):
            entry, form = _Entry(2, (l1.parts[0], m2.group(2).upper()), f"{l1.parts[0]}.{m2.group(2)}", indent,
                                 [m2.group(3)], parent=l1), "numbered"
        elif l1 and b2 and indent > l1.indent and b2.group(1).upper() == string.ascii_uppercase[l1.next_child] \
                and l1.child_style in (None, "upper" if b2.group(1).isupper() else "lower") \
                and (l1.child_indent is None or abs(indent - l1.child_indent) <= 2):  # siblings share a layout
            entry, form = _Entry(2, (l1.parts[0], b2.group(1).upper()), f"{l1.parts[0]}.{b2.group(1)}", indent,
                                 [b2.group(2)], parent=l1), "upper" if b2.group(1).isupper() else "lower"
        elif m1 and top and int(m1.group(1)) == (l1.parts[0] + 1 if l1 else 1):
            entry = _Entry(1, (int(m1.group(1)),), m1.group(1), indent, [m1.group(2)])
            top_indent = indent if top_indent is None else top_indent
        if entry is None:
            if l1 and m2 and int(m2.group(1)) == l1.parts[0] and _ATTACHMENT.search(m2.group(3)) \
                    and m2.group(2).upper() == string.ascii_uppercase[l1.next_child]:
                l1.skipped_link = l1.next_child  # a link printed with the next letter: a sibling after it is ambiguous
            if deepest:
                deepest.lines.append(raw)
            continue
        if entry.parent:
            entry.parent.children += 1
            entry.parent.next_child += 1
            if form and entry.parent.child_style is None:  # the first child fixes its siblings' form and indent
                entry.parent.child_style = form
                entry.parent.child_indent = None if form == "numbered" else indent
        if entry.level == 1:
            l1, l2 = entry, None
        elif entry.level == 2:
            l2 = entry
        entries.append(entry)
        deepest = entry
    if end is None:
        raise Unparseable("agenda_end_missing", "no top-level ADJOURN(MENT) after CALL TO ORDER")
    rest = lines[end + 1:]
    for j, line in enumerate(rest):
        if _BODY_START.match(line) and (by_notice or not any(re.search(r"\bMINUTES\b", x, re.IGNORECASE) for x in rest[:j])):  # a packet's minutes follow an ADJOURN
            raise Unparseable("multi_session_agenda", "a second CALL TO ORDER after the agenda's end")
    if by_notice and any(((m := _L1.match(x.strip())) and int(m.group(1)) == l1.parts[0] + 1)
                         or ((n := _L2_NUMBERED.match(x.strip())) and int(n.group(1)) == l1.parts[0])
                         or ((b := _L2_BARE.match(x.strip())) and x[:1].isspace()
                             and b.group(1).upper() == string.ascii_uppercase[l1.next_child])
                         or (l2 is not None and (c := _L3.match(x.strip())) and int(c.group(1)) == l2.next_child + 1)
                         for x in rest):  # numbered business at any level after the notice: not the end
        raise Unparseable("agenda_end_missing", "numbered business continues after the posting notice")
    items = []
    for e in entries:
        if e.children or _excluded(e.lines[0]) or _none_below(e.lines):
            continue
        top = e if e.level == 1 else e.parent if e.level == 2 else e.parent.parent
        item_number = "".join(str(p) for p in e.parts[1:])
        items.append({"label": e.label, "section_number": str(e.parts[0]), "item_number": item_number,
                      "key": (str(e.parts[0]) + item_number).lower(),
                      "heading": "" if e.level == 1 else _heading(top.lines[0]), "title": title_of(e.lines, e.label)})
    return {"printed_date": _printed_date(lines[:start]), "header": "\n".join(lines[:start]), "notice": None,
            "items": items}


# --- flat: numbered items under unnumbered headings, several sessions to a document ------------------------

_FLAT_ITEM = re.compile(r"^\s{0,8}(\d{1,2})\.\s+(\S.*)$")
_SESSION = re.compile(r"\b(Meeting|Session)\b.*\bat\s+\d{1,2}(:\d{2})?\s*[ap]\.?m", re.IGNORECASE)


def _is_heading(line: str) -> bool:
    text = re.sub(r"\s*\([^)]*\)\s*$", "", line.strip())
    return (bool(re.search(r"[A-Z]{3}", text)) and not re.search(r"[a-z]", text) and not re.match(r"\d", text)
            and not _CALL.search(text) and not _BARE_END.match(text))


def parse_flat(text: str) -> dict:
    lines = _clean(text)
    start = _start(lines)
    if start is None:
        return _no_body(text, lines)
    end = next((i for i in range(len(lines) - 1, start, -1) if _BARE_END.match(lines[i].strip())), None)
    if end is None:
        raise Unparseable("agenda_end_missing", "no ADJOURNMENT line after CALL TO ORDER")
    heading, expected, entries = "", 1, []
    for raw in lines[start:end]:
        line = raw.strip()
        m = _FLAT_ITEM.match(raw)
        if m and int(m.group(1)) in (expected, 1):
            expected = int(m.group(1)) + 1
            entries.append({"number": m.group(1), "heading": heading, "lines": [m.group(2)]})
        elif _CALL.search(line) or (_SESSION.search(line) and not m):
            heading = ""
        elif _is_heading(line):
            heading = _heading(line)
        elif entries:
            entries[-1]["lines"].append(raw)
    items = []
    for e in entries:
        if _excluded(e["lines"][0]):
            continue
        section = re.sub(r"[^A-Za-z]", "", e["heading"])[:2].upper() or "GE"
        items.append({"label": e["number"], "section_number": section, "item_number": e["number"],
                      "key": f"{section}{e['number']}".lower(), "heading": e["heading"],
                      "title": title_of(e["lines"], e["number"])})
    return {"printed_date": _printed_date(lines[:start]), "header": "\n".join(lines[:start]), "notice": None,
            "items": items}


# --- lettered: lettered items under numbered sections or ALL-CAPS headings, no CALL TO ORDER -----------------

_AGENDA_TITLE = re.compile(r"^(?:(?:REVISED|AMENDED)\s+)?AGENDA(?:\s*[-–—]\s*(?:REVISED|AMENDED))?$", re.IGNORECASE)
_COUNCIL_MASTHEAD = re.compile(r"^[A-Z][A-Z .'’-]* CITY COUNCIL$")
_SESSION_LINE = re.compile(r"^(?:(?:special|regular|adjourned)\s+)*(?:closed\s+session|meeting|session)$", re.IGNORECASE)
_CANCELLED = re.compile(r"\bcancel+ed\b|notice of cancellation", re.IGNORECASE)
_LETTERED_END = re.compile(r"^ADJOURN(?:MENT)?\b(?!\s+TO\b)", re.IGNORECASE)
_LETTERED_TOP = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")
_LETTER = re.compile(r"^([a-z])\.\s+(\S.*)$")
_ROMAN = re.compile(r"^[ivx]{2,4}\.\s")
_ROMAN_POINT = re.compile(r"^[ivx]{1,4}\.\s")  # a roman point under an item: its description, not its title
_SESSION_TITLE = re.compile(r"\bMEETING\s+AT\s+\d{1,2}(?::\d{2})?\s*[AP]\.?\s*M", re.IGNORECASE)
_OTHER_BODY = re.compile(r"\b(AGENCY|AUTHORITY|DISTRICT|BOARD)\b")
_ONLY_NONE = re.compile(r"^(?:[^:]*:\s*)?[-–—\s]*NONE\.?$", re.IGNORECASE)
_WRAPS = re.compile(r"(?:[-,–—&]|\b(?:and|or|of|the|for|to|in|an|a|with|at|on|by|from))$")
_LETTERED_STOP = re.compile(r"^(Recommended\s+Action|[•*\-–]\s)", re.IGNORECASE)
_MINUTES_HEADING = re.compile(r"^MINUTES\b")
# lettered's date: a full month name not glued to a word before it, spaces, a 1-2 digit day, a 4-digit year ending there
_EXACT_DATE = re.compile(rf"(?<![A-Za-z0-9_])({'|'.join(_MONTHS)}) +(\d{{1,2}}),? +(\d{{4}})(?![A-Za-z0-9_])",
                         re.IGNORECASE)
_SUBJECT = re.compile(r"^(?:title|position|position affected|name of case|case name|property):", re.IGNORECASE)
_CLOSED_SESSION = re.compile(r"closed\s+session", re.IGNORECASE)
_CAPTION = re.compile(r"\S\s+v\.?(?=\s|$)")  # "Ridley v. City …": a word, then v. or v standing alone


def _indent(raw: str) -> int:
    return len(raw) - len(raw.lstrip())


def _is_caps_heading(raw: str) -> bool:
    """A section heading: at the left (indent <= 4), capitals only (outside parentheses), not an entry."""
    text = re.sub(r"\([^)]*\)", "", raw.strip())
    return (_indent(raw) <= 4 and len(re.findall(r"[A-Z]", text)) >= 3 and not re.search(r"[a-z]", text)
            and not _LETTERED_TOP.match(raw.strip()) and not _LETTERED_END.match(raw.strip())
            and not _AGENDA_TITLE.match(raw.strip()))


def _abbrev(heading: str) -> str:
    return re.sub(r"[^A-Za-z]", "", heading)[:2].upper()


@dataclass
class _Parent:
    """What lettered entries hang from: a numbered entry, a heading, or nothing (`GE`)."""
    section: str
    heading: str
    label: str = ""
    run: int | None = None
    lines: list = field(default_factory=list)
    letters: int = 0
    line: int = 0


def _wrapped(lines: list[str]) -> tuple[str, int]:
    """The first line, then each line that starts lower-case or "(", or follows a line ending mid-phrase (a
    connective, comma, hyphen, dash or ampersand): a wrapped subject, and how many lines it took."""
    text = " ".join(_ODD.sub("", lines[0]).split())
    for n, line in enumerate(lines[1:], start=1):
        nxt = " ".join(_ODD.sub("", line).split())
        if not nxt or _LETTERED_STOP.match(nxt) or _ROMAN_POINT.match(nxt) \
                or not (nxt[0].islower() or nxt[0] == "(" or _WRAPS.search(text)):
            return text, n
        text = f"{text} {nxt}"
    return text, len(lines)


def _lettered_title(lines: list[str], closed: bool = False) -> str:
    """The entry's wrapped subject. A closed-session item's subject is boilerplate ("CONFERENCE WITH LEGAL
    COUNSEL…"), so it takes " - " and the line that names its position, case or property, if one comes before a
    blank line (a line beginning "v." is a roman point, not a case caption)."""
    title, used = _wrapped(lines)
    if closed:
        for k in range(used, len(lines)):
            line = " ".join(_ODD.sub("", lines[k]).split())
            if not line:
                break
            if _SUBJECT.match(line) or (_CAPTION.search(line) and not line.startswith("v.")):
                return f"{title} - {_wrapped(lines[k:])[0]}"
    return title


def _roman_ahead(lines: list[str], i: int) -> bool:
    """A line `i.` begins a roman list when `ii.` follows before the next lettered or numbered entry."""
    for line in lines[i + 1:]:
        text = line.strip()
        if _ROMAN.match(text):
            return text.startswith("ii.")
        if _LETTER.match(text) or (_LETTERED_TOP.match(text) and _indent(line) <= 8):
            return False
    return False


def _pages_joined(text: str) -> list[str]:
    """The text's lines with page breaks (form feeds) removed: a page break is not a blank line."""
    return _clean(text.replace("\f", ""))


def _council_masthead(lines: list[str]) -> bool:
    """An agenda titled by its masthead (the 2026 closed-session template): its first line is the council's name
    in capitals and the next one is all a session's name ("Special Closed Session")."""
    top = [" ".join(line.split()) for line in lines if line.strip()][:2]
    return len(top) == 2 and bool(_COUNCIL_MASTHEAD.match(top[0]) and _SESSION_LINE.match(top[1]))


def parse_lettered(text: str) -> dict:
    lines = _pages_joined(text)
    dated = next((i for i, line in enumerate(lines) if _EXACT_DATE.search(line)), len(lines))
    first = next((i for i, raw in enumerate(lines) if (_LETTERED_TOP.match(raw.strip()) and _indent(raw) <= 8)
                  or _LETTER.match(raw.strip()) or (i > dated and _is_caps_heading(raw))), None)
    header = lines[:first] if first is not None else lines
    printed = _printed_date(header, _EXACT_DATE)
    notice = {"printed_date": printed, "header": "\n".join(header), "notice": "cancellation", "items": []}
    titled = any(_AGENDA_TITLE.match(line.strip()) for line in header) or _council_masthead(header)
    entry = next((i for i, raw in enumerate(lines) if (_LETTERED_TOP.match(raw.strip()) and _indent(raw) <= 8)
                  or _LETTER.match(raw.strip())), len(lines))
    if not titled:
        if _CANCELLED.search(text):
            return notice
        raise Unparseable("unparseable", "no AGENDA title line")
    if any(_MINUTES_HEADING.match(line.strip()) for line in lines[:entry]):
        raise Unparseable("unparseable", "a minutes document, not an agenda")
    end = next((i for i in range(first or 0, len(lines)) if _indent(lines[i]) <= 8
                and _LETTERED_END.match(lines[i].strip())), None)
    stop = len(lines) if end is None else end
    general = _Parent("GE", "")
    heading, top, last, runs = None, None, 0, []  # runs: the heading each numbered run began under
    entries: list[tuple[str, _Parent, str, list]] = []  # (kind, parent, label/letter, lines) in document order
    session_lines, deepest = [], None
    for i in range(first if first is not None else stop, stop):
        raw = lines[i]
        line = raw.strip()
        if not line:
            if deepest is not None:
                deepest.append("")
            continue
        if _SESSION_TITLE.search(line):  # another session's title inside the body
            session_lines.append(len(entries))
            heading, top, general, deepest = None, None, _Parent("GE", ""), None  # letters restart under nothing
            continue
        m = _LETTERED_TOP.match(line) if _indent(raw) <= 8 else None
        if m and (int(m.group(1)) == last + 1 or int(m.group(1)) == 1):
            if int(m.group(1)) == 1:
                runs.append(heading)
            last = int(m.group(1))
            top = _Parent(m.group(1), "", label=m.group(1), run=len(runs) - 1, lines=[m.group(2)], line=i)
            entries.append(("top", top, m.group(1), top.lines))
            deepest = top.lines
            continue
        b = _LETTER.match(line)
        parent = top or heading or general
        if b and parent.letters < 26 and b.group(1) == string.ascii_lowercase[parent.letters] \
                and not (b.group(1) in "ivx" and _roman_ahead(lines, i)):
            parent.letters += 1
            deepest = [b.group(2)]
            entries.append(("letter", parent, b.group(1), deepest))
            continue
        if _is_caps_heading(raw):
            heading, top = _Parent(_abbrev(line), _heading(line), line=i), None
            deepest = None
            continue
        if deepest is not None:
            deepest.append(raw)
    if end is None:
        if not entries:
            return notice if _CANCELLED.search(text) else {**notice, "notice": None}
        raise Unparseable("agenda_end_missing", "no ADJOURNMENT after the agenda's entries")
    after = lines[end + 1:]
    for k, line in enumerate(after):
        if _MINUTES_HEADING.match(line.strip()):
            break
        if _AGENDA_TITLE.match(line.strip()) or (line.strip() and _council_masthead(after[k:])):
            raise Unparseable("multi_session_agenda", "another agenda follows the ADJOURNMENT")

    def leaf(kind, parent, lines):
        return (kind == "letter" or not parent.letters) and not (
            _excluded(lines[0]) or _ONLY_NONE.match(" ".join(lines[0].split())) or _none_below(lines))

    leaves = [n for n, e in enumerate(entries) if leaf(e[0], e[1], e[3])]
    if any(any(n < at for n in leaves) and any(n >= at for n in leaves) for at in session_lines):
        raise Unparseable("multi_session_agenda", "items under two session titles")
    prefixes, main = {}, None  # main: the first run with an item (runs of excluded leaves only are ignored)
    for run, run_heading in enumerate(runs):
        mine = [n for n in leaves if entries[n][1].run == run]
        if not mine or main is None:
            main = run if mine else main
            continue
        if run_heading is None or not _OTHER_BODY.search(run_heading.heading.upper()):
            raise Unparseable("multi_session_agenda", "a second numbered run with items")
        prefixes[run] = run_heading.section
    items = []
    for n in leaves:
        kind, parent, mark, entry_lines = entries[n]
        if kind == "top":
            section = prefixes.get(parent.run, "") + parent.section
            items.append({"label": parent.label, "section_number": section, "item_number": "",
                          "key": section.lower(), "heading": "", "title": _lettered_title(entry_lines)})
            continue
        numbered = parent.run is not None
        section = prefixes.get(parent.run, "") + parent.section if numbered else parent.section
        heading = _heading(parent.lines[0]) if numbered else parent.heading
        items.append({"label": f"{parent.label}.{mark}" if numbered else mark, "section_number": section,
                      "item_number": mark.upper(), "key": (section + mark).lower(), "heading": heading,
                      "title": _lettered_title(entry_lines, closed=bool(_CLOSED_SESSION.search(heading)))})
    return {"printed_date": printed, "header": "\n".join(header), "notice": None, "items": items}


# --- decimal: N. sections, N.M items, N.MA sub-items; one or more sessions to a document ---------------------

_SESSION_START = re.compile(r"^1\.\s+(?:ROLL\s+CALL|CALL\s+TO\s+ORDER)\b", re.IGNORECASE)
_SESSION_KIND = re.compile(r"^((?:[A-Z]+\s+)*)MEETING\b")
_MASTHEAD = re.compile(r"MEETING of the (.+)$")
_D1 = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")
_D2 = re.compile(r"^(\d{1,2})\.(\d{1,2})\s+(\S.*)$")
_D3 = re.compile(r"^(\d{1,2})\.(\d{1,2})([A-Z])\s+(\S.*)$")
_LIST_LABEL = re.compile(r"^(?:[A-Z]|\d{1,2})[.)]\s")  # "A. …", "1) …": a list under the title, not its wrap


@dataclass
class _Decimal:
    parts: tuple
    lines: list
    parent: "_Decimal | None" = None
    children: int = 0
    implicit: bool = False


def _caps_first_word(line: str) -> bool:
    word = next((w for w in line.split() if re.search(r"[A-Za-z]", w)), None)
    return word is not None and not re.search(r"[a-z]", word)


def _decimal_title(lines: list[str], label: str) -> str:
    """Capitals: the line and the following lines that also start in capitals (not a list under it); else the
    sentence rule."""
    first = " ".join(_ODD.sub("", lines[0]).split())
    if not _caps_first_word(first):
        return title_of(lines, label)
    text = first
    for line in lines[1:]:
        nxt = " ".join(_ODD.sub("", line).split())
        if not nxt or _STOP.match(nxt) or _LIST_LABEL.match(nxt) or not _caps_first_word(nxt):
            break
        text = f"{text} {nxt}"
    return text


def _session_kind(lines: list[str], start: int) -> str:
    seen = 0
    for line in reversed(lines[:start]):
        if not line.strip():
            continue
        m = _SESSION_KIND.match(line.strip())
        if m:
            return re.sub(r"[^a-z]", "", m.group(1).lower())
        seen += 1
        if seen == 3:
            break
    return ""


def _is_start(raw: str) -> bool:
    return _indent(raw) <= 3 and bool(_SESSION_START.match(raw.strip()))


def _decimal_session(lines: list[str], start: int) -> tuple[list[_Decimal], int]:
    """One session's entries, from its `1. ROLL CALL` to its closing `N. ADJOURN…` (the end's index)."""
    entries: list[_Decimal] = []
    l1 = l2 = None
    deepest = None
    for i in range(start, len(lines)):
        raw = lines[i]
        line = raw.strip()
        if not line:
            if deepest:
                deepest.lines.append("")
            continue
        if i > start and _is_start(raw):
            raise Unparseable("multi_session_agenda", "a session starts before the previous one adjourns")
        m3, m2 = _D3.match(line), _D2.match(line)
        m1 = _D1.match(line) if _indent(raw) <= 3 else None
        entry = None
        if l1 and m3 and int(m3.group(1)) == l1.parts[0]:
            sub, letter = int(m3.group(2)), m3.group(3)
            if l2 and sub == l2.parts[1] and letter == string.ascii_uppercase[l2.children]:
                entry = _Decimal((*l2.parts, letter), [m3.group(4)], parent=l2)
            elif sub == l1.children + 1 and letter == "A":  # `7.1A` printed without its `7.1`
                l2 = _Decimal((l1.parts[0], sub), [""], parent=l1, implicit=True)
                l1.children += 1
                entry = _Decimal((*l2.parts, letter), [m3.group(4)], parent=l2)
        elif l1 and m2 and int(m2.group(1)) == l1.parts[0] and int(m2.group(2)) == l1.children + 1:
            entry = _Decimal((l1.parts[0], int(m2.group(2))), [m2.group(3)], parent=l1)
        elif m1 and int(m1.group(1)) == (l1.parts[0] + 1 if l1 else 1):
            entry = _Decimal((int(m1.group(1)),), [m1.group(2)])
            if re.match(r"ADJOURN", m1.group(2), re.IGNORECASE):
                following = next((int(m.group(1)) for x in lines[i + 1:] if _indent(x) <= 3
                                  for m in [_D1.match(x.strip())] if m), None)
                if following != entry.parts[0] + 1:
                    return entries + [entry], i
        if entry is None:
            if deepest:
                deepest.lines.append(raw)
            continue
        if entry.parent:
            entry.parent.children += 1
        if len(entry.parts) == 1:
            l1, l2 = entry, None
        elif len(entry.parts) == 2:
            l2 = entry
        entries.append(entry)
        deepest = entry
    raise Unparseable("agenda_end_missing", "no ADJOURN closing the session")


def _masthead_conflict(between: list[str], printed: str | None, body: str | None) -> bool:
    """A later session's own masthead ("… MEETING of the <body>" and the date under it) for another day or body."""
    at = next((i for i in range(len(between) - 1, -1, -1) if _MASTHEAD.search(between[i])), None)
    if at is None:
        return False
    named = " ".join(_MASTHEAD.search(between[at]).group(1).split())
    near = [x for x in between[at:] if x.strip()][:3]
    day = _printed_date(near)
    return (body is not None and named != body) or (day is not None and day != printed)


def parse_decimal(text: str) -> dict:
    lines = _pages_joined(text)
    start = next((i for i, raw in enumerate(lines) if _is_start(raw)), None)
    if start is None:
        return _no_body(text, lines)
    header = lines[:start]
    if any(_MINUTES_HEADING.match(line.strip()) for line in header):
        raise Unparseable("unparseable", "a minutes document, not an agenda")
    printed = _printed_date(header)
    first_masthead = next((m for m in map(_MASTHEAD.search, header) if m), None)
    body = " ".join(first_masthead.group(1).split()) if first_masthead else None
    sessions = []
    while start is not None:
        entries, end = _decimal_session(lines, start)
        sessions.append((_session_kind(lines, start), entries))
        start = None
        for i in range(end + 1, len(lines)):
            if _MINUTES_HEADING.match(lines[i].strip()):  # an attached minutes document: not a session
                break
            if _is_start(lines[i]):
                if _masthead_conflict(lines[end + 1:i], printed, body):
                    raise Unparseable("multi_session_agenda", "a later session is another day's or body's")
                start = i
                break
    kinds = [kind for kind, _ in sessions]
    if len(sessions) > 1 and ("" in kinds or len(set(kinds)) < len(kinds)):
        raise Unparseable("multi_session_agenda", f"sessions not told apart: {kinds}")
    items = []
    for kind, entries in sessions:
        for e in entries:
            if e.children or _excluded(e.lines[0]) or _none_below(e.lines):
                continue
            label = ".".join([str(e.parts[0]), "".join(str(p) for p in e.parts[1:])]) if len(e.parts) > 1 \
                else str(e.parts[0])
            top = e.parent.parent if len(e.parts) == 3 else e.parent
            key = "".join(str(p) for p in e.parts).lower()
            items.append({"label": label, "section_number": str(e.parts[0]),
                          "item_number": "".join(str(p) for p in e.parts[1:]),
                          "key": f"{kind}{key}" if len(sessions) > 1 else key,
                          "heading": _heading(top.lines[0]) if top else "", "title": _decimal_title(e.lines, label)})
    return {"printed_date": printed, "header": "\n".join(header), "notice": None, "items": items,
            "sessions": len(sessions)}


PARSERS: dict[str, Parser] = {"outline": Parser(8, parse_outline), "flat": Parser(1, parse_flat),
                              "lettered": Parser(5, parse_lettered), "decimal": Parser(1, parse_decimal)}


def extract_text(data: bytes) -> str:
    """A PDF's text, laid out as printed (pdftotext -layout)."""
    result = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data, capture_output=True,
                            timeout=PDFTOTEXT_TIMEOUT)
    if result.returncode != 0:
        raise Unparseable(f"pdftotext exited {result.returncode}: {result.stderr.decode(errors='replace')[:200]}")
    return result.stdout.decode("utf-8", errors="replace")
