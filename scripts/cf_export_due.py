"""The export-due alarm: tells the operator, by Healthchecks.io email, when a NetFile export needs downloading.

NetFile's yearly "Export Amended" ZIP sits behind a captcha, so only the operator can fetch it, by hand. This
module never touches the captcha or the export routes. It judges, per source and year, whether the selected
export (cf_inventory.py) is due, by three kinds of rule:

- calendar (always): the current year's export older than 7 days during Sep 1–Nov 15 of even years (else 30),
  the previous year's older than 90, any older year's older than 365;
- API hints (positive only, never proof of currency): a transaction dated after the export's latest report
  date, or a campaign filing filed after the export was downloaded, for that year's period;
- inventory: a year with no valid export (unless confirmed unavailable: then a warning, and a quarterly retry),
  and a landed file that is held or misnamed.

The API calls are the public portal's own JSON routes, at most one request per second, reading counts and
filing ids only; no contributor field is kept. Everything external is injected, so tests run without a network.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from cf_inventory import ConfigError, LandedProblem, SourceInventory, inventory

API_BASE = "https://netfile.com/api/public/sites/"
PACIFIC = ZoneInfo("America/Los_Angeles")
REQUEST_GAP_SECS = 1.0
FILINGS_PAGE_SIZE = 100
FILINGS_MAX_PAGES = 10
RETRY_AFTER_DAYS = 91  # a confirmed-unavailable year comes back as a reminder once a quarter
IDS_KEPT = 20
BODY_CHARS = 10_000
REQUIRED_KEYS = ("id", "name", "agency_code", "portal_url", "backfill_from")


class ApiError(Exception):
    """The NetFile API could not be read: unreachable, or its responses changed shape."""


def pacific_today(now: datetime) -> date:
    return now.astimezone(PACIFIC).date()


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "open-marin-export-due",
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


class NetFileApi:
    """The two no-captcha routes the alarm reads, throttled to one request per second."""

    def __init__(self, fetch: Callable[[str], dict] = fetch_json, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic, base: str = API_BASE):
        self.fetch, self.sleep, self.monotonic, self.base = fetch, sleep, monotonic, base
        self.requests = 0
        self._last: float | None = None

    def _get(self, route: str, params: dict) -> dict:
        if self._last is not None:
            wait = REQUEST_GAP_SECS - (self.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.monotonic()
        self.requests += 1
        try:
            payload = self.fetch(f"{self.base}{route}?{urllib.parse.urlencode(params)}")
        except Exception as exc:
            raise ApiError(f"NetFile API unreachable: {type(exc).__name__}: {exc}") from None
        if not isinstance(payload, dict):
            raise ApiError(f"NetFile API changed shape: {route} returned {type(payload).__name__}")
        return payload

    def transactions_between(self, aid: str, start: date, end: date) -> int:
        payload = self._get("api/SearchCampaignTransactions", {
            "aid": aid, "query": "", "currentPage": 1, "pageSize": 1, "isArchived": "false",
            "dateStart": start.isoformat(), "dateEnd": end.isoformat()})
        count = payload.get("totalCount")
        if type(count) is not int or not isinstance(payload.get("items"), list):
            raise ApiError("NetFile API changed shape: SearchCampaignTransactions has no integer totalCount/items")
        return count

    def filings_between(self, aid: str, start: date, end: date) -> list[tuple[str, date, str]]:
        """(filing id, filing date in Pacific time, period year) for each campaign filing filed in [start, end]."""
        found, page = [], 1
        while page <= FILINGS_MAX_PAGES:
            payload = self._get("api/filings/byDate", {
                "agencyCode": aid, "startDate": start.isoformat(), "endDate": end.isoformat(), "page": page,
                "pageSize": FILINGS_PAGE_SIZE, "isArchived": "false", "isOnlyCampaign": "true"})
            filings, total = payload.get("filings"), payload.get("totalCount")
            if not isinstance(filings, list) or type(total) is not int:
                raise ApiError("NetFile API changed shape: filings/byDate has no filings list/integer totalCount")
            found += [_filing(f) for f in filings]
            if not filings or len(found) >= total:
                break
            page += 1
        return found


def _instant(text, what: str) -> datetime:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(f"NetFile API changed shape: unreadable {what} {str(text)[:40]!r}") from None


def _filing(f) -> tuple[str, date, str]:
    if not isinstance(f, dict) or not isinstance(f.get("id"), (str, int)) or "periodEnd" not in f:
        raise ApiError("NetFile API changed shape: a filing lacks id/filingDate/periodEnd")
    filed = _instant(f.get("filingDate"), "filingDate")
    filed = filed.astimezone(PACIFIC).date() if filed.tzinfo else filed.date()
    period = f["periodEnd"]
    year = str(_instant(period, "periodEnd").year) if period else str(filed.year)
    return str(f["id"]), filed, year


# --- the verdict -------------------------------------------------------------------------------------


@dataclass
class DueItem:
    source_id: str
    year: str
    why: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    today: date
    sources: dict[str, dict]
    items: list[DueItem] = field(default_factory=list)
    landed: list[LandedProblem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # monitoring failures: they make the main run not clean
    api_status: str = "not checked"
    requests: int = 0
    transactions_after: dict = field(default_factory=dict)
    filings_after_capture: dict = field(default_factory=dict)

    @property
    def is_due(self) -> bool:
        return bool(self.items or self.landed)

    def record(self) -> dict:
        """What may be persisted: ids, years, reasons, counts and filing ids. Never a contributor field."""
        return {"today": self.today.isoformat(), "due": [{"source_id": i.source_id, "year": i.year, "why": i.why}
                                                         for i in self.items],
                "landed": [{"path": p.path, "reason": p.reason} for p in self.landed],
                "warnings": self.warnings, "problems": self.problems,
                "api": {"status": self.api_status, "requests": self.requests,
                        "transactions_after": self.transactions_after,
                        "filings_after_capture": self.filings_after_capture}}

    def body(self, scrub: Callable[[str], str] = lambda text: text) -> str:
        """The email body, scrubbed whole and only then cut: a secret split by the cut would survive."""
        return scrub(render_body(self))[:BODY_CHARS]


def _calendar_limit(year: int, today: date) -> tuple[int, str]:
    if year == today.year:
        if today.year % 2 == 0 and date(year, 9, 1) <= today <= date(year, 11, 15):
            return 7, "7: Sep 1–Nov 15 of an election year"
        return 30, "30 for the current year"
    if year == today.year - 1:
        return 90, "90 for the previous year"
    return 365, "365 for older years"


def _item(items: dict, sid: str, year: str) -> DueItem:
    return items.setdefault((sid, year), DueItem(sid, year))


def _judge_inventory(source: dict, inv: SourceInventory, today: date, items: dict, warnings: list[str]) -> None:
    sid = source["id"]
    for year, entry in inv.years.items():
        if entry.status == "held":
            _item(items, sid, year).why.append(f"data/raw/{entry.held.path} was not used: {entry.held.reason}; "
                                               "download it again")
        elif entry.status in ("missing", "pinned"):
            if entry.confirmed:
                retry = date.fromisoformat(entry.confirmed["confirmed"]) + timedelta(days=RETRY_AFTER_DAYS)
                if today >= retry:
                    _item(items, sid, year).why.append(
                        f"confirmed unavailable on {entry.confirmed['confirmed']}: quarterly retry, check the "
                        "portal again")
                else:
                    warnings.append(f"{source['name']} {year}: confirmed unavailable on "
                                    f"{entry.confirmed['confirmed']} ({entry.confirmed['reason']}); retry reminder "
                                    f"from {retry.isoformat()}")
            else:
                pinned = " (only a saved HTML page is on file)" if entry.status == "pinned" else ""
                _item(items, sid, year).why.append(f"no export on file for this year{pinned}")
        else:
            age = (today - date.fromisoformat(entry.selected.capture)).days
            limit, rule = _calendar_limit(int(year), today)
            if age > limit:
                _item(items, sid, year).why.append(f"export is {age} days old (limit {rule})")


def _api_hints(api: NetFileApi, source: dict, inv: SourceInventory, today: date, items: dict,
               verdict: Verdict) -> None:
    sid, aid = source["id"], source["agency_code"]
    selected = {y: e.selected for y, e in inv.years.items() if e.status == "selected"}
    if not selected:
        return
    oldest = min(date.fromisoformat(ref.capture) for ref in selected.values())
    if oldest < today:
        late: dict[str, list[str]] = {}
        for fid, filed, year in api.filings_between(aid, oldest + timedelta(days=1), today):
            ref = selected.get(year)
            if ref is not None and filed > date.fromisoformat(ref.capture):
                late.setdefault(year, []).append(fid)
        for year, ids in sorted(late.items()):
            verdict.filings_after_capture.setdefault(sid, {})[year] = {"count": len(ids), "ids": sorted(ids)[:IDS_KEPT]}
            _item(items, sid, year).why.append(f"NetFile lists {len(ids)} filing(s) filed after this export was "
                                               f"downloaded ({selected[year].capture}) for this period")
    for year, ref in sorted(selected.items()):
        start = (date.fromisoformat(ref.latest_report_date) + timedelta(days=1) if ref.latest_report_date
                 else date(int(year), 1, 1))
        end = min(date(int(year), 12, 31), today)
        if start > end:
            continue
        count = api.transactions_between(aid, start, end)
        if count:
            verdict.transactions_after.setdefault(sid, {})[year] = count
            _item(items, sid, year).why.append(
                f"NetFile lists {count} transaction(s) dated after this export's latest report date "
                f"({ref.latest_report_date})")


def check_sources(sources: list[dict], today: date | None = None) -> list[str]:
    """Everything the alarm needs from the registry; an empty or unjudgeable registry is a problem, never 'all clear'."""
    if not sources:
        return ["no campaign sources in the registry: the export-due alarm has nothing to judge"]
    problems = []
    for source in sources:
        missing = [k for k in REQUIRED_KEYS if not str(source.get(k) or "").strip()]
        if missing:
            problems.append(f"campaign source {source.get('id', '?')} lacks {', '.join(missing)} in the registry")
            continue
        try:
            start = date.fromisoformat(str(source["backfill_from"]))
        except ValueError:
            start = None
        if start is None or (today is not None and start > today):
            problems.append(f"campaign source {source['id']}: backfill_from {source['backfill_from']!r} is not a "
                            "past YYYY-MM-DD date")
    return problems


def evaluate(raw_root: Path, sources: list[dict], now: datetime, cache: dict, api: NetFileApi | None,
             extra: list[DueItem] = ()) -> Verdict:
    """Judge every source and year. Never raises for a bad API or a bad registry entry: those are `problems`."""
    today = pacific_today(now)
    verdict = Verdict(today, {s["id"]: s for s in sources if "id" in s})
    verdict.problems += check_sources(sources, today)
    usable = [s for s in sources if not check_sources([s], today)]
    items: dict[tuple[str, str], DueItem] = {}
    inventories = {}
    for source in usable:
        try:
            inventories[source["id"]] = inventory(raw_root, [source], today, cache)[source["id"]]
        except ConfigError as exc:
            verdict.problems.append(str(exc))
    for source in usable:
        inv = inventories.get(source["id"])
        if inv is not None:
            _judge_inventory(source, inv, today, items, verdict.warnings)
            verdict.landed += inv.landed_problems
    if api is not None:
        try:
            for source in usable:
                if source["id"] in inventories:
                    _api_hints(api, source, inventories[source["id"]], today, items, verdict)
            verdict.api_status = f"ok ({api.requests} requests)"
        except ApiError as exc:
            verdict.problems.append(str(exc))
            verdict.api_status = f"failed: {exc}; calendar rules only"
        verdict.requests = api.requests
    for item in extra:
        _item(items, item.source_id, item.year).why.extend(item.why)
    verdict.items = sorted(items.values(), key=lambda i: (i.source_id, -int(i.year) if i.year.isdigit() else 1))
    return verdict


# --- the email body ------------------------------------------------------------------------------------


def render_body(v: Verdict) -> str:
    count = len(v.items) + len(v.landed)
    if count:
        lines = [f"Open Marin: campaign export due ({count} item{'s' if count != 1 else ''}, {v.today.isoformat()})"]
    else:
        lines = [f"Open Marin: no campaign export due ({v.today.isoformat()})"]
    prepared = [i for i in v.items if i.source_id == "*"]
    if prepared:
        lines += ["", "Landed exports, prepared automatically:"]
        for item in prepared:
            lines += [f"  - {item.year}: {why}" for why in item.why]
    for sid in sorted({i.source_id for i in v.items} - {"*"}):
        source = v.sources.get(sid, {"name": sid, "agency_code": "?", "portal_url": "?"})
        lines += ["", f"{source['name']} ({source['agency_code']}): {source['portal_url']}"]
        if any(i.year.isdigit() for i in v.items if i.source_id == sid):
            lines.append('  For each year: choose the year, click "Export Amended", save the ZIP exactly as shown.')
        for item in (i for i in v.items if i.source_id == sid):
            if item.year.isdigit():
                lines.append(f"  - {item.year} -> save as data/raw/{sid}/{v.today.isoformat()}/{item.year}.zip")
            else:
                lines.append(f"  - {item.year}")
            lines += [f"      {why}" for why in item.why]
    if v.landed:
        lines += ["", "Fix these landed files (nothing else changes until they are fixed or removed):"]
        lines += [f"  - data/raw/{p.path}: {p.reason}" for p in v.landed]
    if v.warnings:
        lines += ["", "Coverage warnings (not due):", *(f"  - {w}" for w in v.warnings)]
    if v.problems:
        lines += ["", "Monitoring problems (the weekly run reports these too):", *(f"  - {p}" for p in v.problems)]
    lines += ["", f"NetFile API: {v.api_status}"]
    return "\n".join(lines) + "\n"
