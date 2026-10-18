"""CivicPlus Archive Center adapter: one static page of titled items, each keyed by its ADID.

Not AgendaCenter (scripts/adapters/civicplus.py): no categories, years or AJAX, no agenda ids; an Archive
Center listing (`Archive.aspx?AMID=N`) is one page of `<table summary="Archive Details">` rows, each an
`Archive.aspx?ADID=N` link (a PDF) titled by the city, e.g. "October 7, 2026, City Council Agenda".

Every row is accounted for: included (a meeting), excluded with a reason, or unresolved. An unresolved row,
a missing or wrong archive table, a row count that does not add up, or a listing that no longer reaches back
before `backfill_from` is an adapter error, so the pull fails its floors and nothing is written.

Meetings: one per listing key (date, type, ordinal). A row naming n dates is n meetings sharing its item.
Rows on one key with the same title are re-postings of one agenda: the meeting takes the latest (highest)
ADID and lists the others as superseded; different titles on one key are unresolved. The meeting id is
`meeting-<source>-adid-<N>` (`-adid-<N>-<date>` for a row with several dates): the city's own item id,
independent of row order and title text. Requests: robots.txt and the listing page, through the robots gate
with the source's host allowlist; no item is fetched.
"""
from __future__ import annotations

import html as html_lib
import re
import urllib.parse
import urllib.request
from datetime import date

from net_retry import retry_transient

from .base import BaseAdapter
from .meeting_ids import normalize_title

_USER_AGENT = "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"
_MONTHS = {m: i for i, m in enumerate(("january february march april may june july august september "
                                       "october november december").split(), start=1)}
_DATE_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})\s*[,.]?\s*(\d{4})\b", re.I)
_HEADER_RE = re.compile(r'<table summary="Archive Details List".*?<span[^>]*font-weight: bold[^>]*>(.*?)</span>',
                        re.S)
_TABLE_RE = re.compile(r'<table summary="Archive Details">(.*?)</table>', re.S)
_ANCHOR_RE = re.compile(r'href="Archive\.aspx\?ADID=(\d+)"')
# The item link; everything after it in the row is its note (whatever the markup).
_ROW_RE = re.compile(r'<a href="Archive\.aspx\?ADID=(\d+)"[^>]*>(.*?)</a>(.*)', re.S)
# First match wins, on the title and its note.
_TYPES = (("cancel", "cancelled_meeting"), ("joint", "joint_meeting"), ("closed session", "closed_session"),
          ("special", "special"), ("workshop", "workshop"), ("agenda", "regular"))


def _text(fragment: str) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _dates(title: str) -> tuple[list[str], list[str]]:
    """(valid ISO dates, the date texts that are no date) in the title."""
    found, invalid = [], []
    for month, day, year in _DATE_RE.findall(title):
        try:
            found.append(date(int(year), _MONTHS[month.lower()], int(day)).isoformat())
        except ValueError:
            invalid.append(f"{month} {day}, {year}")
    return found, invalid


def _classify(row: dict, backfill_from: str) -> str | None:
    """The row's meeting type, or sets its exclusion / unresolved reason and returns None."""
    words = f"{row['title']} {row['note']}".lower()
    if row["unconsumed"]:
        row["unresolved"] = "unconsumed_text"
    elif row["invalid_dates"]:
        row["unresolved"] = "invalid_date"
    elif not row["dates"]:
        row["unresolved"] = "no_date"
    elif max(row["dates"]) < backfill_from:
        row["excluded"] = "before_backfill_from"
    elif "courtesy notice" in words:
        row["excluded"] = "attendance_notice"
    else:
        mtype = next((t for word, t in _TYPES if word in words), None)
        if mtype is None:
            row["unresolved"] = "no_type_word"
        return mtype
    return None


def parse_listing(page: str, *, source_id: str, base_url: str, backfill_from: str, archive_title: str) -> dict:
    """{meetings, inventory, errors} for one Archive Center listing page."""
    header = _HEADER_RE.search(page)
    if not header or _text(header.group(1)) != archive_title:
        found = _text(header.group(1)) if header else None
        return {"meetings": [], "errors": [f"listing_table_missing: no '{archive_title}' archive table (found {found!r})"],
                "inventory": {"raw_rows": 0, "items": [], "included": [], "excluded": [], "unresolved": []}}
    tables = _TABLE_RE.findall(page)
    adids = [int(a) for a in _ANCHOR_RE.findall(page)]
    errors, parsed = [], []
    for i, table in enumerate(tables):
        match = _ROW_RE.search(table)
        if len(_ANCHOR_RE.findall(table)) != 1 or not match:
            errors.append(f"row_count_mismatch: item table {i + 1} has {len(_ANCHOR_RE.findall(table))} ADID links")
            continue
        parsed.append({"adid": int(match.group(1)), "title": _text(match.group(2)), "note": _text(match.group(3)),
                       "unconsumed": _text(table[:match.start()])})
    if len(adids) != len(parsed) or len(set(adids)) != len(adids):
        errors.append(f"row_count_mismatch: {len(tables)} item tables, {len(adids)} ADID links on the page, "
                      f"{len(parsed)} parsed rows, {len(set(adids))} distinct ADIDs")
    for row in parsed:
        row["dates"], row["invalid_dates"] = _dates(row["title"])
        row["type"] = _classify(row, backfill_from)
        row["ordinal"] = 2 if re.search(r"\bsecond\b", row["title"].lower()) else 1
    if parsed and not any(r["dates"] and min(r["dates"]) < backfill_from for r in parsed):
        errors.append(f"listing_truncated: no item dated before {backfill_from}; the archive reaches back further")

    plural = [r for r in parsed if r["type"] and re.search(r"\bagendas\b", r["title"].lower())]
    by_date: dict[str, list[dict]] = {}
    for r in parsed:
        if r["type"] and r not in plural:
            for d in r["dates"]:
                by_date.setdefault(d, []).append(r)
    for r in plural:  # an index page vouched for by real rows only, never by another index
        r["type"] = None
        if len(by_date.get(r["dates"][0], [])) >= 2:
            r["excluded"] = "index_of_same_day_agendas"
        else:
            r["unresolved"] = "plural_agendas"
    included = [r for r in parsed if r["type"]]

    keyed: dict[tuple, list[dict]] = {}
    for r in included:
        for d in r["dates"]:
            keyed.setdefault((d, r["type"], r["ordinal"]), []).append(r)
    for d in sorted({d for d, _, _ in keyed}):
        types = {t for dd, t, _ in keyed if dd == d}
        if {"cancelled_meeting", "regular"} <= types:
            for key in [k for k in keyed if k[0] == d and k[1] in ("cancelled_meeting", "regular")]:
                for r in keyed.pop(key):
                    r["unresolved"] = "cancelled_and_regular_same_day"
    meetings = []
    for (d, mtype, ordinal), group in sorted(keyed.items()):
        if len({normalize_title(r["title"]) for r in group}) > 1:
            for r in group:
                r["unresolved"] = "same_key_different_titles"
            errors.append(f"unresolved ADIDs {', '.join(str(r['adid']) for r in group)}: same_key_different_titles "
                          f"({d} {mtype} {ordinal})")
            continue
        latest = max(group, key=lambda r: r["adid"])
        key = f"{latest['adid']}-{d}" if len(latest["dates"]) > 1 else str(latest["adid"])
        art = "notice" if mtype == "cancelled_meeting" else "agenda"
        meetings.append({
            "meeting_id": f"meeting-{source_id}-adid-{key}",
            "date": d, "title": latest["title"], "meeting_type": mtype,
            "listing_key": f"{d}|{mtype}|{ordinal}",
            "archive_item_id": latest["adid"],
            "superseded_item_ids": sorted(r["adid"] for r in group if r is not latest),
            "description": latest["note"],
            "artifacts": {art: {"available": True,
                                "url": urllib.parse.urljoin(base_url + "/", f"Archive.aspx?ADID={latest['adid']}")}},
        })
    unresolved = [r for r in parsed if r.get("unresolved")]
    for r in unresolved:
        if r["unresolved"] != "same_key_different_titles":
            errors.append(f"unresolved row ADID {r['adid']}: {r['unresolved']}: {r['title']}"
                      + (f" (invalid {', '.join(r['invalid_dates'])})" if r["invalid_dates"] else ""))
    inventory = {
        "raw_rows": len(tables), "items": sorted(adids),
        "included": sorted({r["adid"] for r in parsed if r["type"] and not r.get("unresolved")}),
        "excluded": [{"adid": r["adid"], "reason": r["excluded"]} for r in parsed if r.get("excluded")],
        "unresolved": [{"adid": r["adid"], "reason": r["unresolved"], "title": r["title"]} for r in unresolved],
    }
    return {"meetings": meetings, "inventory": inventory, "errors": errors}


class CivicPlusArchiveAdapter(BaseAdapter):
    """One CivicPlus Archive Center listing (an `AMID`), read through the gate under the source's host allowlist."""

    def __init__(self, source_config: dict, root_dir, **kwargs):
        super().__init__(source_config, root_dir, **kwargs)
        hosts = source_config.get("allowed_hosts")
        if not hosts:
            raise ValueError(f"{self.source_id}: a civicplus_archive source names its allowed_hosts")
        self.allowed_hosts = {h.lower() for h in hosts}
        self.archive_title = source_config["archive_title"]

    @retry_transient
    def _fetch_page(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with self.gate.open(req, timeout=30, hosts=self.allowed_hosts) as resp:
            return resp.read().decode(resp.headers.get_content_charset("utf-8"), errors="replace")

    def capture(self) -> dict:
        page = self._fetch_page(self.url)
        captured_at = self.utc_now_iso()
        raw_dir = self.raw_dir()
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / "source.html"
        raw_path.write_text(page, encoding="utf-8")
        parts = urllib.parse.urlsplit(self.url)
        out = parse_listing(page, source_id=self.source_id, base_url=f"{parts.scheme}://{parts.netloc}",
                            backfill_from=self.backfill_from, archive_title=self.archive_title)
        meetings = out["meetings"]
        for m in meetings:
            m["institution_id"] = self.institution_id
        counts: dict[str, int] = {}
        for m in meetings:
            for art in m["artifacts"]:
                counts[art] = counts.get(art, 0) + 1
        return {
            "capture_id": self.capture_id(), "source_id": self.source_id, "adapter": "civicplus_archive",
            "captured_at": captured_at, "url": self.url, "jurisdiction_id": self.jurisdiction_id,
            "institution_id": self.institution_id, "raw_artifact": str(raw_path.relative_to(self.root)),
            "meeting_count": len(meetings), "artifact_counts": counts, "inventory": out["inventory"],
            "meetings": meetings,
            "record_refs": [{"id": f"record-{self.source_id}-archive-page-{captured_at[:10]}",
                             "record_type": "archive_center_page", "source_id": self.source_id,
                             "artifact_path": str(raw_path.relative_to(self.root)), "captured_at": captured_at}],
            "errors": out["errors"],
        }
