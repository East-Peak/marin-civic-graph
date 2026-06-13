"""form700_schedule_parsers.py — pure FPPC Form 700 schedule parsers (M4).

The e-filed Form 700 prints a fixed two-column ("2-up") template per schedule
page: a left entry and a right entry side by side. `pdftotext -layout` keeps the
columns aligned with whitespace but interleaves them on shared physical lines,
so we extract each column independently with a pdftotext crop box (US Letter is
612pt wide → left = x[0,306), right = x[306,612)). Document order is row-major:
within each page, left cell then right cell, top band to bottom; empty cells
consume no ordinal. pdftotext is the only process boundary — no OCR.

Each parser returns a list of parsed-line dicts in document order. A line dict
carries the EconomicInterest node fields (schedule / interest_type /
counterparty_name_raw / amount_band? / amount? / position? / is_spouse) plus an
`envelope` dict of auxiliary verbatim fields (acquired/disposed dates, nature,
description) that the node shape does not carry but the extraction envelope
preserves. Ethics stripping (addresses/APNs → city only; tenant non-extraction)
is applied in the Schedule B / A-2 part-4 / C-loan parsers.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

# US Letter geometry (points == pixels at pdftotext's default 72 dpi).
_PAGE_W = 612
_HALF_W = 306
_PAGE_H = 792

# A checked FPPC band: an "X" immediately before a band literal. Bands are
# either a "$lo - $hi" range or the open-ended "Over $n".
# Bands print mixed case: FMV uses "Over $1,000,000" (title), Sch C gross-income
# and loan highest-balance use "OVER $100,000" (upper). The capture preserves
# whatever case matched so the verbatim band string is kept.
_BAND = r"\$[\d,]+\s*-\s*\$[\d,]+|(?i:over)\s+\$[\d,]+|(?i:under)\s+\$[\d,]+"
_CHECKED_BAND_RE = re.compile(rf"X\s+({_BAND})")
_DATE_RE = re.compile(r"(\d{2})\s*/\s*(\d{2})\s*/\s*(\d{2})")


def _crop_text(pdf_path: Path, page: int, x: int, width: int) -> str:
    """Extract one page region as `-layout` text via a pdftotext crop box."""
    result = subprocess.run(
        ["pdftotext", "-layout", "-f", str(page), "-l", str(page),
         "-x", str(x), "-y", "0", "-W", str(width), "-H", str(_PAGE_H),
         str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def column_text(pdf_path: Path, page: int, side: str) -> str:
    """`-layout` text for the left half, right half, or full page width."""
    if side == "left":
        return _crop_text(pdf_path, page, 0, _HALF_W)
    if side == "right":
        return _crop_text(pdf_path, page, _HALF_W, _HALF_W)
    if side == "full":
        return _crop_text(pdf_path, page, 0, _PAGE_W)
    raise ValueError(f"unknown side {side!r}")


# Page-header schedule tag is UPPERCASE "SCHEDULE A-1"; the cover §4 summary uses
# title-case "Schedule A-1", so a case-sensitive match avoids the cover lines.
_SCHEDULE_HEADER_RE = re.compile(r"\bSCHEDULE\s+(A-1|A-2|B|C|D|E)\b")


def find_schedule_pages(pdf_path: Path) -> dict[str, list[int]]:
    """Map each schedule tag → its 1-based page numbers, in document order.

    One pdftotext pass over the whole doc; pages are split on the form-feed
    pdftotext emits between pages.
    """
    full = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    pages = full.split("\f")
    out: dict[str, list[int]] = {}
    for idx, page_text in enumerate(pages, start=1):
        m = _SCHEDULE_HEADER_RE.search(page_text)
        if m:
            out.setdefault(m.group(1), []).append(idx)
    return out


def _entry_blocks(text: str, marker: str) -> list[str]:
    """Split a column's text into per-entry blocks on `marker`, dropping the
    pre-first-marker page header. Each block is the text of one template cell."""
    parts = text.split(marker)
    return parts[1:]  # parts[0] is the header above the first cell


def _checked_band(section: str) -> str | None:
    """Return the X-checked band literal in `section`, whitespace-normalized."""
    m = _CHECKED_BAND_RE.search(section)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _slice_between(lines: list[str], start_label: str, end_label: str) -> str:
    """Join the lines strictly between the first `start_label` line and the next
    `end_label` line (exclusive). Empty string if the bounds aren't found."""
    start = end = None
    for i, ln in enumerate(lines):
        if start is None and start_label in ln:
            start = i
        elif start is not None and end_label in ln:
            end = i
            break
    if start is None:
        return ""
    return "\n".join(lines[start + 1: end if end is not None else len(lines)])


def _first_value_before(lines: list[str], label: str) -> str | None:
    """First non-empty stripped line occurring before the `label` line. Used to
    pull a free-text value (business-entity name) that sits above its caption."""
    for ln in lines:
        if label in ln:
            break
        stripped = ln.strip()
        if stripped:
            return stripped
    return None


def _interleave_row_major(left_blocks: list[str], right_blocks: list[str]) -> list[str]:
    """Yield blocks in document order: left cell then right cell, per row band."""
    out: list[str] = []
    for i in range(max(len(left_blocks), len(right_blocks))):
        if i < len(left_blocks):
            out.append(left_blocks[i])
        if i < len(right_blocks):
            out.append(right_blocks[i])
    return out


def _acquired_disposed(block_lines: list[str]) -> dict[str, str]:
    """Pull acquired/disposed dates (envelope-only) from an A-1/A-2 cell."""
    env: dict[str, str] = {}
    section = _slice_between(block_lines, "IF APPLICABLE, LIST DATE", "ACQUIRED")
    dates = _DATE_RE.findall(section)
    if dates:
        env["acquired"] = "/".join(dates[0])
    if len(dates) > 1:
        env["disposed"] = "/".join(dates[1])
    return env


def _parse_a1_block(block: str) -> dict[str, Any] | None:
    """Parse one Schedule A-1 cell → an `investment` line, or None if empty."""
    lines = block.splitlines()
    name = _first_value_before(lines, "GENERAL DESCRIPTION OF THIS BUSINESS")
    if not name:
        return None
    fmv = _slice_between(lines, "FAIR MARKET VALUE", "NATURE OF INVESTMENT")
    band = _checked_band(fmv)
    return {
        "schedule": "A-1",
        "interest_type": "investment",
        "counterparty_name_raw": name,
        "amount_band": band,
        "amount": None,
        "position": None,
        "is_spouse": False,
        "envelope": _acquired_disposed(lines),
    }


def parse_schedule_a1(pdf_path: Path, pages: list[int]) -> list[dict[str, Any]]:
    """Parse all Schedule A-1 pages → `investment` lines in document order."""
    lines: list[dict[str, Any]] = []
    for page in pages:
        left = _entry_blocks(column_text(pdf_path, page, "left"), "NAME OF BUSINESS ENTITY")
        right = _entry_blocks(column_text(pdf_path, page, "right"), "NAME OF BUSINESS ENTITY")
        for block in _interleave_row_major(left, right):
            parsed = _parse_a1_block(block)
            if parsed is not None:
                lines.append(parsed)
    return lines


# ---------------------------------------------------------------------------
# Shared value helpers
# ---------------------------------------------------------------------------

_LITERAL_NONE = {"none"}


def _is_literal_none(value: str | None) -> bool:
    """A form-filler's literal "None" (case-insensitive) — a "nothing here"
    marker, never a name (real basket fact: filers type it)."""
    return value is not None and value.strip().casefold() in _LITERAL_NONE


def _value_after(lines: list[str], label: str) -> str | None:
    """First non-empty stripped line strictly after the `label` line."""
    seen = False
    for ln in lines:
        if not seen:
            if label in ln:
                seen = True
            continue
        if ln.strip():
            return ln.strip()
    return None


def _value_above(lines: list[str], label: str, *, skip: tuple[str, ...] = ()) -> str | None:
    """Nearest non-empty stripped line ABOVE the `label` line, skipping any line
    containing a string in `skip` (caption lines). Form values sit above their
    caption; this reads the value WITHOUT ever touching a different field's
    value (the ethics-load-bearing primitive for Schedule B / A-2 part-4: the
    city sits above its caption; the street/APN field is never read)."""
    idx = next((i for i, ln in enumerate(lines) if label in ln), None)
    if idx is None:
        return None
    for ln in reversed(lines[:idx]):
        if any(s in ln for s in skip):
            continue
        if ln.strip():
            return ln.strip()
    return None


def _position_value(lines: list[str], end_label: str) -> str | None:
    """Pull the YOUR BUSINESS POSITION value (inline or the next line), bounded
    by `end_label`. Literal "None" → None (the position is absent, not a name)."""
    for i, ln in enumerate(lines):
        if "YOUR BUSINESS POSITION" in ln:
            inline = ln.split("YOUR BUSINESS POSITION", 1)[1].strip()
            if inline:
                return None if _is_literal_none(inline) else inline
            for nxt in lines[i + 1:]:
                if end_label in nxt:
                    break
                if nxt.strip():
                    val = nxt.strip()
                    return None if _is_literal_none(val) else val
            return None
    return None


# ---------------------------------------------------------------------------
# Schedule D — Income: Gifts (one node per gift; exact amount)
# ---------------------------------------------------------------------------

_GIFT_LINE_RE = re.compile(
    r"(\d{2})\s*/\s*(\d{2})\s*/\s*(\d{2})\s+\$\s*([\d,]+\.\d{2})\s*(.*)"
)


def _parse_d_block(block: str) -> list[dict[str, Any]]:
    """Parse one Schedule D source cell → one `gift` line per gift row."""
    lines = block.splitlines()
    name = _first_value_before(lines, "ADDRESS")
    if not name:
        return []
    gifts: list[dict[str, Any]] = []
    for ln in lines:
        m = _GIFT_LINE_RE.search(ln)
        if not m:
            continue
        mm, dd, yy, amount, desc = m.groups()
        gifts.append({
            "schedule": "D",
            "interest_type": "gift",
            "counterparty_name_raw": name,
            "amount_band": None,
            "amount": amount,
            "position": None,
            "is_spouse": False,
            "envelope": {"gift_date": f"{mm}/{dd}/{yy}", "description": desc.strip()},
        })
    return gifts


def parse_schedule_d(pdf_path: Path, pages: list[int]) -> list[dict[str, Any]]:
    """Parse all Schedule D pages → `gift` lines (one per gift) in document order."""
    out: list[dict[str, Any]] = []
    for page in pages:
        left = _entry_blocks(column_text(pdf_path, page, "left"), "NAME OF SOURCE (Not an Acronym)")
        right = _entry_blocks(column_text(pdf_path, page, "right"), "NAME OF SOURCE (Not an Acronym)")
        for block in _interleave_row_major(left, right):
            out.extend(_parse_d_block(block))
    return out


# ---------------------------------------------------------------------------
# Schedule E — Income: Gifts – Travel Payments (one node per source; exact amount)
# ---------------------------------------------------------------------------

_AMT_RE = re.compile(r"AMT:\s*\$\s*([\d,]+\.\d{2})")


def _parse_e_block(block: str) -> dict[str, Any] | None:
    """Parse one Schedule E source cell → a `travel` line, or None if empty."""
    lines = block.splitlines()
    name = _first_value_before(lines, "ADDRESS")
    if not name:
        return None
    m = _AMT_RE.search(block)
    if not m:
        return None
    return {
        "schedule": "E",
        "interest_type": "travel",
        "counterparty_name_raw": name,
        "amount_band": None,
        "amount": m.group(1),
        "position": None,
        "is_spouse": False,
        "envelope": {},
    }


def parse_schedule_e(pdf_path: Path, pages: list[int]) -> list[dict[str, Any]]:
    """Parse all Schedule E pages → `travel` lines in document order."""
    out: list[dict[str, Any]] = []
    for page in pages:
        left = _entry_blocks(column_text(pdf_path, page, "left"), "NAME OF SOURCE (Not an Acronym)")
        right = _entry_blocks(column_text(pdf_path, page, "right"), "NAME OF SOURCE (Not an Acronym)")
        for block in _interleave_row_major(left, right):
            parsed = _parse_e_block(block)
            if parsed is not None:
                out.append(parsed)
    return out


# ---------------------------------------------------------------------------
# Schedule C — Income, Loans, & Business Positions
# Part 1 = income source (gross-income band) [+ position]; Part 2 = loan
# (highest-balance band). Loan security (real property) is NEVER extracted.
# ---------------------------------------------------------------------------

def _parse_c_cell(cell: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse one Schedule C cell → (parsed lines, unparsed records)."""
    lines = cell.splitlines()
    loan_idx = next((i for i, ln in enumerate(lines) if "LOANS RECEIVED" in ln), len(lines))
    part1, part2 = lines[:loan_idx], lines[loan_idx:]

    out: list[dict[str, Any]] = []
    unparsed: list[dict[str, Any]] = []

    # Part 1 — income source.
    name = _value_after(part1, "NAME OF SOURCE OF INCOME")
    position = _position_value(part1, "GROSS INCOME RECEIVED")
    gross = _checked_band(_slice_between(part1, "GROSS INCOME RECEIVED", "CONSIDERATION"))
    consideration = _slice_between(part1, "CONSIDERATION", "LOANS RECEIVED")
    is_spouse = bool(re.search(r"X\s+Spouse", consideration)) or (
        position is not None and "(spouse)" in position.lower()
    )
    if name and not _is_literal_none(name):
        if gross:
            out.append({
                "schedule": "C",
                "interest_type": "income source",
                "counterparty_name_raw": name,
                "amount_band": gross,
                "amount": None,
                "position": position,
                "is_spouse": is_spouse,
                "envelope": {},
            })
        elif position:
            # Position disclosed with NO gross-income band — never a fabricated
            # band, never a node; an envelope unparsed record + a validationcheck
            # candidate (Predeclared 5). Keys only, no raw value in any message.
            unparsed.append({
                "schedule": "C",
                "reason": "business_position_without_income_band",
            })

    # Part 2 — loan (lender + highest-balance band). Security is never extracted.
    lender = _value_after(part2, "NAME OF LENDER")
    bal = _checked_band(_slice_between(part2, "HIGHEST BALANCE", "Comments"))
    if lender and not _is_literal_none(lender) and bal:
        out.append({
            "schedule": "C",
            "interest_type": "loan",
            "counterparty_name_raw": lender,
            "amount_band": bal,
            "amount": None,
            "position": None,
            "is_spouse": False,
            "envelope": {},
        })
    return out, unparsed


def parse_schedule_c(
    pdf_path: Path, pages: list[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse all Schedule C pages → (lines, unparsed) in document order."""
    out: list[dict[str, Any]] = []
    unparsed: list[dict[str, Any]] = []
    for page in pages:
        left = _entry_blocks(column_text(pdf_path, page, "left"), "1. INCOME RECEIVED")
        right = _entry_blocks(column_text(pdf_path, page, "right"), "1. INCOME RECEIVED")
        for cell in _interleave_row_major(left, right):
            cell_lines, cell_unparsed = _parse_c_cell("1. INCOME RECEIVED" + cell)
            out.extend(cell_lines)
            unparsed.extend(cell_unparsed)
    return out, unparsed


# ---------------------------------------------------------------------------
# Schedule A-2 — Investments, Income, and Assets of Business Entities/Trusts
# Per cell, in order: part-1 entity (investment), part-3 reportable income
# sources (no band), part-4 sub-entry (investment OR real property — city only).
# ---------------------------------------------------------------------------

def _parse_a2_cell(cell: str) -> tuple[list[dict[str, Any]], int]:
    """Parse one A-2 cell → (lines in doc order, literal-None skip count)."""
    lines = cell.splitlines()
    out: list[dict[str, Any]] = []
    skipped_none = 0

    # Part 1 — the business entity sits ABOVE its "Name" caption. An empty cell
    # (the unused half of a 2-up page) has nothing above "Name" → None → skip.
    name = _value_above(lines, "Name")
    fmv1 = _checked_band(_slice_between(lines, "FAIR MARKET VALUE", "NATURE OF INVESTMENT"))
    position = _position_value(lines, "IDENTIFY THE GROSS INCOME")
    is_spouse = position is not None and "(spouse)" in position.lower()
    if name:
        out.append({
            "schedule": "A-2",
            "interest_type": "investment",
            "counterparty_name_raw": name,
            "amount_band": fmv1,
            "amount": None,
            "position": position,
            "is_spouse": is_spouse,
            "envelope": {},
        })

    # Part 3 — reportable single sources of income (no band; the carve-out).
    p3_lines = _slice_between(
        lines, "REPORTABLE SINGLE SOURCE", "INVESTMENTS AND INTERESTS"
    ).splitlines()
    if not any(re.search(r"X\s+None", ln) for ln in p3_lines):
        started = False
        for ln in p3_lines:
            if "Names listed below" in ln:
                started = True
                continue
            if not started:
                continue
            value = ln.strip()
            if not value:
                continue
            if _is_literal_none(value):
                skipped_none += 1
                continue
            out.append({
                "schedule": "A-2",
                "interest_type": "income source",
                "counterparty_name_raw": value,
                "amount_band": None,
                "amount": None,
                "position": None,
                "is_spouse": False,
                "envelope": {},
            })

    # Part 4 — sub-entry: INVESTMENT (named entity) or REAL PROPERTY (city only).
    p4_idx = next(
        (i for i, ln in enumerate(lines) if "INVESTMENTS AND INTERESTS" in ln), None
    )
    if p4_idx is not None:
        p4 = lines[p4_idx:]
        checkbox = _slice_between(p4, "Check one box", "FAIR MARKET VALUE")
        fmv4 = _checked_band(_slice_between(p4, "FAIR MARKET VALUE", "NATURE OF INTEREST"))
        if re.search(r"X\s+REAL PROPERTY", checkbox):
            # City only — the street/APN field (above the "Assessor's Parcel
            # Number or Street Address" caption) is structurally never read.
            city = _value_above(
                p4, "City or Other Precise Location",
                skip=("Description of Business Activity",),
            )
            if city and not _is_literal_none(city):
                out.append({
                    "schedule": "A-2",
                    "interest_type": "real property",
                    "counterparty_name_raw": city,
                    "amount_band": fmv4,
                    "amount": None,
                    "position": None,
                    "is_spouse": False,
                    "envelope": {},
                })
        elif re.search(r"X\s+INVESTMENT", checkbox):
            biz = _value_above(
                p4, "Assessor", skip=("Name of Business Entity",),
            )
            if biz and not _is_literal_none(biz):
                out.append({
                    "schedule": "A-2",
                    "interest_type": "investment",
                    "counterparty_name_raw": biz,
                    "amount_band": fmv4,
                    "amount": None,
                    "position": None,
                    "is_spouse": False,
                    "envelope": {},
                })
    return out, skipped_none


def parse_schedule_a2(
    pdf_path: Path, pages: list[int]
) -> tuple[list[dict[str, Any]], int]:
    """Parse all A-2 pages → (lines in doc order, literal-None skip count)."""
    out: list[dict[str, Any]] = []
    skipped_none = 0
    for page in pages:
        left = _entry_blocks(column_text(pdf_path, page, "left"), "1. BUSINESS ENTITY OR TRUST")
        right = _entry_blocks(column_text(pdf_path, page, "right"), "1. BUSINESS ENTITY OR TRUST")
        for cell in _interleave_row_major(left, right):
            cell_lines, skips = _parse_a2_cell(cell)
            out.extend(cell_lines)
            skipped_none += skips
    return out, skipped_none


# ---------------------------------------------------------------------------
# Schedule B — Real Property (city only; tenant names NEVER extracted)
# ---------------------------------------------------------------------------

def _parse_b_block(block: str) -> dict[str, Any] | None:
    """Parse one Schedule B property cell → a `real property` line (city only).

    The street address / APN (the value below the "ASSESSOR'S PARCEL NUMBER OR
    STREET ADDRESS" caption) is NEVER read. Tenant / rental-income source names
    are NEVER extracted (the SOURCES OF RENTAL INCOME section is ignored,
    including the "Name(s) redacted" marker and overflow pages).
    """
    lines = block.splitlines()
    # City sits between the "CITY" caption and the "FAIR MARKET VALUE" section.
    # An empty property cell has nothing there → None → skip. The street/APN
    # field (above the "CITY" caption) is never inside this slice, so it is
    # structurally never read.
    city_section = _slice_between(lines, "CITY", "FAIR MARKET VALUE")
    city = next((ln.strip() for ln in city_section.splitlines() if ln.strip()), None)
    if not city or _is_literal_none(city):
        return None
    band = _checked_band(_slice_between(lines, "FAIR MARKET VALUE", "NATURE OF INTEREST"))
    return {
        "schedule": "B",
        "interest_type": "real property",
        "counterparty_name_raw": city,
        "amount_band": band,
        "amount": None,
        "position": None,
        "is_spouse": False,
        "envelope": {},
    }


def parse_schedule_b(pdf_path: Path, pages: list[int]) -> list[dict[str, Any]]:
    """Parse all Schedule B pages → `real property` lines (city only).

    Overflow pages ("Additional Sources of Rental Income …") carry no
    ASSESSOR/CITY property block, so they yield no cell — tenant names there are
    never echoed.
    """
    out: list[dict[str, Any]] = []
    for page in pages:
        left = _entry_blocks(
            column_text(pdf_path, page, "left"),
            "ASSESSOR",
        )
        right = _entry_blocks(
            column_text(pdf_path, page, "right"),
            "ASSESSOR",
        )
        for block in _interleave_row_major(left, right):
            parsed = _parse_b_block(block)
            if parsed is not None:
                out.append(parsed)
    return out


# ---------------------------------------------------------------------------
# Cover sheet — filer identity + §4 schedule-summary marks
# ---------------------------------------------------------------------------

_COVER_SCHED_RE = re.compile(r"X\s+Schedule\s+(A-1|A-2|B|C|D|E)\b")
_COVER_NONE_RE = re.compile(r"X\s+None\s*-\s*No reportable")


def parse_cover(pdf_path: Path) -> dict[str, Any]:
    """Parse the cover page (page 1): filer name + which schedules are marked
    attached in §4, and whether the "None - No reportable interests" box is
    checked."""
    text = column_text(pdf_path, 1, "full")
    lines = text.splitlines()
    cover_filer = _value_after(lines, "NAME OF FILER")
    schedules_marked = sorted(set(_COVER_SCHED_RE.findall(text)))
    none_checked = bool(_COVER_NONE_RE.search(text))
    return {
        "cover_filer": cover_filer,
        "schedules_marked": schedules_marked,
        "none_checked": none_checked,
    }
