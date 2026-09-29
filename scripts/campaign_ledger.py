"""Campaign-finance ledger for NetFile yearly exports: hashed inputs, every physical row, reconciled filings.

The ledger is operator-private. It keeps every row of every sheet with a disposition, groups rows into
filings, and reconciles itemized Schedule A/E rows against the filer's own Summary totals. The public graph
is emitted from it by normalize_campaign_finance.py; nothing here writes outside the output root.
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import openpyxl

REQUIRED_SHEETS = ("A-Contributions", "E-Expenditure", "Summary")


class InputError(Exception):
    """An input is missing, unreadable, or not what the registry says it is."""


class UnsafeOutputError(Exception):
    """The output root would write into a protected location."""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_workbook(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.endswith(".xlsx")]
            if len(names) != 1:
                raise InputError(f"{path.name}: expected one .xlsx inside, found {len(names)}")
            with zf.open(names[0]) as f:
                wb = openpyxl.load_workbook(f, read_only=True)
                missing = [s for s in REQUIRED_SHEETS if s not in wb.sheetnames]
                wb.close()
    except (zipfile.BadZipFile, OSError, KeyError, ValueError) as exc:
        raise InputError(f"{path.name}: not a readable workbook export ({exc})") from exc
    if missing:
        raise InputError(f"{path.name}: missing sheet(s) {', '.join(missing)}")


def inventory_inputs(
    input_root: Path,
    source_id: str,
    capture_date: str,
    years: list[str],
    unavailable: list[dict],
) -> list[dict]:
    """Hash every yearly export of one capture; fail on anything unexpected.

    ``unavailable`` pins inputs known to be HTML pages rather than exports ({file, sha256}); they are recorded
    as unavailable coverage, never as empty years. Any other unreadable, missing or extra file fails.
    """
    capture = Path(input_root) / source_id / capture_date
    pins = {p["file"]: p["sha256"] for p in unavailable}
    expected = {f"{year}.zip": year for year in years}
    present = {p.name for p in capture.glob("*") if p.is_file()}
    extra = sorted(present - set(expected))
    if extra:
        raise InputError(f"{source_id}/{capture_date}: unexpected input(s) {', '.join(extra)}")
    entries = []
    for name, year in sorted(expected.items()):
        path = capture / name
        if not path.is_file():
            raise InputError(f"{source_id}/{capture_date}/{name}: missing")
        sha = _sha256(path)
        entry = {
            "path": f"{source_id}/{capture_date}/{name}",
            "source_id": source_id,
            "year": year,
            "bytes": path.stat().st_size,
            "sha256": sha,
        }
        if name in pins:
            if pins[name] != sha:
                raise InputError(f"{entry['path']}: pinned as unavailable with a different sha256")
            entry.update(coverage="unavailable", reason="html_page_not_export")
        else:
            _check_workbook(path)
            entry["coverage"] = "workbook"
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Output root
# ---------------------------------------------------------------------------

def _protected_dirs(repo: Path) -> list[Path]:
    repo = Path(repo).resolve()
    dirs = [repo]
    for layer in ("normalized", "extracted"):  # symlinks into the private data repo
        link = repo / "data" / layer
        if link.exists():
            dirs.append(link.resolve().parent)
    for layer in ("normalized", "extracted", "exports", "ingest-runs"):
        dirs.append((repo / "data" / layer).resolve())
    return dirs


def _inside_git_checkout(path: Path) -> Path | None:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            return parent
    return None


def resolve_output_root(output_root: Path, *repos: Path) -> Path:
    """Resolve symlinks and refuse any destination inside a git checkout or a protected data dir."""
    out = Path(output_root).expanduser().resolve()
    for repo in repos:
        for protected in _protected_dirs(repo):
            if out == protected or protected in out.parents:
                raise UnsafeOutputError(f"refusing to write into {protected}")
    checkout = _inside_git_checkout(out)
    if checkout is not None:
        raise UnsafeOutputError(f"refusing to write inside the git checkout {checkout}")
    if out.exists() and any(out.iterdir()):
        raise UnsafeOutputError(f"output root {out} is not empty")
    return out
