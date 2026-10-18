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


def _printed_date(lines: list[str]) -> str | None:
    for line in lines:
        m = _DATE.search(line)
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
    end = None
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
        m3 = _L3.match(line)
        m2 = _L2_NUMBERED.match(line)
        b2 = _L2_BARE.match(line)
        m1 = _L1.match(line)
        entry = None
        if l2 and m3 and int(m3.group(1)) == l2.next_child + 1:
            entry = _Entry(3, (*l2.parts, int(m3.group(1))), f"{l2.label}.({m3.group(1)})", indent, [m3.group(2)],
                           parent=l2)
        elif l1 and m2 and int(m2.group(1)) == l1.parts[0] and m2.group(2).upper() == string.ascii_uppercase[l1.next_child]:
            entry = _Entry(2, (l1.parts[0], m2.group(2).upper()), f"{l1.parts[0]}.{m2.group(2)}", indent,
                           [m2.group(3)], parent=l1)
        elif l1 and b2 and indent > l1.indent and b2.group(1).upper() == string.ascii_uppercase[l1.next_child] \
                and (l1.child_indent is None or abs(indent - l1.child_indent) <= 2):  # siblings share an indent
            entry = _Entry(2, (l1.parts[0], b2.group(1).upper()), f"{l1.parts[0]}.{b2.group(1)}", indent,
                           [b2.group(2)], parent=l1)
        elif m1 and top and int(m1.group(1)) == (l1.parts[0] + 1 if l1 else 1):
            entry = _Entry(1, (int(m1.group(1)),), m1.group(1), indent, [m1.group(2)])
            top_indent = indent if top_indent is None else top_indent
        if entry is None:
            if deepest:
                deepest.lines.append(raw)
            continue
        if entry.parent:
            entry.parent.children += 1
            entry.parent.next_child += 1
            if entry.level == 2 and b2 and entry.parent.child_indent is None and not m2:
                entry.parent.child_indent = indent
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
        if _BODY_START.match(line) and not any(re.search(r"\bMINUTES\b", x, re.IGNORECASE) for x in rest[:j]):
            raise Unparseable("multi_session_agenda", "a second CALL TO ORDER after the agenda's end")
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


PARSERS: dict[str, Parser] = {"outline": Parser(3, parse_outline), "flat": Parser(1, parse_flat)}


def extract_text(data: bytes) -> str:
    """A PDF's text, laid out as printed (pdftotext -layout)."""
    result = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data, capture_output=True,
                            timeout=PDFTOTEXT_TIMEOUT)
    if result.returncode != 0:
        raise Unparseable(f"pdftotext exited {result.returncode}: {result.stderr.decode(errors='replace')[:200]}")
    return result.stdout.decode("utf-8", errors="replace")
