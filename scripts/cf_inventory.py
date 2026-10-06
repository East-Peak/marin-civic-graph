"""The effective inventory of landed NetFile campaign exports: what data/raw offers, per source and year.

The operator downloads each yearly "Export Amended" ZIP by hand (NetFile puts it behind a captcha) into
data/raw/<source>/<YYYY-MM-DD capture>/<year>.zip. Per source and year, the newest capture holding that year's
file is the candidate: it is selected if it validates (or is a registry-pinned page), and otherwise the year is
held. A held year never falls back to an older file: an invalid newest submission must be fixed, not skipped.
Nothing here writes anything; validation results are cached by the caller, keyed by content hash.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from campaign_ledger import InputError, _check_workbook

DATE_DIR = re.compile(r"\d{4}-\d{2}-\d{2}")
YEAR_FILE = re.compile(r"(\d{4})\.zip")


class ConfigError(Exception):
    """The registry's campaign-finance settings are missing or malformed."""


@dataclass(frozen=True)
class FileRef:
    path: str  # relative to the raw root: <source>/<capture>/<year>.zip
    capture: str
    sha256: str
    latest_report_date: str | None = None
    reason: str | None = None  # why it did not validate (held files only)


@dataclass
class YearEntry:
    year: str
    status: str  # selected | pinned | held | missing
    selected: FileRef | None = None
    pinned: FileRef | None = None
    held: FileRef | None = None
    confirmed: dict | None = None  # the registry's confirmed_unavailable entry for this year, if any
    submitted: list[FileRef] = field(default_factory=list)  # every capture's file for this year, oldest first


@dataclass(frozen=True)
class LandedProblem:
    path: str
    reason: str


@dataclass
class SourceInventory:
    source_id: str
    years: dict[str, YearEntry]
    landed_problems: list[LandedProblem]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _real_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if DATE_DIR.fullmatch(text) else None
    except ValueError:
        return None


def validate_export(path: Path) -> dict:
    """{ok, reason, latest_report_date}: the normalizer's own workbook check, with a plain reason on failure."""
    head = path.read_bytes()[:512].lstrip()
    if head[:1] == b"<":
        return {"ok": False, "reason": "an HTML page, not the export ZIP (the download failed or was blocked)",
                "latest_report_date": None}
    try:
        latest = _check_workbook(path)
    except InputError as exc:
        return {"ok": False, "reason": str(exc), "latest_report_date": None}
    return {"ok": True, "reason": None, "latest_report_date": latest}


def years_for(source: dict, today: date) -> list[str]:
    start = int(str(source["backfill_from"])[:4])
    return [str(y) for y in range(start, today.year + 1)]


def confirmed_unavailable(source: dict, today: date) -> dict[str, dict]:
    """The operator's confirmed-unavailable years, validated: each needs a real date and a reason."""
    years = set(years_for(source, today))
    confirmed = {}
    for entry in source.get("confirmed_unavailable") or []:
        year = str(entry.get("year", ""))
        if year not in years:
            raise ConfigError(f"{source['id']}: confirmed_unavailable year {year!r} is outside "
                              f"{min(years)}–{max(years)}")
        when = _real_date(str(entry.get("confirmed", "")))
        if when is None or when > today:
            raise ConfigError(f"{source['id']} {year}: confirmed_unavailable needs a past 'confirmed' date "
                              "(YYYY-MM-DD)")
        if not str(entry.get("reason") or "").strip():
            raise ConfigError(f"{source['id']} {year}: confirmed_unavailable needs a reason")
        confirmed[year] = {"year": year, "confirmed": when.isoformat(), "reason": str(entry["reason"]).strip()}
    return confirmed


def _validated(path: Path, sha: str, cache: dict) -> dict:
    if sha not in cache:
        cache[sha] = validate_export(path)
    return cache[sha]


def source_inventory(raw_root: Path, source: dict, today: date, cache: dict) -> SourceInventory:
    sid = source["id"]
    years = years_for(source, today)
    pins = {(p["capture"], p["file"]): p["sha256"] for p in source.get("unavailable_inputs") or []}
    problems: list[LandedProblem] = []
    files: dict[str, list[tuple[str, Path]]] = {y: [] for y in years}
    base = Path(raw_root) / sid
    for child in sorted(base.iterdir()) if base.is_dir() else ():
        rel = f"{sid}/{child.name}"
        if not child.is_dir():
            problems.append(LandedProblem(rel, f"a file outside any capture folder; move it into {sid}/<YYYY-MM-DD>/"))
            continue
        captured = _real_date(child.name)
        if captured is None:
            problems.append(LandedProblem(rel, "the capture folder must be named YYYY-MM-DD (the download date)"))
            continue
        if captured > today:
            problems.append(LandedProblem(rel, "the capture folder is dated after today"))
            continue
        for path in sorted(child.iterdir()):
            match = YEAR_FILE.fullmatch(path.name)
            if not path.is_file() or not match:
                hint = re.search(r"(20\d{2})", path.name)
                fix = f"; rename it to {hint.group(1)}.zip" if hint else ""
                problems.append(LandedProblem(f"{rel}/{path.name}", f"not named <year>.zip{fix}"))
            elif match.group(1) not in files:
                problems.append(LandedProblem(f"{rel}/{path.name}",
                                              f"year {match.group(1)} is outside {years[0]}–{years[-1]}"))
            else:
                files[match.group(1)].append((child.name, path))

    confirmed = confirmed_unavailable(source, today)
    entries = {}
    for year in years:
        entry = YearEntry(year=year, status="missing", confirmed=confirmed.get(year))
        for capture, path in files[year]:  # sorted by capture date, oldest first
            sha = _sha256(path)
            rel = f"{sid}/{capture}/{path.name}"
            if pins.get((capture, path.name)) == sha:
                entry.submitted.append(FileRef(rel, capture, sha))
                continue
            check = _validated(path, sha, cache)
            entry.submitted.append(FileRef(rel, capture, sha, check["latest_report_date"], check["reason"]))
        if entry.submitted:
            newest = entry.submitted[-1]
            capture, name = newest.capture, Path(newest.path).name
            if pins.get((capture, name)) == newest.sha256:
                entry.status, entry.pinned = "pinned", newest
            elif newest.reason is None:
                entry.status, entry.selected = "selected", newest
            else:
                entry.status, entry.held = "held", newest
        entries[year] = entry
    return SourceInventory(sid, entries, problems)


def inventory(raw_root: Path, sources: list[dict], today: date, cache: dict) -> dict[str, SourceInventory]:
    return {source["id"]: source_inventory(raw_root, source, today, cache) for source in sources}


def selection_id(inventories: dict[str, SourceInventory]) -> str:
    """sha256 over what data/raw offers: per source and year, the status, file hash and capture date."""
    rows = []
    for sid, source in sorted(inventories.items()):
        for year, entry in sorted(source.years.items()):
            ref = entry.selected or entry.pinned or entry.held
            rows.append([sid, year, entry.status, ref.sha256 if ref else None, ref.capture if ref else None])
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()
