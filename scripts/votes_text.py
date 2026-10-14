#!/usr/bin/env python3
"""Votes Part A: the canonical text of a minutes document.

Every span the vote ledger records — vote blocks, category values, attendance statements,
candidate matches — is a character offset into this text, so it is defined once here:

- PDF: `pdftotext -layout` lines, right-stripped; a form feed becomes its own "\\f" line.
- HTML: script/style/head content dropped; a table row is ONE line (its cells joined by a space,
  so a label cell and its value cell read "AYES: Supervisor …"); outside rows, block tags break
  lines; whitespace collapsed; empty lines dropped.
- DOCX: one line per paragraph (tabs → space, breaks → newline), a table row is one line.
- All: curly quotes and en/em dashes fold to ASCII, NBSP to space.

text_sha256 pins the canonicalizer: a change here changes every locator, on purpose.
"""

from __future__ import annotations

import bisect
import hashlib
import io
import re
import subprocess
import zipfile
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                       "–": "-", "—": "-", " ": " "})


@dataclass(frozen=True)
class CanonicalText:
    text: str
    _line_starts: tuple[int, ...] = field(repr=False)

    @classmethod
    def from_lines(cls, lines: list[str]) -> "CanonicalText":
        text = "\n".join(lines).translate(_FOLD)
        starts = [0] + [m.end() for m in re.finditer("\n", text)]
        return cls(text, tuple(starts))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def line_of(self, offset: int) -> int:
        """1-based line number holding `offset`."""
        return bisect.bisect_right(self._line_starts, offset)

    def locate(self, start: int, end: int) -> dict:
        return {"start": start, "end": end, "line_start": self.line_of(start),
                "line_end": self.line_of(max(start, end - 1))}

    def line_span(self, line_no: int) -> tuple[int, int]:
        start = self._line_starts[line_no - 1]
        nxt = self._line_starts[line_no] - 1 if line_no < len(self._line_starts) else len(self.text)
        return start, nxt


def pdf_lines(layout_text: str) -> list[str]:
    out: list[str] = []
    for line in layout_text.replace("\r\n", "\n").split("\n"):
        while "\f" in line:
            before, _, line = line.partition("\f")
            if before.strip():
                out.append(before.rstrip())
            out.append("\f")
        out.append(line.rstrip())
    while out and out[-1] == "":
        out.pop()
    return out


_BLOCK = {"p", "div", "br", "blockquote", "table", "tbody", "li", "ul", "ol", "h1", "h2", "h3", "h4",
          "h5", "h6", "hr"}
_SKIP = {"script", "style", "head", "title"}


class _HtmlLines(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.skip = 0
        self.tr = 0

    def _flush(self):
        line = re.sub(r"\s+", " ", "".join(self.buf).replace(" ", " ")).strip()
        if line:
            self.lines.append(line)
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif tag == "tr":
            if self.tr == 0:
                self._flush()
            self.tr += 1
        elif tag == "td":
            self.buf.append(" ")
        elif tag in _BLOCK:
            if self.tr:
                self.buf.append(" ")
            else:
                self._flush()

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "tr":
            self.tr = max(0, self.tr - 1)
            if self.tr == 0:
                self._flush()
        elif tag == "td":
            self.buf.append(" ")
        elif tag in _BLOCK:
            if self.tr:
                self.buf.append(" ")
            else:
                self._flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)

    def close(self):
        super().close()
        self._flush()


def html_lines(html: str) -> list[str]:
    p = _HtmlLines()
    p.feed(html)
    p.close()
    return [unescape(x) if "&" in x else x for x in p.lines]


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_lines(data: bytes) -> list[str]:
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))

    def para_text(p) -> str:
        parts: list[str] = []
        for el in p.iter():
            if el.tag == _W + "t":
                parts.append(el.text or "")
            elif el.tag == _W + "tab":
                parts.append(" ")
            elif el.tag in (_W + "br", _W + "cr"):
                parts.append("\n")
        return "".join(parts)

    lines: list[str] = []
    body = root.find(_W + "body")
    for child in list(body if body is not None else []):
        if child.tag == _W + "p":
            lines.extend(para_text(child).split("\n"))
        elif child.tag == _W + "tbl":
            for tr in child.iter(_W + "tr"):
                cells = [" ".join(para_text(p).replace("\n", " ") for p in tc.iter(_W + "p")).strip()
                         for tc in tr.findall(_W + "tc")]
                lines.append(re.sub(r"\s+", " ", " ".join(c for c in cells if c)).strip())
    return [line.rstrip() for line in lines]


def canonical_text(path: Path, fmt: str) -> CanonicalText:
    path = Path(path)
    if fmt == "pdf":
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, timeout=300)
        if out.returncode != 0:
            raise RuntimeError(f"pdftotext failed for {path}: {out.stderr[:200]!r}")
        return CanonicalText.from_lines(pdf_lines(out.stdout.decode("utf-8", "replace")))
    if fmt == "html":
        return CanonicalText.from_lines(html_lines(path.read_bytes().decode("utf-8", "replace")))
    if fmt == "docx":
        return CanonicalText.from_lines(docx_lines(path.read_bytes()))
    raise ValueError(f"unsupported document format {fmt!r}")
