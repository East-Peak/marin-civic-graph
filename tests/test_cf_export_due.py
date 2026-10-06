"""The export-due alarm's rules, over synthetic exports, a fake NetFile API and a fixed clock (no network)."""
from __future__ import annotations

import json
import sys
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cf_export_due as due  # noqa: E402
from tests.netfile_workbooks import filing, summary, write_export  # noqa: E402

HTML_PAGE = b"<!DOCTYPE html><html></html>"
COUNTY = {"id": "example-cf", "name": "Example County", "agency_code": "EXC",
          "portal_url": "https://netfile.example/public/EXC/campaign", "backfill_from": "2023-01-01"}
TOWN = {"id": "sampleton-cf", "name": "Sampleton", "agency_code": "SMP",
        "portal_url": "https://netfile.example/public/SMP/campaign", "backfill_from": "2025-01-01"}
# A contributor-shaped search result: none of these values may ever be persisted or printed.
PRIVATE = {"name": "Quill, Ada", "address": "Sampleton, CA, 94999", "employer": "Example Widgets",
           "occupation": "Tinkerer", "filerName": "Friends of Example"}


def _at(day: str, hour: int = 12) -> datetime:  # noon UTC: the same calendar day in Pacific time
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=timezone.utc)


def _export(raw: Path, source: str, capture: str, year: str, rpt: str) -> None:
    write_export(raw / source / capture / f"{year}.zip", {"Summary": [summary(filing(rpt=rpt), "A", "1", 0)]})


class FakeApi:
    """Stands in for netfile.com: transactions and filings, as the portal's own JSON routes return them."""

    def __init__(self):
        self.transactions: dict[str, list[str]] = {}  # aid -> transaction dates
        self.filings: dict[str, list[dict]] = {}  # aid -> filings
        self.urls: list[str] = []
        self.down: Exception | None = None
        self.shape: dict | None = None  # a response to return instead of the real shape

    def __call__(self, url: str) -> dict:
        self.urls.append(url)
        if self.down:
            raise self.down
        if self.shape is not None:
            return self.shape
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        if parts.path.endswith("api/SearchCampaignTransactions"):
            hits = [d for d in self.transactions.get(q["aid"], []) if q["dateStart"] <= d <= q["dateEnd"]]
            items = [{**PRIVATE, "id": "x", "date": f"{d}T07:00:00Z", "amount": 1.0} for d in hits][:int(q["pageSize"])]
            return {"aid": q["aid"], "items": items, "pageSize": int(q["pageSize"]), "currentPage": 1,
                    "totalCount": len(hits)}
        if parts.path.endswith("api/filings/byDate"):
            hits = [f for f in self.filings.get(q["agencyCode"], [])
                    if q["startDate"] <= f["filingDate"][:10] <= q["endDate"]]
            size, page = int(q["pageSize"]), int(q["page"])
            return {"filings": hits[(page - 1) * size: page * size], "totalCount": len(hits)}
        raise AssertionError(f"unexpected url {url}")

    def add_filing(self, aid: str, fid: str, filed: str, period_end: str | None) -> None:
        self.filings.setdefault(aid, []).append({
            "id": fid, "formName": "FPPC 460", "filerName": PRIVATE["filerName"], "filingDate": f"{filed}T16:00:00+00:00",
            "periodStart": None, "periodEnd": None if period_end is None else f"{period_end}T00:00:00+00:00"})


class Clock:
    def __init__(self):
        self.t = 0.0
        self.requests: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.t += seconds


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    return tmp_path / "raw"


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _evaluate(raw, api, clock, now, sources=(COUNTY,), use_api=True):
    client = due.NetFileApi(api, sleep=clock.sleep, monotonic=clock.monotonic) if use_api else None
    return due.evaluate(raw, list(sources), now, {}, client)


def _fresh(raw: Path, capture: str, years=("2023", "2024", "2025", "2026"), source="example-cf") -> None:
    for year in years:
        _export(raw, source, capture, year, rpt=f"{int(year) + 1}-01-31" if year != "2026" else capture)


def _due(verdict) -> dict[tuple[str, str], list[str]]:
    return {(i.source_id, i.year): i.why for i in verdict.items}


# --- calendar rules --------------------------------------------------------------------------------


@pytest.mark.parametrize("today,age_ok,age_due", [
    ("2026-10-12", "2026-10-05", "2026-10-04"),  # Sep 1–Nov 15 of an even year: 7 days
    ("2026-09-01", "2026-08-25", "2026-08-24"),
    ("2026-11-15", "2026-11-08", "2026-11-07"),
    ("2026-11-16", "2026-10-17", "2026-10-16"),  # after Nov 15: 30 days
    ("2026-08-31", "2026-08-01", "2026-07-31"),
    ("2027-10-12", "2027-09-12", "2027-09-11"),  # an odd year: 30 days all autumn
])
def test_the_current_years_export_is_due_by_its_season(raw, api, clock, today, age_ok, age_due):
    year = today[:4]
    source = {**COUNTY, "backfill_from": f"{year}-01-01"}
    _export(raw, "example-cf", age_ok, year, rpt=age_ok)
    assert _due(_evaluate(raw, api, clock, _at(today), [source])) == {}

    _export(raw, "example-cf", age_due, year, rpt=age_due)
    (raw / "example-cf" / age_ok / f"{year}.zip").unlink()

    why = _due(_evaluate(raw, api, clock, _at(today), [source]))[("example-cf", year)]
    assert any("days old" in w for w in why)


@pytest.mark.parametrize("year,limit", [("2025", 90), ("2024", 365), ("2023", 365)])
def test_older_years_have_longer_limits(raw, api, clock, year, limit):
    _fresh(raw, "2026-10-10", years=[y for y in ("2023", "2024", "2025", "2026") if y != year])
    ok = date.fromordinal(date(2026, 10, 12).toordinal() - limit).isoformat()
    _export(raw, "example-cf", ok, year, rpt=f"{int(year) + 1}-01-31")
    assert _due(_evaluate(raw, api, clock, _at("2026-10-12"))) == {}

    later = _at("2026-10-13")
    assert ("example-cf", year) in _due(_evaluate(raw, api, clock, later))


def test_a_fresh_current_year_does_not_excuse_a_stale_prior_year(raw, api, clock):
    _fresh(raw, "2026-10-10", years=("2023", "2024", "2026"))
    _export(raw, "example-cf", "2026-04-14", "2025", rpt="2026-01-31")

    assert list(_due(_evaluate(raw, api, clock, _at("2026-10-12")))) == [("example-cf", "2025")]


# --- API hints ---------------------------------------------------------------------------------------


def test_a_transaction_dated_after_the_latest_report_makes_the_year_due_now(raw, api, clock):
    _fresh(raw, "2026-10-10")  # 2026's latest report date is 2026-10-10
    api.transactions["EXC"] = ["2026-10-10", "2025-12-30"]
    assert _due(_evaluate(raw, api, clock, _at("2026-10-12"))) == {}

    api.transactions["EXC"].append("2026-10-11")
    verdict = _evaluate(raw, api, clock, _at("2026-10-12"))

    assert _due(verdict) == {("example-cf", "2026"): [
        "NetFile lists 1 transaction(s) dated after this export's latest report date (2026-10-10)"]}
    assert verdict.record()["api"]["transactions_after"] == {"example-cf": {"2026": 1}}


def test_a_late_filed_old_period_is_caught_by_the_filing_hint(raw, api, clock):
    _fresh(raw, "2026-10-10")
    api.transactions["EXC"] = ["2024-06-01"]  # dated long before the 2024 export's latest report: no count can see it
    api.add_filing("EXC", "9001", filed="2026-10-11", period_end="2024-06-30")

    verdict = _evaluate(raw, api, clock, _at("2026-10-12"))

    assert _due(verdict) == {("example-cf", "2024"): [
        "NetFile lists 1 filing(s) filed after this export was downloaded (2026-10-10) for this period"]}
    assert verdict.record()["api"]["filings_after_capture"] == {"example-cf": {"2024": {"count": 1, "ids": ["9001"]}}}


def test_a_same_count_amendment_is_caught_by_the_filing_hint_or_the_calendar(raw, api, clock):
    _fresh(raw, "2026-10-10")
    api.add_filing("EXC", "9002", filed="2026-10-10", period_end="2025-12-31")  # same day as the download
    assert _due(_evaluate(raw, api, clock, _at("2026-10-12"))) == {}  # counts alone can't prove currency …

    api.add_filing("EXC", "9003", filed="2026-10-12", period_end="2025-12-31")  # … an amendment filed later
    assert ("example-cf", "2025") in _due(_evaluate(raw, api, clock, _at("2026-10-12")))
    api.filings.clear()
    api.add_filing("EXC", "9005", filed="2026-10-10", period_end="2026-09-30")  # unseen by any count …
    assert ("example-cf", "2026") in _due(_evaluate(raw, api, clock, _at("2026-10-18")))  # … the calendar has it


def test_a_filing_without_a_period_counts_for_its_filing_year(raw, api, clock):
    _fresh(raw, "2026-10-10")
    api.add_filing("EXC", "9004", filed="2026-10-11", period_end=None)
    assert list(_due(_evaluate(raw, api, clock, _at("2026-10-12")))) == [("example-cf", "2026")]


def test_requests_are_polite_and_ask_only_for_counts(raw, api, clock):
    _fresh(raw, "2026-10-10")
    _fresh(raw, "2026-10-10", years=("2025", "2026"), source="sampleton-cf")
    stamps = []
    client = due.NetFileApi(lambda url: (stamps.append(clock.t), api(url))[1],
                            sleep=clock.sleep, monotonic=clock.monotonic)

    due.evaluate(raw, [COUNTY, TOWN], _at("2026-10-12"), {}, client)

    assert len(stamps) >= 3 and all(b - a >= 1.0 for a, b in zip(stamps, stamps[1:]))
    searches = [u for u in api.urls if "SearchCampaignTransactions" in u]
    assert searches and all("pageSize=1&" in u for u in searches)


def test_no_contributor_field_is_persisted_or_rendered(raw, api, clock):
    _fresh(raw, "2026-10-10")
    api.transactions["EXC"] = ["2026-10-11"]
    api.add_filing("EXC", "9001", filed="2026-10-11", period_end="2024-06-30")

    verdict = _evaluate(raw, api, clock, _at("2026-10-12"))

    text = json.dumps(verdict.record()) + verdict.body()
    for value in PRIVATE.values():
        assert value not in text


# --- gaps, landed files, nothing due -------------------------------------------------------------------


def test_a_missing_year_is_due_unless_confirmed_unavailable_then_a_quarterly_reminder(raw, api, clock):
    _fresh(raw, "2026-10-10", years=("2024", "2025", "2026"))
    assert _due(_evaluate(raw, api, clock, _at("2026-10-12")))[("example-cf", "2023")] == [
        "no export on file for this year"]

    confirmed = {**COUNTY, "confirmed_unavailable": [
        {"year": "2023", "confirmed": "2026-10-01", "reason": "the portal lists no export"}]}
    verdict = _evaluate(raw, api, clock, _at("2026-10-12"), [confirmed])
    assert _due(verdict) == {}
    assert verdict.warnings == ["Example County 2023: confirmed unavailable on 2026-10-01 (the portal lists no "
                                "export); retry reminder from 2026-12-31"]

    reminder = _evaluate(raw, api, clock, _at("2026-12-31"), [confirmed])
    assert _due(reminder)[("example-cf", "2023")] == [
        "confirmed unavailable on 2026-10-01: quarterly retry, check the portal again"]


def test_an_invalid_landed_file_is_due_with_the_reason(raw, api, clock):
    _fresh(raw, "2026-10-10")
    (raw / "example-cf/2026-10-11").mkdir(parents=True)
    (raw / "example-cf/2026-10-11/2025.zip").write_bytes(HTML_PAGE)

    verdict = _evaluate(raw, api, clock, _at("2026-10-12"))

    assert _due(verdict) == {("example-cf", "2025"): [
        "data/raw/example-cf/2026-10-11/2025.zip was not used: an HTML page, not the export ZIP (the download "
        "failed or was blocked); download it again"]}
    assert "you downloaded" not in verdict.body()  # plain, not chatty


def test_misnamed_files_are_due_with_the_fix(raw, api, clock):
    _fresh(raw, "2026-10-10")
    _export(raw, "example-cf", "2026-10-11", "EXC_2026_Amended_Transactions", rpt="2026-10-11")

    verdict = _evaluate(raw, api, clock, _at("2026-10-12"))

    assert [(p.path, p.reason) for p in verdict.landed] == [
        ("example-cf/2026-10-11/EXC_2026_Amended_Transactions.zip", "not named <year>.zip; rename it to 2026.zip")]
    assert verdict.is_due and "rename it to 2026.zip" in verdict.body()


def test_nothing_due(raw, api, clock):
    _fresh(raw, "2026-10-10")
    _fresh(raw, "2026-10-10", years=("2025", "2026"), source="sampleton-cf")

    verdict = _evaluate(raw, api, clock, _at("2026-10-12"), [COUNTY, TOWN])

    assert not verdict.is_due and verdict.problems == []
    assert verdict.body().startswith("Open Marin: no campaign export due (2026-10-12)")
    assert "NetFile API: ok" in verdict.body()


def test_the_body_says_exactly_what_to_do_per_item(raw, api, clock):
    _fresh(raw, "2026-10-10", years=("2023", "2024", "2025"))

    body = _evaluate(raw, api, clock, _at("2026-10-12")).body()

    assert body.startswith("Open Marin: campaign export due (1 item, 2026-10-12)")
    assert "Example County (EXC): https://netfile.example/public/EXC/campaign" in body
    assert 'click "Export Amended"' in body
    assert "2026 -> save as data/raw/example-cf/2026-10-12/2026.zip" in body
    assert "no export on file for this year" in body


# --- the API failing never silences the calendar ---------------------------------------------------------


@pytest.mark.parametrize("trouble,says", [
    ("down", "NetFile API unreachable"),
    ({"items": [], "count": 3}, "NetFile API changed shape"),
    ({"filings": "nope", "totalCount": 1, "items": [], "pageSize": 1, "currentPage": 1}, "changed shape"),
])
def test_an_api_failure_is_a_problem_and_the_calendar_still_rules(raw, api, clock, trouble, says):
    _fresh(raw, "2026-10-10", years=("2023", "2024", "2026"))
    _export(raw, "example-cf", "2026-04-14", "2025", rpt="2026-01-31")  # stale by the calendar
    if trouble == "down":
        api.down = OSError("connection refused")
    else:
        api.shape = trouble

    verdict = _evaluate(raw, api, clock, _at("2026-10-12"))

    assert len(verdict.problems) == 1 and says in verdict.problems[0]
    assert list(_due(verdict)) == [("example-cf", "2025")]
    assert "calendar rules only" in verdict.body()


def test_a_filing_with_an_unreadable_date_is_a_shape_change(raw, api, clock):
    _fresh(raw, "2026-10-10")
    api.add_filing("EXC", "9001", filed="2026-10-11", period_end="2024-06-30")
    api.filings["EXC"][0]["filingDate"] = "2026-10-11 around noon"
    verdict = _evaluate(raw, api, clock, _at("2026-10-12"))
    assert verdict.problems and "changed shape" in verdict.problems[0]


def test_the_body_is_capped(raw, api, clock):
    _fresh(raw, "2026-10-10")
    for i in range(400):
        _export(raw, "example-cf", "2026-10-11", f"bad-{i:03d}-2026-long-name", rpt="2026-10-11")
    assert len(_evaluate(raw, api, clock, _at("2026-10-12")).body()) <= due.BODY_CHARS


def test_the_real_registry_gives_the_alarm_everything_it_needs():
    import yaml
    registry = Path(__file__).resolve().parent.parent / "registry/netfile-sources.yaml"
    sources = yaml.safe_load(registry.read_text())["sources"]
    assert due.check_sources(sources) == []
    assert {s["agency_code"] for s in sources} == {"CMAR", "NVO"}
    assert all(s["portal_url"] == f"https://netfile.com/public/{s['agency_code']}/campaign" for s in sources)
