#!/usr/bin/env python3
"""Votes Part A, increment b: vote events parsed from a minutes document's canonical text.

An event is one motion's disposition: the motion (mover, seconder, kind, text), its vote block
(per-category names exactly as written, sentinels, printed tally, outcome) and a locator for
everything it read. Nothing here decides who was present: an `ALL`/`UNANIMOUS` block is left
`needs_attendance` for the attendance stage. An event that cannot be read completely is `held`
with reason codes — never dropped and never guessed.

Spans are character offsets into votes_text.CanonicalText.text; `consumed` lists every span the
event read, so the independent candidate scan can tell which vote-bearing text it accounted for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from votes_text import CanonicalText

CATEGORIES = ("aye", "no", "abstain", "recused", "absent")

TITLE = (r"(?:Supe\w*visors?|Councilmember|Council\s+Member|Councilwoman|Councilman|"
         r"(?:Mayor\s+Pro\s+Tem(?:pore)?|Vice\s+Mayor|Mayor)(?:\s*/\s*Board\s*Member)?|Board\s*Member|"
         r"Vice\s+President|President|Pres\.|"
         r"Vice\s+Chair|Chair|Director|Commissioner)")
_TITLE_LEAD_RE = re.compile(rf"^\s*{TITLE}\s+", re.I)
_NAME_TOKEN_RE = re.compile(r"^[A-Z][A-Za-z'\-]*\.?$")
_ALLCAPS_TOKEN_RE = re.compile(r"^[A-Z][A-Z'\-]+$")

# Category labels. Mixed case only where the minutes use it ("Abstain:", "Absent:").
_LABELS = [
    ("aye", r"AYES?"),
    ("no", r"NOES?|NAYS?"),
    ("abstain", r"ABSTAIN(?:ED|S)?|ABSTENTIONS?|Abstain(?:ed|s)?|Abstentions?"),
    ("recused", r"RECUS(?:ED|ALS?|E)|Recus(?:ed|als?|e)"),
    ("absent", r"EXCUSED\s+ABSENCE|ABSENT|Absent"),
]
_LABEL_RE = re.compile(r"(?<![\w-])(?:" + "|".join(f"(?P<{c}>{p})" for c, p in _LABELS) + r")[ \t]*:")
_TALLY_LINE_RE = re.compile(r"(?<![\w-])Vote[ \t]*:[ \t]*Motion\s+(?P<outcome>carried|failed|passed)"
                            r"(?P<rest>[^\n]*)", re.I)
_VOTES_INTRO_RE = re.compile(r"^[ \t]*Votes[ \t]*:[ \t]*$", re.M)
_KEYED_TALLY_RE = re.compile(r"^\s*(\d+)-(\d+)\.?((?:\s+(?:Abstain|Absent|Recused?|Noes?)\s*:\s*\d+)*)\s*\.?\s*$",
                             re.I)
_TERMINATOR_RE = re.compile(r"\b(?:The\s+)?[Mm]otion\s+(?:carried|failed|passed)\b|\bMOTION\s+(?:CARRIED|FAILED)\b")
_OUTCOME_LINE_RE = re.compile(r"^[ \t]*(?:The\s+)?[Mm]otion\s+(?P<o>carried|failed|passed)\b[^\n]*", re.M)
_PAGE_NOISE_RE = re.compile(r"^\s*(?:\f|\d{1,3}|Page\s+\d+(?:\s+of\s+\d+)?)\s*$")
_SCOPE_RE = re.compile(r"^[ \t]*\(\s*[A-Z]\.\d+(?:\s*(?:,|and|&)\s*[A-Z]\.\d+)*\s*\)[ \t]*$", re.M)
_LEADIN_RE = re.compile(r"Thereafter,?\s+the\s+vote\s+on\s+the\s+pending\s+motion\s+was\s*$", re.I)
_SENTINELS_NONE = {"NONE", "NONE."}
_SENTINELS_ALL = {"ALL", "UNANIMOUS"}

# case-sensitive even inside the case-insensitive motion patterns: "and" is never a name
_NAME = rf"(?-i:(?:(?i:{TITLE})[ \t]+)?(?:(?:[A-Z]\.|[A-Z][\w'\-]*)[ \t]+){{0,2}}[A-Z][\w'\-]*)"

# Novato headers and motion clauses (matched on the text with whitespace collapsed).
_NOV_HEADER_RE = re.compile(
    r"(?<![\w-])(?P<hdr>(?:(?P<who>[A-Z]{2,}(?:\s[A-Z]{2,}){0,3})\s+ACTION(?:\s+ON\s+MAIN\s+MOTION|\s+-\s+MAIN\s+MOTION)?"
    r"|SUBSTITUTE\s+MOTION|COUNCIL\s+MOTION)\s*:)")
_NOV_MOVER_SECONDER_RE = re.compile(
    rf"(?:Upon\s+)?(?:a\s+)?(?:substitute\s+|friendly\s+)?(?:motion|amendment)\s+(?:was\s+)?(?:made\s+)?by\s+(?P<m>{_NAME})\s*,?\s+"
    rf"(?:and\s+)?(?:was\s+)?seconded\s+by\s+(?P<s>{_NAME})", re.I)
_NOV_MOVER_ONLY_RE = re.compile(
    rf"(?:(?:Upon\s+)?(?:a\s+)?(?:substitute\s+)?motion\s+(?:was\s+)?(?:made\s+)?by\s+(?P<m>{_NAME}))"
    rf"|(?:(?P<m2>{_NAME})\s+made\s+a\s+(?:substitute\s+)?motion)", re.I)
_NOV_RESTATED_RE = re.compile(rf"(?P<m>{_NAME})\s+restated\s+(?:his|her|their|the)\s+motion", re.I)
_NOV_SECONDED_LATER_RE = re.compile(rf"motion\s+was\s+seconded\s+by\s+(?P<s>{_NAME})", re.I)
_NOV_TALLY_RE = re.compile(r"vot(?:ed|e)\s+(?:unanimously\s+)?(?:via\s+roll\s+call\s+)?"
                           r"(?P<a>\d+)-(?P<n>\d+)(?:-(?P<x>\d+))?(?![\d-])(?:\s+via\s+roll\s+call)?", re.I)
# anything that prints a count after "voted" — if it is not exactly A-N[-X], the tally is unrecognized
_NOV_TALLY_ANY_RE = re.compile(r"vot(?:ed|e)\s+(?:unanimously\s+)?(?:via\s+roll\s+call\s+)?"
                               r"(?:\d|(?:zero|one|two|three|four|five)\b)", re.I)
_ABBREVIATIONS = {"no", "nos", "st", "ave", "blvd", "dr", "mr", "ms", "mrs", "inc", "co", "corp", "ltd", "jr",
                  "sr", "vs", "etc", "approx", "rd", "hwy", "dept"}
_PERIOD_RE = re.compile(r"\.(?=\s+[A-Z(\"]|\s*$)")


class _SentenceEnd:
    """Finds the period that ends a sentence (not one after an abbreviation or an initial)."""

    @staticmethod
    def search(text: str, start: int = 0, end: int | None = None):
        end = len(text) if end is None else end
        for m in _PERIOD_RE.finditer(text, start, end):
            before = text[max(start, m.start() - 12):m.start()]
            word = re.search(r"([A-Za-z]+)$", before)
            if word and (word.group(1).lower() in _ABBREVIATIONS or len(word.group(1)) == 1):
                continue
            if re.search(r"(?:^|\s)\d{1,2}$", before):  # an enumeration ("5. Consent Calendar")
                continue
            return m
        return None


_SENTENCE_END_RE = _SentenceEnd
_NO_SECOND_RE = re.compile(r"no\s+second|lack\s+of\s+a\s+second|died\s+for\s+lack", re.I)

# Board motions name each member as "[Supervisor] [Given] Surname". A given name is taken only when the
# surname after it is followed by what must come next (the dash, or "to"/"on behalf of"), so a
# capitalized first word of the motion text ("Recommended action: …") is never read as a surname.
_TTL = rf"(?:(?i:{TITLE})[ \t]+)?"
_SUR = r"[A-Z][\w'\-]*"
_BOS_MOVER = rf"(?-i:{_TTL}(?:[A-Z][\w']*[ \t]+(?={_SUR}\s*[-/]\s))?{_SUR})"
_BOS_SECONDER = rf"(?-i:{_TTL}(?:[A-Z][\w']*[ \t]+(?={_SUR},?\s+(?:to\b|on\s+behalf)))?{_SUR})"
_BOS_NAME = rf"(?-i:(?i:{TITLE})[ \t]+{_SUR})"
_BOS_MS_RE = re.compile(rf"M/s\s+(?P<m>{_BOS_MOVER})\s*[-/]\s*(?:(?P<s>{_BOS_SECONDER})|\d+)"
                        rf"(?:,?\s+on\s+behalf\s+of\s+(?P<b>{_BOS_NAME}))?,?\s+(?:to\s+)?", re.I)
_BOS_MOVED_RE = re.compile(rf"(?:Motion\s+to\s+)?(?P<text>[^\n.]*?)\s*moved\s+by\s+(?P<m>{_NAME})\s+and\s+"
                           rf"seconded\s+by\s+(?P<s>{_NAME})", re.I)

_EXCEPTION_RE = re.compile(
    rf"{TITLE}\s+(?:[A-Z][\w'\-]*\s+)?(?P<n>[A-Z][\w'\-]*)\s+(?P<v>recused\s+(?:himself|herself|themselves|themself)"
    rf"|recused|abstained|did\s+not\s+participate)", re.I)

_TRANSCRIPT_LINE_RE = re.compile(r"^[A-Z][A-Z .'\-]{1,40}:\s")


@dataclass
class _Label:
    category: str          # one of CATEGORIES, or "tally" / "intro"
    start: int             # label start
    colon_end: int         # just after the colon (value starts here)
    value_end: int = 0     # end of value (trailing whitespace trimmed)
    value: str = ""
    names: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    sentinel: dict | None = None
    unparsed: bool = False
    tally: dict | None = None
    outcome: str | None = None


# ---------------------------------------------------------------------------------------------
# names

def split_names(raw: str) -> tuple[list[dict], list[str]]:
    """Names in a category value, with offsets into `raw`. A chunk that is not name-shaped adds
    the flag `unparsed`; ALL-CAPS surnames with no delimiter between them are split and flagged
    `delimiter_repaired` (each must then be a known member, which the attendance stage checks)."""
    names: list[dict] = []
    flags: list[str] = []
    for chunk in re.finditer(r"[^,;&]+", raw):
        c = chunk.group()
        cuts = [(m.start(), m.end()) for m in re.finditer(r"\s+and\s+", c, re.I)]
        bounds = [0] + [e for _, e in cuts]
        ends = [s for s, _ in cuts] + [len(c)]
        for ps, pe in zip(bounds, ends):
            text = c[ps:pe]
            base = chunk.start() + ps
            stripped = text.strip().rstrip(".").strip() if text.strip() not in ("",) else ""
            if not stripped:
                continue
            lead = 0
            titled = False
            while True:
                m = _TITLE_LEAD_RE.match(text[lead:])
                if not m:
                    break
                lead += m.end()
                titled = True
            body = text[lead:]
            tokens = [(m.start() + lead, m.group()) for m in re.finditer(r"\S+", body)]
            tokens = [(off, tok.rstrip(".") if tok.endswith(".") and not re.fullmatch(r"[A-Z]\.", tok) else tok)
                      for off, tok in tokens]
            tokens = [(off, tok) for off, tok in tokens if tok]
            if not tokens:
                continue
            if not all(_NAME_TOKEN_RE.match(tok) for _, tok in tokens):
                flags.append("unparsed")
                continue
            if not titled and len(tokens) >= 2 and all(_ALLCAPS_TOKEN_RE.match(tok) for _, tok in tokens):
                for off, tok in tokens:
                    names.append({"name": tok.upper(), "raw": tok, "start": base + off,
                                  "end": base + off + len(tok)})
                if "delimiter_repaired" not in flags:
                    flags.append("delimiter_repaired")
                continue
            off, tok = tokens[-1]
            names.append({"name": tok.upper(), "raw": tok, "start": base + off, "end": base + off + len(tok)})
    return names, flags


def surname(name_with_title: str | None) -> str | None:
    if not name_with_title:
        return None
    got, _ = split_names(name_with_title)
    return got[-1]["name"] if got else None


# ---------------------------------------------------------------------------------------------
# document structure

def is_transcript(ct: CanonicalText) -> bool:
    """A verbatim caption transcript (SPEAKER: text lines), not minutes."""
    lines = [ln for ln in ct.text.split("\n") if ln.strip()]
    speakers = [ln for ln in lines if _TRANSCRIPT_LINE_RE.match(ln) and not _LABEL_RE.match(ln)]
    return len(speakers) >= 5 and len(speakers) * 2 >= len(lines)


@dataclass
class _Heading:
    start: int
    level: str   # "top" | "sub"
    label: str
    title: str


_NOV_TOP_RE = re.compile(r"^[ \t]*(?P<l>[A-Z])\.[ \t]+(?P<t>\S[^\n]*)$", re.M)
_NOV_SUB_RE = re.compile(r"^[ \t]*(?P<l>[A-Z]\.\d+)\.?[ \t]+(?P<t>\S[^\n]*)$", re.M)
_BOS_TOP_RE = re.compile(r"^[ \t]*(?P<l>\d{1,2})\.(?:[ \t]+(?P<t>\S[^\n]*))?[ \t]*$", re.M)
_BOS_SUB_RE = re.compile(r"^[ \t]*(?P<l>C[AB]-\d+[a-z]?|[a-z]|[ivx]{1,4})\.(?:[ \t]+(?P<t>\S[^\n]*))?[ \t]*$", re.M)


def _headings(ct: CanonicalText, body: str) -> list[_Heading]:
    text = ct.text
    top_re, sub_re = (_NOV_TOP_RE, _NOV_SUB_RE) if body == "novato-city-council" else (_BOS_TOP_RE, _BOS_SUB_RE)
    out: list[_Heading] = []
    last_top = None

    def continues_sentence(pos: int, title: str | None) -> bool:
        """The line at pos carries on the previous line's sentence (no blank line between, that line
        ends mid-sentence, and the words after the label are lowercase): a wrapped "E.3 to April …"
        is motion text, not a heading."""
        if pos == 0 or not title or not title[:1].islower():
            return False
        prev_end = pos - 1
        prev_start = text.rfind("\n", 0, prev_end) + 1
        prev = text[prev_start:prev_end].rstrip()
        return bool(prev) and bool(re.search(r"[a-z,;]$", prev))

    for level, rx in (("top", top_re), ("sub", sub_re)):
        for m in rx.finditer(text):
            if continues_sentence(m.start(), m.group("t")):
                continue
            if level == "top":
                # top-level items only advance; a numbered or lettered list inside an item restarts
                key = int(m.group("l")) if m.group("l").isdigit() else ord(m.group("l"))
                if last_top is not None and key <= last_top:
                    continue
                last_top = key
            title = (m.group("t") or "").strip()
            if not title:  # "1." alone on its line: the title is the next non-empty line
                nxt = re.search(r"\n[ \t]*(\S[^\n]*)", text[m.end():])
                title = nxt.group(1).strip() if nxt else ""
            out.append(_Heading(m.start(), level, m.group("l"), title))
    out.sort(key=lambda h: (h.start, h.level != "top"))
    return out


def _item_at(headings: list[_Heading], pos: int) -> tuple[_Heading | None, _Heading | None]:
    top = sub = None
    for h in headings:
        if h.start > pos:
            break
        if h.level == "top":
            top, sub = h, None
        else:
            sub = h
    return top, sub


def _next_heading_after(headings: list[_Heading], pos: int, end: int) -> int:
    for h in headings:
        if h.start > pos:
            return h.start
    return end


def _region_end(headings: list[_Heading], pos: int, end: int, consent: bool) -> int:
    """A motion owns votes up to the next item: a consent motion up to the next top-level item
    (its roll call may follow the subitems it covers), any other up to the next heading."""
    return _next_top_after(headings, pos, end) if consent else _next_heading_after(headings, pos, end)


def _next_top_after(headings: list[_Heading], pos: int, end: int) -> int:
    for h in headings:
        if h.level == "top" and h.start > pos:
            return h.start
    return end


# ---------------------------------------------------------------------------------------------
# vote labels and blocks

def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    s = text.rfind("\n", 0, pos) + 1
    e = text.find("\n", pos)
    return s, (len(text) if e == -1 else e)


def _is_heading_line(line: str, body: str) -> bool:
    if body == "novato-city-council":
        return bool(_NOV_TOP_RE.match(line) or _NOV_SUB_RE.match(line))
    return bool(_BOS_TOP_RE.match(line) or _BOS_SUB_RE.match(line))


def _name_shaped(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if s.rstrip(".").upper() in _SENTINELS_ALL | {"NONE"}:
        return True
    names, flags = split_names(s)
    return bool(names) and "unparsed" not in flags


def _ends_with_delimiter(s: str) -> bool:
    return bool(re.search(r"(?:,|;|&|\band)\s*$", s.strip(), re.I))


def _labels(ct: CanonicalText, body: str) -> list[_Label]:
    text = ct.text
    found: list[_Label] = []
    for m in _LABEL_RE.finditer(text):
        cat = next(c for c in CATEGORIES if m.group(c) is not None)
        found.append(_Label(cat, m.start(), m.end()))
    for m in _TALLY_LINE_RE.finditer(text):
        lab = _Label("tally", m.start(), m.end())
        lab.value_end = m.end()
        lab.value = m.group(0)
        lab.outcome = "carried" if m.group("outcome").lower() in ("carried", "passed") else "failed"
        rest = m.group("rest")
        k = _KEYED_TALLY_RE.match(rest)
        if k:
            keyed = {}
            for km in re.finditer(r"(Abstain|Absent|Recused?|Noes?)\s*:\s*(\d+)", k.group(3) or "", re.I):
                key = {"abstain": "abstain", "absent": "absent", "recuse": "recused", "recused": "recused",
                       "no": "no", "noes": "no"}[km.group(1).lower()]
                keyed[key] = int(km.group(2))
            lab.tally = {"printed": rest.strip().rstrip("."), "a": int(k.group(1)), "n": int(k.group(2)),
                         "x": None, "keyed": keyed}
        else:
            lab.tally = {"printed": rest.strip(), "unrecognized": True}
        found.append(lab)
    for m in _VOTES_INTRO_RE.finditer(text):
        lab = _Label("intro", m.start() + len(m.group()) - len(m.group().lstrip()), m.end())
        lab.value_end = m.end()
        found.append(lab)
    found.sort(key=lambda lab: lab.start)
    # drop category labels that sit inside a tally line ("Abstain:1" after "Vote: Motion carried")
    tally_spans = [(lab.start, lab.value_end) for lab in found if lab.category == "tally"]
    found = [lab for lab in found
             if lab.category in ("tally", "intro") or not any(s <= lab.start < e for s, e in tally_spans)]

    for i, lab in enumerate(found):
        if lab.category in ("tally", "intro"):
            continue
        nxt = found[i + 1].start if i + 1 < len(found) else len(text)
        _read_value(text, lab, nxt, body)
    return found


def _read_value(text: str, lab: _Label, hard_end: int, body: str) -> None:
    """The value of a category label: the rest of its line up to the next label or a motion
    outcome; if that is empty or ends with a delimiter, continuation lines that are name-shaped
    (page-break noise skipped)."""
    pieces: list[tuple[int, int]] = []
    pos = lab.colon_end
    _, line_end = _line_bounds(text, pos)
    end = min(line_end, hard_end)
    term = _TERMINATOR_RE.search(text, pos, end)
    if term:
        end = term.start()
    pieces.append((pos, end))
    seg = text[pos:end]
    while (not seg.strip() or _ends_with_delimiter(seg)) and end < hard_end and not term:
        # look for the next non-noise line
        nxt_start = end + 1
        found = None
        while nxt_start < hard_end:
            ls, le = _line_bounds(text, nxt_start)
            line = text[ls:le]
            if not line.strip() or _PAGE_NOISE_RE.match(line):
                nxt_start = le + 1
                continue
            found = (ls, min(le, hard_end))
            break
        if not found:
            break
        ls, le = found
        cand = text[ls:le]
        t2 = _TERMINATOR_RE.search(text, ls, le)
        if t2:
            le = t2.start()
            cand = text[ls:le]
        if _is_heading_line(text[ls:_line_bounds(text, ls)[1]], body) or not _name_shaped(cand):
            break
        pieces.append((ls, le))
        seg = cand
        end = le
        if t2:
            break
    # assemble names from all pieces
    vstart = pieces[0][0]
    vend = pieces[-1][1]
    while vend > vstart and text[vend - 1].isspace():
        vend -= 1
    lab.value_end = vend
    lab.value = text[vstart:vend]
    joined_tokens = " ".join(text[s:e].strip() for s, e in pieces if text[s:e].strip())
    token = joined_tokens.strip().rstrip(".").strip().upper()
    if not token:
        # the label with nothing written after it: an empty category, recorded as such
        lab.sentinel = {"token": "BLANK", "category": lab.category, "start": lab.start, "end": lab.colon_end}
        return
    if token in _SENTINELS_ALL or token == "NONE":
        # sentinel span: the sentinel word itself
        for s, e in pieces:
            m = re.search(r"\b(ALL|UNANIMOUS|NONE)\b\.?", text[s:e], re.I)
            if m:
                lab.sentinel = {"token": m.group(1).upper(), "category": lab.category,
                                "start": s + m.start(1), "end": s + m.end(1)}
                break
        return
    for s, e in pieces:
        names, flags = split_names(text[s:e])
        for n in names:
            lab.names.append({"name": n["name"], "raw": n["raw"], "start": s + n["start"], "end": s + n["end"]})
        for f in flags:
            if f == "unparsed":
                lab.unparsed = True
            elif f not in lab.flags:
                lab.flags.append(f)
    if not lab.names and not lab.unparsed:
        lab.unparsed = True


def _blocks(text: str, labels: list[_Label]) -> list[list[_Label]]:
    """Consecutive labels with only whitespace / page-break noise between one value's end and the
    next label form one block; a block must carry an aye or no category or a Vote: tally line."""
    blocks: list[list[_Label]] = []
    cur: list[_Label] = []
    prev_end = None
    for lab in labels:
        if cur and prev_end is not None:
            gap = text[prev_end:lab.start]
            if any(ln.strip() and not _PAGE_NOISE_RE.match(ln) for ln in gap.split("\n")):
                blocks.append(cur)
                cur = []
        cur.append(lab)
        prev_end = lab.value_end
    if cur:
        blocks.append(cur)
    return [b for b in blocks if any(lab.category in ("aye", "no", "tally") for lab in b)]


# ---------------------------------------------------------------------------------------------
# motions

@dataclass
class _Motion:
    start: int
    clause_end: int      # end of the mover/seconder/tally clause (motion text starts after)
    region_end: int = 0
    kind: str = "main"
    mover: str | None = None
    seconder: str | None = None
    tally: dict | None = None
    acting_as: str | None = None
    on_behalf_of: str | None = None
    restates: "_Motion | None" = None
    restatement: "_Motion | None" = None
    extra_spans: list = field(default_factory=list)
    outcome: str | None = None
    text_start: int = 0
    blocks: list = field(default_factory=list)


def _collapsed(text: str, start: int, end: int) -> str:
    return re.sub(r"\s+", " ", text[start:end])


def _map_collapsed(text: str, start: int, end: int, cpos: int) -> int:
    """Offset in text of position cpos in the whitespace-collapsed text[start:end]."""
    out = 0
    i = start
    prev_space = False
    while i < end:
        ch = text[i]
        is_space = ch.isspace()
        if is_space and prev_space:
            i += 1
            continue
        if out == cpos:
            return i
        out += 1
        prev_space = is_space
        i += 1
    return end


_ITEM_ID = r"(?:C[AB]-\d+[a-z]?|[A-Z]\.\d+)"
_GROUPED_RE = re.compile(rf"consent\s+(?:calendar|agenda)|\bconsent\s+[AB]\b"
                         rf"|\bitems?\s+{_ITEM_ID}\.?\s*(?:through|to|-|and|&|,)\s*(?:items?\s+)?{_ITEM_ID}", re.I)


def _own_sentence(text: str, headings: list[_Heading], start: int, limit: int) -> str:
    """The motion's own words for grouped-motion evidence: from the motion to its first sentence
    end, never past the next heading or `limit`."""
    end = min(limit, _next_heading_after(headings, start, len(text)))
    col = _collapsed(text, start, end)
    m = _SENTENCE_END_RE.search(col)
    return col[: m.end()] if m else col


def _looks_consent(headings: list[_Heading], pos: int, lead: str) -> bool:
    """Grouped-motion evidence is the motion's own wording ("approve the Consent Calendar …");
    a section title alone never lets an individual motion cross its subitem."""
    return bool(_GROUPED_RE.search(lead))


def _novato_motions(ct: CanonicalText, headings: list[_Heading]) -> list[_Motion]:
    text = ct.text
    heads = list(_NOV_HEADER_RE.finditer(text))
    motions: list[_Motion] = []
    for i, h in enumerate(heads):
        nxt = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        lead = _own_sentence(text, headings, h.end(), min(nxt, h.end() + 1500))
        region_end = min(nxt, _region_end(headings, h.start(), len(text), _looks_consent(headings, h.start(), lead)))
        first_label = _LABEL_RE.search(text, h.end(), region_end)
        before_block = first_label.start() if first_label else region_end
        window_end = min(before_block, h.end() + 1500)
        col = _collapsed(text, h.end(), window_end)
        mo = _Motion(h.start(), h.end(), region_end)
        hdr = h.group("hdr")
        who = (h.group("who") or "").strip()
        if who and who not in ("COUNCIL", "COUCNIL", "SEPARATE"):
            mo.acting_as = who

        def at(cpos: int) -> int:
            return _map_collapsed(text, h.end(), window_end, cpos)

        ms = _NOV_MOVER_SECONDER_RE.search(col)
        rs = _NOV_RESTATED_RE.search(col)
        clause_c_end = 0
        if rs and rs.start() < 80:
            mo.mover = surname(rs.group("m"))
            mo.kind = "restated"
            clause_c_end = rs.end()
            later = _NOV_SECONDED_LATER_RE.search(col, clause_c_end)
            if later:
                mo.seconder = surname(later.group("s"))
                mo.extra_spans.append((at(later.start()), at(later.end())))
        elif ms and ms.start() < 80:
            mo.mover, mo.seconder = surname(ms.group("m")), surname(ms.group("s"))
            clause_c_end = ms.end()
        else:
            mm = _NOV_MOVER_ONLY_RE.search(col)
            if mm and mm.start() < 80:
                mo.mover = surname(mm.group("m") or mm.group("m2"))
                clause_c_end = mm.end()
        # a printed tally belongs to this motion only if it sits in the motion's own sentence, or in
        # the sentence that runs straight into this motion's vote block
        first_end = _SENTENCE_END_RE.search(col, clause_c_end)
        first_end_pos = first_end.end() if first_end else len(col)

        def owned(m) -> bool:
            if m is None:
                return False
            if m.start() < first_end_pos:
                return True
            if first_label is None:
                return False
            nxt_end = _SENTENCE_END_RE.search(col, m.end())
            return nxt_end is None or not col[nxt_end.end():].strip()

        t = _NOV_TALLY_RE.search(col, clause_c_end)
        anyt = _NOV_TALLY_ANY_RE.search(col, clause_c_end)
        t = t if owned(t) else None
        anyt = anyt if owned(anyt) else None
        if t:
            mo.tally = {"printed": "-".join(x for x in (t.group("a"), t.group("n"), t.group("x")) if x),
                        "a": int(t.group("a")), "n": int(t.group("n")),
                        "x": int(t.group("x")) if t.group("x") else None, "keyed": {}}
            mo.extra_spans.append((at(t.start()), at(t.end())))
            if t.start() - clause_c_end < 40 and t.start() < first_end_pos and mo.kind != "restated":
                clause_c_end = t.end()
        elif anyt:
            mo.tally = {"printed": _collapsed(text, at(anyt.start()), min(window_end, at(anyt.start()) + 40)).strip(),
                        "unrecognized": True}
            mo.extra_spans.append((at(anyt.start()), at(anyt.end())))
        if mo.kind == "restated":
            pass
        elif "SUBSTITUTE" in hdr or re.search(r"substitute\s+motion", col[:clause_c_end or 120], re.I):
            mo.kind = "substitute"
        elif re.search(r"\bamendment\s+(?:was\s+)?(?:made\s+)?by\b", col[:clause_c_end or 120], re.I):
            mo.kind = "amendment"
        ns = _NO_SECOND_RE.search(col[: max(clause_c_end, 0) + 200])
        if ns and not mo.seconder and not mo.tally:
            mo.kind = "failed_no_second"
            mo.outcome = "failed"
            # the sentence that says so is the outcome evidence
            sent_start = col.rfind(".", 0, ns.start()) + 1
            sent_end = _SENTENCE_END_RE.search(col, ns.end())
            mo.extra_spans.append((at(sent_start + (1 if col[sent_start:sent_start + 1] == " " else 0)),
                                   at(sent_end.end() if sent_end else ns.end())))
        mo.clause_end = at(clause_c_end) if clause_c_end else h.end()
        lead_m = re.match(r"[\s,]*(?:to\s+)?", text[mo.clause_end:region_end])
        mo.text_start = mo.clause_end + (lead_m.end() if lead_m else 0)
        motions.append(mo)
    return motions


def _bos_motions(ct: CanonicalText, headings: list[_Heading]) -> list[_Motion]:
    text = ct.text
    found: list[_Motion] = []
    for m in _BOS_MS_RE.finditer(text):
        mo = _Motion(m.start(), m.end())
        mo.mover, mo.seconder = surname(m.group("m")), surname(m.group("s"))
        mo.on_behalf_of = surname(m.group("b"))
        mo.text_start = m.end()
        found.append(mo)
    for m in _BOS_MOVED_RE.finditer(text):
        if any(f.start <= m.start() < f.clause_end for f in found):
            continue
        mo = _Motion(m.start(), m.end())
        mo.mover, mo.seconder = surname(m.group("m")), surname(m.group("s"))
        mo.text_start = m.start("text")
        mo._moved_text_end = m.start("text") + len(m.group("text"))  # type: ignore[attr-defined]
        found.append(mo)
    found.sort(key=lambda mo: mo.start)
    for i, mo in enumerate(found):
        nxt = found[i + 1].start if i + 1 < len(found) else len(text)
        lead = _own_sentence(text, headings, mo.start, min(nxt, mo.start + 1500))
        mo.region_end = min(nxt, _region_end(headings, mo.start, len(text), _looks_consent(headings, mo.start, lead)))
        lead = lead.lower()
        if "substitute motion" in lead:
            mo.kind = "substitute"
    return found


def _motion_text(text: str, mo: _Motion, stop: int, body: str) -> tuple[str, int]:
    """The motion's own words and where they end in the text: the first sentence after the
    mover clause (abbreviations like "No." do not end it), never past `stop`; for the Board, never
    past the end of the motion's paragraph."""
    if hasattr(mo, "_moved_text_end"):
        e = mo._moved_text_end  # type: ignore[attr-defined]
        return re.sub(r"\s+", " ", text[mo.text_start:e]).strip(), e
    end = stop
    if body != "novato-city-council":
        pos = mo.text_start
        _, le = _line_bounds(text, pos)
        end = min(le, stop)
        while end < stop:
            nls, nle = _line_bounds(text, end + 1)
            line = text[nls:nle]
            if (not line.strip() or not line[:1].isspace() or _LABEL_RE.match(line.strip())
                    or _TALLY_LINE_RE.match(line.strip()) or _is_heading_line(line, body)):
                break
            end = min(nle, stop)
    m = _SENTENCE_END_RE.search(text, mo.text_start, end)
    if m:
        end = m.end()
    while end > mo.text_start and text[end - 1].isspace():
        end -= 1
    return re.sub(r"\s+", " ", text[mo.text_start:end]).strip(), end


def _amendment(text: str) -> bool:
    return bool(re.match(r"amend\b", text, re.I) or re.search(r"\bamend\s+the\s+(?:main\s+)?motion\b", text, re.I))


# ---------------------------------------------------------------------------------------------

def _loc(ct: CanonicalText, start: int, end: int) -> dict:
    return ct.locate(start, end)


def _scope_before(text: str, pos: int) -> tuple[list[str], tuple[int, int]] | None:
    """A group scope like '(G.1 and G.4)' on the last non-empty line before pos."""
    ls, _ = _line_bounds(text, pos)
    cur = ls - 1
    while cur > 0:
        ps, pe = _line_bounds(text, cur - 1 if text[cur] == "\n" else cur)
        line = text[ps:pe]
        if line.strip():
            if _SCOPE_RE.match(line):
                return re.findall(r"[A-Z]\.\d+", line), (ps + len(line) - len(line.lstrip()), pe)
            return None
        cur = ps - 1
    return None


def parse_document(ct: CanonicalText, *, body: str, meeting_id: str, doc_sha256: str) -> list[dict]:
    if is_transcript(ct):
        return []
    text = ct.text
    headings = _headings(ct, body)
    labels = _labels(ct, body)
    blocks = _blocks(text, labels)
    motions = (_novato_motions if body == "novato-city-council" else _bos_motions)(ct, headings)

    # assign blocks to motions
    orphans: list[list[_Label]] = []
    for blk in blocks:
        bstart = blk[0].start
        owner = None
        for mo in motions:
            if mo.start < bstart < mo.region_end and bstart >= mo.clause_end:
                owner = mo
        if owner is None:
            orphans.append(blk)
            continue
        scope = _scope_before(text, bstart)
        if not owner.blocks:
            owner.blocks.append((blk, scope))
        elif scope and owner.blocks[0][1]:
            owner.blocks.append((blk, scope))
        else:
            orphans.append(blk)

    # a restatement of the pending motion (same mover and seconder, "restated" between them) is the
    # same motion: the vote belongs to the restated wording and the first wording is folded into it
    folded: set[int] = set()
    for i, first in enumerate(motions):
        if first.blocks or first.kind == "failed_no_second":
            continue
        for later in motions[i + 1:]:
            same_item = _item_at(headings, first.start)[0] is _item_at(headings, later.start)[0]
            if not same_item:
                break
            if (later.blocks and later.mover == first.mover and later.seconder == first.seconder
                    and re.search(r"restat", text[first.clause_end:later.start], re.I)):
                later.restates = first
                later.kind = "restated"
                folded.add(id(first))
                break
    motions = [mo for mo in motions if id(mo) not in folded]

    # a second roll call on the same motion after it was restated: identical → the same vote, kept
    # as evidence on the first event; different → a revote, its own event marked restated
    def signature(blk):
        return tuple((lab.category, tuple(sorted(n["name"] for n in lab.names)),
                      lab.sentinel["token"] if lab.sentinel else None)
                     for lab in blk if lab.category in CATEGORIES)

    kept: list[_Motion] = []
    for mo in motions:
        prev = kept[-1] if kept else None
        if (prev and prev.blocks and mo.blocks and len(prev.blocks) == 1 and len(mo.blocks) == 1
                and prev.mover == mo.mover and prev.seconder == mo.seconder
                and _item_at(headings, prev.start)[0] is _item_at(headings, mo.start)[0]
                and re.search(r"restat", text[prev.blocks[0][0][-1].value_end:mo.start], re.I)):
            if signature(prev.blocks[0][0]) == signature(mo.blocks[0][0]):
                prev.restatement = mo
                continue
            mo.kind = "restated"
        kept.append(mo)
    motions = kept

    # where each motion's prose exceptions may start: after the previous motion's vote (or motion)
    ends = sorted([b[-1].value_end for b in blocks] + [mo.clause_end for mo in motions if not mo.blocks])
    suffix = meeting_id.removeprefix("meeting-")
    events: list[dict] = []

    def exc_start(pos: int) -> int:
        prior = [e for e in ends if e <= pos]
        return prior[-1] if prior else 0

    for mo in motions:
        if not mo.blocks:
            events.append(_event(ct, body, meeting_id, doc_sha256, headings, mo, None, None, suffix,
                                 multi=False, exc_from=exc_start(mo.start)))
        for blk, scope in mo.blocks:
            events.append(_event(ct, body, meeting_id, doc_sha256, headings, mo, blk, scope, suffix,
                                 multi=len(mo.blocks) > 1, exc_from=exc_start(mo.start)))
    for blk in orphans:
        events.append(_event(ct, body, meeting_id, doc_sha256, headings, None, blk,
                             _scope_before(text, blk[0].start), suffix, multi=False,
                             exc_from=exc_start(blk[0].start)))
    events.sort(key=lambda e: (e["_order"], e["event_id"]))
    for i, e in enumerate(events):
        m = e["motion"]
        if m and m["kind"] == "restated" and "restates_span" not in m:
            prior = [p for p in events[:i] if p["motion"] and p["motion"]["mover"] == m["mover"]
                     and p["item"]["top"] == e["item"]["top"]]
            m["restates"] = prior[-1]["event_id"] if prior else None
    seen = set()
    for e in events:
        if e["event_id"] in seen:
            raise ValueError(f"duplicate event id {e['event_id']}")
        seen.add(e["event_id"])
        del e["_order"]
    return events


def _event(ct, body, meeting_id, doc_sha256, headings, mo: _Motion | None, blk, scope, suffix, *, multi,
           exc_from=0):
    text = ct.text
    hold: list[str] = []
    flags: list[str] = []
    categories: dict[str, list] = {c: [] for c in CATEGORIES}
    category_spans: dict[str, dict] = {}
    sentinels: list[dict] = []
    consumed: list[dict] = []
    tally = mo.tally if mo else None
    outcome = mo.outcome if mo else None
    block_loc = None
    restatement = None

    anchor = mo.start if mo else blk[0].start
    top, sub = _item_at(headings, anchor)

    if mo:
        stop = blk[0].start if blk else mo.region_end
        if blk and scope:
            stop = min(stop, scope[1][0])
        consumed.append(_loc(ct, mo.start, max(mo.clause_end, mo.start)))
        mtext, mtext_end = _motion_text(text, mo, stop, body)
        if mtext:
            consumed.append(_loc(ct, mo.text_start, mtext_end))
        for es, ee in mo.extra_spans:
            if ee > es:
                consumed.append(_loc(ct, es, ee))
        if mo.kind == "failed_no_second":
            mtext = re.split(r"\.\s+(?:The\s+motion|There\s+was)", mtext)[0]
        kind = mo.kind
        if kind == "main" and _amendment(mtext):
            kind = "amendment"
        motion = {"kind": kind, "text": mtext, "mover": mo.mover, "seconder": mo.seconder,
                  "span": _loc(ct, mo.start, max(mo.clause_end, mo.text_start)),
                  "group_of": f"L{ct.line_of(mo.start)}" if multi else None}
        if mo.acting_as:
            motion["acting_as"] = mo.acting_as
        if mo.on_behalf_of:
            motion["on_behalf_of"] = mo.on_behalf_of
        if mo.restatement is not None:
            r = mo.restatement
            rblk = r.blocks[0][0]
            motion_end = max(r.clause_end, r.text_start)
            restatement = {"motion_span": _loc(ct, r.start, motion_end),
                           "block": _loc(ct, rblk[0].start, rblk[-1].value_end)}
            consumed.append(restatement["motion_span"])
            for es, ee in r.extra_spans:
                if ee > es:
                    consumed.append(_loc(ct, es, ee))
            for lab in rblk:
                consumed.append(_loc(ct, lab.start, lab.value_end))
            om = _OUTCOME_LINE_RE.match(text, rblk[-1].value_end + (len(text[rblk[-1].value_end:])
                                                                     - len(text[rblk[-1].value_end:].lstrip())))
            if om:
                consumed.append(_loc(ct, om.start() + len(om.group(0)) - len(om.group(0).lstrip()), om.end()))
        if mo.restates is not None:
            motion["restates_span"] = _loc(ct, mo.restates.start, mo.restates.clause_end)
            consumed.append(_loc(ct, mo.restates.start, mo.restates.clause_end))
    else:
        motion = None
        hold.append("vote_without_motion")

    if blk:
        seen_cats: set[str] = set()
        bstart = blk[0].start
        bend = blk[-1].value_end
        for lab in blk:
            if lab.category == "intro":
                consumed.append(_loc(ct, lab.start, lab.value_end))
                continue
            if lab.category == "tally":
                consumed.append(_loc(ct, lab.start, lab.value_end))
                if lab.tally.get("unrecognized"):
                    hold.append("tally_unrecognized")
                tally = dict(lab.tally)
                outcome = lab.outcome
                continue
            if lab.category in seen_cats:
                hold.append("duplicate_category")
            seen_cats.add(lab.category)
            category_spans[lab.category] = _loc(ct, lab.start, lab.value_end)
            consumed.append(_loc(ct, lab.start, lab.value_end))
            if lab.unparsed:
                hold.append("unparsed_block")
            if lab.sentinel:
                tok = lab.sentinel["token"]
                sentinels.append({"token": tok, "category": lab.category,
                                  "span": _loc(ct, lab.sentinel["start"], lab.sentinel["end"])})
                if tok in _SENTINELS_ALL and lab.category != "aye":
                    hold.append("unparsed_block")
            for n in lab.names:
                categories[lab.category].append({"name": n["name"], "raw": n["raw"],
                                                 "span": _loc(ct, n["start"], n["end"])})
            for f in lab.flags:
                if f not in flags:
                    flags.append(f)
        # outcome line right after the block
        after = text[bend:]
        m = re.match(r"(?:[ \t]*\n)*", after)
        ol = _OUTCOME_LINE_RE.match(after, m.end() if m else 0)
        inline = _TERMINATOR_RE.match(after.lstrip(" \t"))
        if ol and (not mo or bend + ol.start() < mo.region_end):
            o = ol.group("o").lower()
            outcome = "carried" if o in ("carried", "passed") else "failed"
            s = bend + ol.start() + (len(ol.group(0)) - len(ol.group(0).lstrip()))
            consumed.append(_loc(ct, s, bend + ol.end()))
            bend = bend + ol.end()
        elif inline:
            off = len(after) - len(after.lstrip(" \t"))
            o = re.search(r"carried|failed|passed", inline.group(0), re.I).group(0).lower()
            outcome = "carried" if o in ("carried", "passed") else "failed"
            consumed.append(_loc(ct, bend + off, bend + off + inline.end()))
            bend = bend + off + inline.end()
        block_loc = _loc(ct, bstart, bend)
        if scope:
            consumed.append(_loc(ct, scope[1][0], scope[1][1]))
        # "Thereafter, the vote on the pending motion was" right before the block
        ls, _ = _line_bounds(text, bstart)
        prev = text[max(0, ls - 200):ls].rstrip()
        lm = _LEADIN_RE.search(prev)
        if lm:
            base = max(0, ls - 200)
            consumed.append(_loc(ct, base + lm.start(), base + lm.end()))

        # a member in two categories
        where: dict[str, str] = {}
        for c in CATEGORIES:
            for n in categories[c]:
                if n["name"] in where and where[n["name"]] != c:
                    hold.append("name_in_two_categories")
                where[n["name"]] = c
    elif mo and mo.kind != "failed_no_second":
        hold.append("no_vote_recorded")

    if outcome is None:
        outcome = "not_printed"

    has_all = any(s["token"] in _SENTINELS_ALL for s in sentinels)
    # printed tally vs named counts
    if tally and tally.get("unrecognized"):
        tally = {"printed": tally["printed"], "unrecognized": True}
        hold.append("tally_unrecognized")
    if blk and tally and not tally.get("unrecognized"):
        if multi:
            hold.append("tally_scope_ambiguous")
        elif not has_all:
            if tally["a"] != len(categories["aye"]) or tally["n"] != len(categories["no"]):
                hold.append("tally_mismatch")
            if tally.get("x") is not None and tally["x"] != (len(categories["abstain"]) + len(categories["recused"])
                                                            + len(categories["absent"])):
                hold.append("tally_mismatch")
            for key, count in (tally.get("keyed") or {}).items():
                if count != len(categories[key]):
                    hold.append("tally_mismatch")

    # prose exceptions inside the item region
    item_exceptions = []
    region_start = max((sub or top).start if (sub or top) else 0, exc_from)
    region_end = block_loc["end"] if block_loc else (mo.region_end if mo else anchor)
    for m in _EXCEPTION_RE.finditer(text, region_start, region_end):
        if any(c["start"] <= m.start() < c["end"] for c in category_spans.values()):
            continue
        kind = {"recused": "recused", "abstained": "abstain"}.get(m.group("v").split()[0].lower(), "recused")
        name = m.group("n").upper()
        item_exceptions.append({"name": name, "kind": kind, "span": _loc(ct, m.start(), m.end())})
        listed = next((c for c in CATEGORIES for n in categories[c] if n["name"] == name), None)
        if blk and not has_all and listed != kind and not (kind == "recused" and listed == "absent"):
            hold.append("exception_scope_conflict")

    consent = bool(motion and _GROUPED_RE.search(motion["text"]))
    item = {"top": top.label if top else None, "sub": None if consent else (sub.label if sub else None),
            "title": ((sub if (sub and not consent) else top).title if (sub or top) else None),
            "scope": scope[0] if scope else None}

    status = "held" if hold else ("needs_attendance" if has_all else "named")
    line_anchor = mo.start if (mo and not multi) else (blk[0].start if blk else anchor)
    if blk and scope and multi:
        line_anchor = scope[1][0]
    event_id = f"vev-{suffix}-{doc_sha256[:8]}-L{ct.line_of(line_anchor)}"
    return {
        "event_id": event_id,
        "body": body,
        "meeting_id": meeting_id,
        "doc_sha256": doc_sha256,
        "text_sha256": ct.sha256,
        "item": item,
        "consent": consent,
        "motion": motion,
        "outcome": outcome,
        "tally": tally,
        "categories": categories,
        "category_spans": category_spans,
        "sentinels": sentinels,
        "item_exceptions": item_exceptions,
        "restatement": restatement,
        "block": block_loc,
        "consumed": sorted(consumed, key=lambda c: (c["start"], c["end"])),
        "flags": flags,
        "status": status,
        "hold_reasons": sorted(set(hold)),
        "_order": blk[0].start if blk else anchor,
    }
