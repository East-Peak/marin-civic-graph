"""Ingestion safety net: a run never makes data worse, and silence is failure.

See docs/specs/2026-09-28-persistent-ingestion-design.md (I1). The failure this
exists for is real: after NetFile replatformed, the campaign-finance and Form
700 scrapers got HTTP 200 with zero rows, reported success, and would have
overwritten good data with empty files.

Every pull is judged against per-source floors before anything is written:
  * rows must be > 0 and at least ``min_ratio`` x the baseline: the max rows
    over the last ``BASELINE_WINDOW`` GOOD runs (see RunLedger);
  * the newest past record must be no older than ``max_newest_age_days``;
  * the adapter may report at most ``max_errors`` errors (a swallowed year or
    a failed detail page keeps the row count up while losing data).
A pull that fails its floors writes nothing (the previous good output stays
authoritative) and is recorded in the run ledger with its reasons.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Floors:
    # 0.9: meeting lists and filings accumulate, so a >10% drop is a broken
    # pull, not real churn. Rolling-window sources (Ross) override it.
    min_ratio: float = 0.9
    # 45 days rather than ~21 so a council's summer recess isn't an alert.
    max_newest_age_days: int | None = 45
    # 0: any adapter error is a partial pull. Raise it per source, with a
    # registry comment naming the known benign error.
    max_errors: int = 0

    @classmethod
    def from_config(cls, source_config: dict[str, Any]) -> "Floors":
        return cls(**(source_config.get("floors") or {}))


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def evaluate(
    *,
    rows: int,
    newest: date | None,
    last_good_rows: int | None,
    today: date,
    floors: Floors,
    errors: int = 0,
    baseline: str = "the last good run",
) -> Verdict:
    reasons: list[str] = []
    if errors > floors.max_errors:
        reasons.append(
            f"{errors} adapter error{'s' if errors != 1 else ''} (max {floors.max_errors}): a partial pull"
        )
    if rows == 0:
        reasons.append("pull returned 0 rows")
    elif last_good_rows and rows < floors.min_ratio * last_good_rows:
        reasons.append(
            f"pull returned {rows} rows, below {floors.min_ratio:.0%} of {baseline} ({last_good_rows})"
        )
    if floors.max_newest_age_days is not None and rows > 0:
        if newest is None:
            reasons.append("no dated past record in the pull")
        elif (today - newest).days > floors.max_newest_age_days:
            reasons.append(
                f"newest past record is {newest.isoformat()}, older than {floors.max_newest_age_days} days"
            )
    return Verdict(ok=not reasons, reasons=reasons)


def newest_past_date(records: Iterable[dict[str, Any]], today: date, key: str = "date") -> date | None:
    """Latest parseable date on or before ``today`` (upcoming meetings don't count)."""
    newest: date | None = None
    for record in records:
        raw = record.get(key)
        if not isinstance(raw, str):
            continue
        try:
            d = date.fromisoformat(raw[:10])
        except ValueError:
            continue
        if d <= today and (newest is None or d > newest):
            newest = d
    return newest


def write_if_ok(path: Path, text: str, verdict: Verdict) -> bool:
    """Atomically write ``text`` to ``path`` only if the pull passed its floors."""
    if not verdict.ok:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


# The row floor compares against the MAX over this many good runs, not the
# last one: against the last run alone, a 9%-a-week decline passes every week
# and compounds without limit.
BASELINE_WINDOW = 4


class RunLedger:
    """Append-only JSONL of every pull and its verdict; the source of the baseline.

    ``rows`` is always the adapter's pre-merge row count (what ``run_source``
    judges), so baselines compare like with like; captures carry the same
    number as ``pulled_rows``.

    An operator reset (``ingest_baseline.py --reset``) is an ordinary ok entry
    with a ``reset`` reason. It starts a new baseline window: nothing before it
    counts, so a source whose scope legitimately shrank can pass again.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def _write(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    def _entries(self, source_id: str) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries = (json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines())
        return [e for e in entries if e["source_id"] == source_id]

    def append(self, source_id: str, run_at: str, rows: int, newest: date | None, verdict: Verdict) -> None:
        self._write({
            "source_id": source_id,
            "run_at": run_at,
            "rows": rows,
            "newest": newest.isoformat() if newest else None,
            "ok": verdict.ok,
            "reasons": verdict.reasons,
        })

    def reset(self, source_id: str, *, rows: int, reason: str, run_at: str) -> dict[str, Any]:
        """Append an audited operator reset that becomes the new baseline."""
        if not reason.strip():
            raise ValueError("a baseline reset needs a --reason")
        if rows <= 0:
            raise ValueError(f"a baseline reset needs a positive row count, not {rows}")
        entry = {"source_id": source_id, "run_at": run_at, "rows": rows, "newest": None,
                 "ok": True, "reasons": [], "reset": reason.strip()}
        self._write(entry)
        return entry

    def last_good(self, source_id: str) -> dict[str, Any] | None:
        good = [e for e in self._entries(source_id) if e["ok"]]
        return good[-1] if good else None

    def latest(self, source_id: str) -> dict[str, Any] | None:
        entries = self._entries(source_id)
        return entries[-1] if entries else None

    def baseline_rows(self, source_id: str, window: int = BASELINE_WINDOW) -> int | None:
        """Max rows over the last ``window`` good runs since the latest reset."""
        rows: list[int] = []
        for entry in self._entries(source_id):
            if entry.get("reset"):
                rows = [entry["rows"]]
            elif entry["ok"]:
                rows.append(entry["rows"])
        return max(rows[-window:]) if rows else None
