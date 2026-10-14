"""Votes Part A, increment f: roster evidence for review — never written to the graph.

Fictional members (Ann Alder, Bea Birch, …) on a fictional five-seat council."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from votes_roster import (  # noqa: E402
    RosterError,
    coverage,
    observed_service,
    parse_answers,
    render_batch,
    term_evidence,
    validate_seatservices,
    verify_drafts,
)
from votes_text import CanonicalText  # noqa: E402

NOV = "novato-city-council"


class TestTermEvidence:
    def test_kinds_of_term_evidence_in_minutes(self):
        ct = CanonicalText.from_lines([
            "G.1. Adopt a resolution accepting the results of the Canvass of Election Returns for Districts 1 and 3",
            "held on November 5, 2019 and declaring the results thereof.",
            "J.1. Reorganize the Council to appoint a new Mayor and Mayor Pro Tem.",
            "Councilmember Bea Birch announced that she would be resigning from the City Council effective",
            "September 15, 2021.",
            "The City Clerk administered the oath of office to Councilmember Cy Cedar.",
            "The Council voted to appoint Di Dogwood to fill the vacancy in District 5.",
            "The Council approved the minutes."])
        kinds = [e["kind"] for e in term_evidence(ct)]
        assert kinds == ["canvass", "reorganization", "resignation", "oath", "vacancy"]
        e = term_evidence(ct)[0]
        assert "Canvass of Election Returns" in ct.text[e["span"]["start"]:e["span"]["end"]]


class TestObservedService:
    def test_first_and_last_seen_and_name_forms(self):
        rolls = [
            ("2020-01-14", "COUNCIL PRESENT: Mayor Ann Alder, Councilmember Bea Birch"),
            ("2020-06-09", "COUNCIL PRESENT: Councilmember Ann Alder, Mayor Bea Birch"),
            ("2021-02-09", "COUNCIL PRESENT: Councilmember Ann Alder"),
        ]
        out = observed_service(rolls)
        assert out["ALDER"]["first_seen"] == "2020-01-14" and out["ALDER"]["last_seen"] == "2021-02-09"
        assert out["ALDER"]["names"] == ["Ann Alder"] and out["ALDER"]["titles"] == ["Councilmember", "Mayor"]
        assert out["BIRCH"]["last_seen"] == "2020-06-09" and out["BIRCH"]["meetings"] == 2

    def test_surname_only_titles_hyphen_breaks_and_non_names(self):
        rolls = [("2020-01-14", "Present: Supervisor Alder; Supervisor Birch-\n     Cedar\nAbsent: Supervisor Dogwood"),
                 ("2020-02-11", "COUNCIL PRESENT: Mayor Pro Tempore\n     Ed Elm, Mayor Pro Tempore, Supervisor Alder Absent")]
        out = observed_service(rolls)
        assert sorted(out) == ["ALDER", "BIRCH-CEDAR", "DOGWOOD", "ELM"]
        assert out["ELM"]["names"] == ["Ed Elm"] and out["ALDER"]["meetings"] == 2


def _draft(**over):
    term = {"draft_id": "rt-1", "member": "Ann Alder", "key": "ALDER", "seat": "District 1", "start": "2019-12-10",
            "end": None, "basis": "election", "confidence": "high", "notes": "",
            "evidence": [{"source": "minutes:m1", "quote": "Districts 1 and 3", "supports": ["start", "seat"]}]}
    term.update(over)
    return {"body": NOV, "terms": [term]}


SOURCES = {"minutes:m1": {"text": "accepting the results of the Canvass for Districts 1 and 3 held in 2019",
                          "sha256": "a" * 64, "url": None, "date": "2019-12-10"}}


class TestVerifyDrafts:
    def test_a_quote_found_in_its_source_verifies(self):
        assert verify_drafts(_draft(), SOURCES) == []

    def test_a_quote_not_in_its_source_fails(self):
        bad = _draft(evidence=[{"source": "minutes:m1", "quote": "Districts 2 and 4", "supports": ["start"]}])
        assert verify_drafts(bad, SOURCES)

    def test_an_unknown_source_fails(self):
        bad = _draft(evidence=[{"source": "web:nowhere", "quote": "x", "supports": ["start"]}])
        assert verify_drafts(bad, SOURCES)

    def test_a_start_or_end_without_supporting_evidence_fails(self):
        assert verify_drafts(_draft(evidence=[{"source": "minutes:m1", "quote": "Districts 1 and 3",
                                                "supports": ["seat"]}]), SOURCES)
        assert verify_drafts(_draft(end="2022-12-13"), SOURCES)

    def test_an_unstated_seat_needs_no_seat_evidence_but_says_so(self):
        ok = _draft(seat="District (unstated in the minutes)",
                    evidence=[{"source": "minutes:m1", "quote": "Districts 1 and 3", "supports": ["start"]}])
        assert verify_drafts(ok, SOURCES) == []

    def test_whitespace_in_quotes_is_normalized(self):
        ok = _draft(evidence=[{"source": "minutes:m1", "quote": "Districts  1\nand 3", "supports": ["start", "seat"]}])
        assert verify_drafts(ok, SOURCES) == []

    def test_source_count_is_capped_per_body(self):
        many = {f"web:{i}": {"text": "x", "sha256": "b" * 64, "url": f"https://example.invalid/{i}", "date": None}
                for i in range(41)}
        with pytest.raises(RosterError, match="40"):
            verify_drafts(_draft(), {**SOURCES, **many}, max_web_sources=40)


class TestSeatServices:
    def test_agree_disagree_and_no_evidence(self):
        drafts = _draft(end="2022-12-13", evidence=[
            {"source": "minutes:m1", "quote": "Districts 1 and 3", "supports": ["start", "seat", "end"]}])
        services = [
            {"id": "seatservice-ann-alder-x", "key": "ALDER", "seat": "District 1", "started_at": "2019-12-10",
             "ended_at": "2022-12-13"},
            {"id": "seatservice-ann-alder-y", "key": "ALDER", "seat": "District 1", "started_at": "2019-11-01",
             "ended_at": "2019-11-30"},
            {"id": "seatservice-zed-x", "key": "ZED", "seat": "District 4", "started_at": "2020-01-01",
             "ended_at": None},
        ]
        rows = {r["seatservice_id"]: r for r in validate_seatservices(drafts, services)}
        assert rows["seatservice-ann-alder-x"]["verdict"] == "agree"
        assert rows["seatservice-ann-alder-y"]["verdict"] == "disagree"
        assert set(rows["seatservice-ann-alder-y"]["differences"]) == {"started_at", "ended_at"}
        assert rows["seatservice-zed-x"]["verdict"] == "no_evidence"


class TestCoverage:
    def test_gaps_per_seat_over_the_window(self):
        drafts = {"body": NOV, "terms": [
            {"seat": "District 1", "start": "2019-01-01", "end": "2020-12-08", "key": "ALDER"},
            {"seat": "District 1", "start": "2020-12-08", "end": None, "key": "BIRCH"},
            {"seat": "District 2", "start": "2019-01-01", "end": "2021-09-15", "key": "CEDAR"},
            {"seat": "District 2", "start": "2021-11-09", "end": None, "key": "DOGWOOD"},
        ]}
        cov = coverage(drafts, ["District 1", "District 2", "District 3"], "2019-01-01", "2026-10-14")
        assert cov["District 1"]["gaps"] == []
        assert cov["District 2"]["gaps"] == [["2021-09-15", "2021-11-09"]]
        assert cov["District 3"]["gaps"] == [["2019-01-01", "2026-10-14"]]


class TestBatch:
    def _batch(self):
        drafts = _draft()
        return render_batch("roster-001", {"novato-city-council": drafts}, {"novato-city-council": []},
                            {"novato-city-council": {"District 1": {"terms": [], "gaps": []}}},
                            sources=SOURCES)

    def test_items_options_and_answer_lines(self):
        md, items = self._batch()
        assert items[0]["item"] == "1" and items[0]["draft_id"] == "rt-1"
        assert items[0]["options"] == ["confirm", "correct", "reject", "defer"]
        assert "batch roster-001" in md and "1 confirm" in md
        assert "Districts 1 and 3" in md

    def test_parse_answers(self):
        _, items = self._batch()
        ans = parse_answers("batch roster-001\n1 confirm\n", "roster-001", items)
        assert ans == [{"item": "1", "option": "confirm", "note": None}]
        ans = parse_answers("batch roster-001\n1 correct: start is 2019-12-17\n", "roster-001", items)
        assert ans[0]["option"] == "correct" and ans[0]["note"] == "start is 2019-12-17"
        for bad in ("batch roster-002\n1 confirm", "batch roster-001\n9 confirm", "batch roster-001\n1 maybe",
                    "batch roster-001\n1 correct", "1 confirm", "batch roster-001\n1 confirm\n1 reject"):
            with pytest.raises(RosterError):
                parse_answers(bad, "roster-001", items)
