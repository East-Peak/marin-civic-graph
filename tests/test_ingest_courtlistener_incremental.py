"""CourtListener weekly pulls are incremental: newest-first, stop at a cutoff, merge onto the last good set.

Since May 2026 a CourtListener account gets ~5 requests/minute and 50-100/hour. A full
refetch (~90 pages over 13 queries) is throttled into a 429 every week. The history is
already staged in data/normalized/courtlistener-cases, so a weekly run only needs what
was filed since: each query ordered by dateFiled desc, stopping at the first record
older than the cutoff (the newest known filing minus an overlap), merged onto the
previous set. Because a merge never shrinks, the floors can't see a broken pull, so the
pull proves itself: the overlap guarantees the newest known case is re-found, and a
pull that re-finds no known case fails. Every transport here is a fake.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ingest_courtlistener_cases as cl  # noqa: E402
import refresh_weekly  # noqa: E402


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(cl.time, "sleep", slept.append)
    return slept


def _raw(docket_id: int, filed: str | None, name: str = "Doe v. City of San Rafael") -> dict:
    return {"docket_id": docket_id, "docketNumber": f"3:26-cv-{docket_id:05d}", "caseName": name,
            "court": "District Court, N.D. California", "court_id": "cand", "dateFiled": filed,
            "dateTerminated": None, "cause": "42:1983 Civil Rights Act", "assignedTo": None,
            "docket_absolute_url": f"/docket/{docket_id}/x/"}


class FakePages:
    """Serves ``pages`` in order per query; records each call's params."""

    def __init__(self, pages: list[list[dict]]):
        self.pages, self.calls = pages, []

    def __call__(self, query, cursor=None, order_by="score desc"):
        n = sum(1 for q, _, _ in self.calls if q == query)
        self.calls.append((query, cursor, order_by))
        results = self.pages[n] if n < len(self.pages) else []
        more = n + 1 < len(self.pages)
        return {"results": results, "next": f"https://x.test/?cursor=c{n + 1}" if more else None}


# --- newest-first, stop at the cutoff -------------------------------------------


def test_a_since_query_walks_newest_first_and_stops_at_the_first_record_older_than_the_cutoff(monkeypatch):
    fake = FakePages([[_raw(1, "2026-09-20"), _raw(2, "2026-08-30")],
                      [_raw(3, "2026-08-10"), _raw(4, "2026-06-01")],
                      [_raw(5, "2026-05-01")]])
    monkeypatch.setattr(cl, "fetch_page", fake)

    got = list(cl.fetch_cases_for_query("q", since=date(2026, 8, 1)))

    assert [r["docket_id"] for r in got] == [1, 2, 3]
    assert len(fake.calls) == 2  # page 3 is never requested
    assert [cursor for _, cursor, _ in fake.calls] == [None, "c1"]
    assert all(order == "dateFiled desc" for _, _, order in fake.calls)


def test_an_undated_record_counts_as_older_than_any_cutoff(monkeypatch):
    fake = FakePages([[_raw(1, "2026-09-20"), _raw(2, None)], [_raw(3, "2026-09-19")]])
    monkeypatch.setattr(cl, "fetch_page", fake)

    assert [r["docket_id"] for r in cl.fetch_cases_for_query("q", since=date(2026, 8, 1))] == [1]
    assert len(fake.calls) == 1


def test_an_out_of_order_page_fails_rather_than_stopping_early_and_missing_a_case(monkeypatch):
    # Codex 2026-09-29: [known recent, old, unseen recent] would stop at "old" and never see
    # the unseen case; the pull still re-finds a known case, so nothing else would notice.
    fake = FakePages([[_raw(1, "2026-09-01"), _raw(2, "2026-01-01"), _raw(3, "2026-09-10")]])
    monkeypatch.setattr(cl, "fetch_page", fake)

    with pytest.raises(ValueError, match="not newest-first"):
        list(cl.fetch_cases_for_query("q", since=date(2026, 8, 1)))


def test_a_dated_record_after_an_undated_one_is_out_of_order(monkeypatch):
    monkeypatch.setattr(cl, "fetch_page", FakePages([[_raw(1, "2026-09-01"), _raw(2, None), _raw(3, "2026-08-20")]]))

    with pytest.raises(ValueError, match="not newest-first"):
        list(cl.fetch_cases_for_query("q", since=date(2026, 8, 1)))


def test_an_incremental_query_with_no_results_at_all_fails(monkeypatch):
    # Every query phrase has matched dockets before; an empty first page is a broken
    # response, and one healthy query must not mask it.
    monkeypatch.setattr(cl, "fetch_page", FakePages([[]]))

    with pytest.raises(ValueError, match="no results at all"):
        list(cl.fetch_cases_for_query("q", since=date(2026, 8, 1)))


def test_a_full_query_keeps_relevance_order_and_every_page(monkeypatch):
    fake = FakePages([[_raw(1, "2020-01-01")], [_raw(2, "2019-01-01")]])
    monkeypatch.setattr(cl, "fetch_page", fake)

    assert [r["docket_id"] for r in cl.fetch_cases_for_query("q")] == [1, 2]
    assert [order for _, _, order in fake.calls] == ["score desc", "score desc"]


def test_fetch_page_sends_the_requested_order(monkeypatch):
    seen = []

    def get(url, params=None, timeout=None, headers=None):
        seen.append(params)
        response = cl.requests.Response()
        response.status_code, response._content = 200, b'{"results": []}'
        return response
    monkeypatch.setattr(cl.requests, "get", get)

    cl.fetch_page("q", order_by="dateFiled desc")

    assert seen[0]["order_by"] == "dateFiled desc"


# --- pacing: every request, across queries, is spaced -----------------------------


class Clock:
    def __init__(self, monkeypatch, slept):
        self.now = 1000.0
        monkeypatch.setattr(cl, "monotonic", lambda: self.now)
        monkeypatch.setattr(cl, "sleep", self.sleep)
        monkeypatch.setattr(cl, "_last_request_at", None)
        self.slept = slept

    def sleep(self, secs):
        self.slept.append(secs)
        self.now += secs


def _ok_get(calls):
    def get(url, params=None, timeout=None, headers=None):
        calls.append(params)
        response = cl.requests.Response()
        response.status_code, response._content = 200, b'{"results": []}'
        return response
    return get


def test_every_request_is_spaced_at_least_the_rate_limit_apart(monkeypatch, no_sleep):
    Clock(monkeypatch, no_sleep)
    calls = []
    monkeypatch.setattr(cl.requests, "get", _ok_get(calls))

    for query in ("a", "b", "c"):
        cl.fetch_page(query)

    assert len(calls) == 3 and no_sleep == [cl.RATE_LIMIT_SECS, cl.RATE_LIMIT_SECS]


def test_a_retried_request_is_paced_too(monkeypatch, no_sleep):
    import net_retry
    Clock(monkeypatch, no_sleep)
    monkeypatch.setattr(net_retry, "sleep", lambda s: None)  # the retry backoff itself
    calls = []
    ok = _ok_get(calls)

    def flaky(url, params=None, timeout=None, headers=None):
        if not calls:
            calls.append("timeout")
            raise cl.requests.ReadTimeout("read timed out")
        return ok(url, params=params, timeout=timeout, headers=headers)
    monkeypatch.setattr(cl.requests, "get", flaky)

    cl.fetch_page("a")

    assert len(calls) == 2 and no_sleep == [cl.RATE_LIMIT_SECS]


def test_the_rate_limit_fits_five_requests_a_minute():
    assert cl.RATE_LIMIT_SECS >= 12


# --- the cutoff and the merge -------------------------------------------------------


def _case_node(case_id: str, filed: str | None, name: str = "Old v. County of Marin") -> dict:
    return {"id": case_id, "node_type": "Case", "labels": ["Case"], "display_label": name,
            "properties": {"case_name": name, "date_filed": filed, "source": "courtlistener"}}


def test_the_cutoff_is_the_newest_known_filing_minus_the_overlap():
    nodes = [_case_node("case-cl-1", "2026-08-06"), _case_node("case-cl-2", "2025-01-01"),
             _case_node("case-cl-3", None), {"id": "org-x", "node_type": "Organization", "properties": {}}]

    assert cl.incremental_since(nodes, today=date(2026, 9, 29)) == date(2026, 8, 6) - cl.INCREMENTAL_OVERLAP
    assert cl.INCREMENTAL_OVERLAP.days >= 30


def test_a_malformed_or_future_date_in_the_previous_set_is_ignored_for_the_cutoff():
    nodes = [_case_node("case-cl-1", "2026-08-06"), _case_node("case-cl-2", "not-a-date"),
             _case_node("case-cl-3", "2099-01-01")]

    assert cl.incremental_since(nodes, today=date(2026, 9, 29)) == date(2026, 8, 6) - cl.INCREMENTAL_OVERLAP


def test_no_dated_case_means_no_cutoff():
    with pytest.raises(ValueError, match="full"):
        cl.incremental_since([{"id": "org-x", "node_type": "Organization", "properties": {}}])


def test_the_merge_keeps_every_previous_record_and_lets_a_refetched_one_win():
    prev_nodes = [_case_node("case-cl-1", "2026-08-06", "Old name"), _case_node("case-cl-2", "2025-01-01")]
    prev_edges = [{"source_id": "case-cl-1", "target_id": "org-court-cand", "relationship_type": "HEARD_IN",
                   "properties": {}}]
    new_nodes = [_case_node("case-cl-1", "2026-08-06", "New name"), _case_node("case-cl-9", "2026-09-20")]
    new_edges = [{"source_id": "case-cl-1", "target_id": "org-court-cand", "relationship_type": "HEARD_IN",
                  "properties": {"x": 1}},
                 {"source_id": "case-cl-9", "target_id": "org-court-cand", "relationship_type": "HEARD_IN",
                  "properties": {}}]

    nodes, edges = cl.merge_graph(prev_nodes, prev_edges, new_nodes, new_edges)

    assert [n["id"] for n in nodes] == ["case-cl-1", "case-cl-2", "case-cl-9"]
    assert nodes[0]["display_label"] == "New name"
    assert len(edges) == 2 and edges[0]["properties"] == {"x": 1}


def test_a_refetched_case_replaces_its_old_edges_rather_than_accumulating_them():
    prev_edges = [{"source_id": "case-cl-1", "target_id": "org-city-of-novato", "relationship_type": "PARTY_TO",
                   "properties": {}},
                  {"source_id": "case-cl-2", "target_id": "org-court-cand", "relationship_type": "HEARD_IN",
                   "properties": {}}]
    new_edges = [{"source_id": "case-cl-1", "target_id": "org-city-of-san-rafael", "relationship_type": "PARTY_TO",
                  "properties": {}}]

    _, edges = cl.merge_graph([_case_node("case-cl-1", "2026-08-06"), _case_node("case-cl-2", "2025-01-01")],
                              prev_edges, [_case_node("case-cl-1", "2026-08-06")], new_edges)

    assert {(e["source_id"], e["target_id"]) for e in edges} == {
        ("case-cl-1", "org-city-of-san-rafael"), ("case-cl-2", "org-court-cand")}


# --- the CLI ------------------------------------------------------------------------


def _write(dir_: Path, nodes: list[dict], edges: list[dict]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    (dir_ / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges))


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_incremental_from_writes_the_previous_set_plus_what_was_filed_since(monkeypatch, tmp_path):
    prev = tmp_path / "prev"
    _write(prev, [_case_node("case-cl-1", "2026-08-06")], [])
    fake = FakePages([[_raw(9, "2026-09-20"), _raw(1, "2026-08-06"), _raw(8, "2026-01-01")]])
    monkeypatch.setattr(cl, "fetch_page", fake)
    monkeypatch.setattr(cl, "QUERIES", ['"City of San Rafael"'])
    out = tmp_path / "out"

    assert cl.main(["--incremental-from", str(prev), "--output-dir", str(out)]) == 0

    ids = {n["id"] for n in _read(out / "nodes.jsonl")}
    assert {"case-cl-1", "case-cl-9"} <= ids and "case-cl-8" not in ids
    assert all(order == "dateFiled desc" for _, _, order in fake.calls)


@pytest.mark.parametrize("pages", [
    [[_raw(8, "2026-01-01")]],                          # order_by ignored: relevance order, old first
    [[{**_raw(1, None), "date_filed_renamed": "2026-08-06"}]],  # dateFiled renamed
    [[_raw(9, "2026-09-20")]],                          # new cases, but not one known case re-found
])
def test_a_pull_that_re_finds_no_known_case_fails_instead_of_passing_as_an_unchanged_set(
        pages, monkeypatch, tmp_path, capsys):
    prev = tmp_path / "prev"
    _write(prev, [_case_node("case-cl-1", "2026-08-06")], [])
    monkeypatch.setattr(cl, "fetch_page", FakePages(pages))
    monkeypatch.setattr(cl, "QUERIES", ['"City of San Rafael"'])
    out = tmp_path / "out"

    assert cl.main(["--incremental-from", str(prev), "--output-dir", str(out)]) != 0
    assert not (out / "nodes.jsonl").exists()
    assert "re-found none" in capsys.readouterr().err


def test_one_healthy_query_cannot_mask_another_that_returned_nothing(monkeypatch, tmp_path, capsys):
    prev = tmp_path / "prev"
    _write(prev, [_case_node("case-cl-1", "2026-08-06")], [])
    healthy = FakePages([[_raw(1, "2026-08-06")]])
    monkeypatch.setattr(cl, "fetch_page", lambda q, cursor=None, order_by="score desc":
                        healthy(q, cursor, order_by) if q == "a" else {"results": [], "next": None})
    monkeypatch.setattr(cl, "QUERIES", ["a", "b"])
    out = tmp_path / "out"

    assert cl.main(["--incremental-from", str(prev), "--output-dir", str(out)]) != 0
    assert not (out / "nodes.jsonl").exists()
    assert "no results at all" in capsys.readouterr().err


def test_incremental_from_an_empty_or_missing_set_refuses_rather_than_silently_refetching_everything(
        monkeypatch, tmp_path, capsys):
    fake = FakePages([[_raw(9, "2026-09-20")]])
    monkeypatch.setattr(cl, "fetch_page", fake)

    assert cl.main(["--incremental-from", str(tmp_path / "missing"), "--output-dir", str(tmp_path / "o")]) != 0
    assert fake.calls == [] and "full" in capsys.readouterr().err


def test_incremental_from_cannot_be_combined_with_load_from(tmp_path):
    with pytest.raises(SystemExit):
        cl.main(["--load-from", str(tmp_path), "--incremental-from", str(tmp_path)])


def test_the_weekly_runner_stages_courtlistener_incrementally_from_its_last_good_output():
    src = refresh_weekly.STAGED_SOURCES["courtlistener"]
    assert src.args == ("--incremental-from", f"data/normalized/{src.normalized}")
