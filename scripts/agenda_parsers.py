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

import subprocess
from dataclasses import dataclass
from typing import Callable

PDFTOTEXT_TIMEOUT = 60


class Unparseable(ValueError):
    """The text is not an agenda this parser can read; the meeting holds with the reason."""


@dataclass(frozen=True)
class Parser:
    version: int
    parse: Callable[[str], dict]


PARSERS: dict[str, Parser] = {}


def extract_text(data: bytes) -> str:
    """A PDF's text, laid out as printed (pdftotext -layout)."""
    result = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data, capture_output=True,
                            timeout=PDFTOTEXT_TIMEOUT)
    if result.returncode != 0:
        raise Unparseable(f"pdftotext exited {result.returncode}: {result.stderr.decode(errors='replace')[:200]}")
    return result.stdout.decode("utf-8", errors="replace")
