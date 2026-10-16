"""Votes Part B2, increment a: confirmed roster terms → Person nodes through a reviewed mapping table.

Fictional members (Ann Alder, Bea Birch, …) on a fictional council `body-x`; a fictional baseline export."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from votes_persons import (  # noqa: E402
    MappingError,
    Resolver,
    covers,
    load_mapping_answers,
    render_mapping_batch,
    validate_mapping,
)

BODY = "body-x"
BODY_ORG = {BODY: "org-body-x"}
BODY_FILING = {BODY: ("xco", "City Council")}
HASHES = {"mapping.json": "a" * 64, "drafts.json": "b" * 64, "batch-001.json": "c" * 64, "answers-001.txt": "d" * 64}


def _term(draft_id, key, start, end, start_kind="stated", end_kind="stated", member=None, seat="District 1"):
    return {"draft_id": draft_id, "key": key, "member": member or key.title(), "seat": seat,
            "start": start, "start_kind": start_kind, "end": end, "end_kind": end_kind if end else None}


def _drafts(*terms):
    return {BODY: {"body": BODY, "terms": list(terms)}}


def _confirmed(drafts):
    items = [{"item": str(i + 1), "draft_id": t["draft_id"], "body": b}
             for i, (b, t) in enumerate((b, t) for b in drafts for t in drafts[b]["terms"])]
    return items, [{"item": i["item"], "option": "confirm", "note": None} for i in items]


def _row(term, item, person_id, provenance, status="mapped", alternates=()):
    return {"item": item, "draft_id": term["draft_id"], "body": BODY, "key": term["key"], "member": term["member"],
            "term_start": term["start"], "term_end": term["end"], "status": status, "person_id": person_id,
            "provenance": list(provenance), "alternates": list(alternates), "notes": ""}


def _n(id_, labels, **props):
    return {"id": id_, "labels": labels, "properties": {"id": id_, **props}}


def _e(s, t, rel):
    return {"start_id": s, "end_id": t, "type": rel, "properties": {}}


NODES = [
    _n("person-ann-alder", ["Person"], name="Ann Alder"),
    _n("person-f700-ann-alder", ["Person"], name="Ann Alder"),
    _n("person-bea-birch", ["Person"], name="Bea Birch"),
    _n("person-birch-beatrice", ["Person"], name="Beatrice Birch"),
    _n("person-o-dell-di", ["Person"], name="Di O'Dell"),
    _n("seatservice-ann-alder-x-2021", ["SeatService"], started_at="2021-01-01", ended_at="2024-12-31"),
    _n("seatservice-ann-alder-y-2021", ["SeatService"], started_at="2021-01-01", ended_at="2024-12-31"),
    _n("seat-x-1", ["Seat"], name="District 1"),
    _n("seat-y-1", ["Seat"], name="District 1"),
    _n("org-body-x", ["Organization"], name="Example Council"),
    _n("org-body-y", ["Organization"], name="Other Board"),
    _n("filing-form700-x-2020-birch-bea-annual-council-member", ["Filing"], agency_id="xco",
       department="City Council, Example Finance Authority", job_title="Council Member"),
    _n("filing-form700-x-2020-birch-bea-annual-radio-board", ["Filing"], agency_id="xco",
       department="Example Radio Authority", job_title="Board Member"),
    _n("filing-form700-y-2020-birch-bea-annual-council", ["Filing"], agency_id="yco", department="City Council",
       job_title="Council Member"),
]
EDGES = [
    _e("seatservice-ann-alder-x-2021", "person-ann-alder", "HELD_BY"),
    _e("seatservice-ann-alder-x-2021", "seat-x-1", "FOR_SEAT"),
    _e("seat-x-1", "org-body-x", "AT_INSTITUTION"),
    _e("seatservice-ann-alder-y-2021", "person-ann-alder", "HELD_BY"),
    _e("seatservice-ann-alder-y-2021", "seat-y-1", "FOR_SEAT"),
    _e("seat-y-1", "org-body-y", "AT_INSTITUTION"),
    _e("filing-form700-x-2020-birch-bea-annual-council-member", "person-bea-birch", "FILED_BY"),
    _e("filing-form700-x-2020-birch-bea-annual-radio-board", "person-bea-birch", "FILED_BY"),
    _e("filing-form700-y-2020-birch-bea-annual-council", "person-bea-birch", "FILED_BY"),
]
SEAT = {"kind": "seat_service", "seat_service_id": "seatservice-ann-alder-x-2021"}
FILING = {"kind": "filing", "filing_id": "filing-form700-x-2020-birch-bea-annual-council-member"}
RADIO = {"kind": "filing", "filing_id": "filing-form700-x-2020-birch-bea-annual-radio-board"}


def _validate(rows, drafts, items, answers, nodes=NODES, edges=EDGES):
    return validate_mapping(rows, drafts, items, answers, nodes, edges, body_org=BODY_ORG, body_filing=BODY_FILING)

ALDER_A = _term("x-alder-a", "ALDER", "2020-01-01", "2021-01-05", start_kind="window", end_kind="bound")
ALDER_B = _term("x-alder-b", "ALDER", "2021-01-05", None, start_kind="bound")
BIRCH = _term("x-birch", "BIRCH", "2019-12-10", "2021-09-15", seat="District 5")
CEDAR = _term("x-cedar", "CEDAR", "2021-10-27", "2022-12-13", seat="District 5", end_kind="observed")


def _world(rows=None):
    drafts = _drafts(ALDER_A, ALDER_B, BIRCH, CEDAR)
    items, answers = _confirmed(drafts)
    rows = rows if rows is not None else [
        _row(ALDER_A, "1", "person-ann-alder", [{"kind": "same_member", "draft_id": "x-alder-b"}],
             alternates=["person-f700-ann-alder"]),
        _row(ALDER_B, "2", "person-ann-alder", [SEAT]),
        _row(BIRCH, "3", "person-bea-birch", [FILING]),
        _row(CEDAR, "4", "person-cy-cedar", [{"kind": "searched", "patterns": ["cedar"]}],
             status="verified_no_person"),
    ]
    return drafts, items, answers, rows


def _resolver(rows=None, mapping_answers=None, as_of="2026-10-14"):
    drafts, items, answers, rows = _world(rows)
    if mapping_answers is None:
        mapping_answers = [{"item": r["item"], "option": "confirm", "note": None} for r in rows]
    return Resolver(drafts, items, answers, rows, mapping_answers, as_of=as_of)


class TestCovers:
    """Starts are inclusive; a stated or observed end is inclusive, a bound end exclusive; open runs to as-of."""

    @pytest.mark.parametrize("kind, date, want", [
        ("stated", "2022-12-13", True), ("observed", "2022-12-13", True), ("bound", "2022-12-13", False),
        ("bound", "2022-12-12", True), ("stated", "2022-12-14", False)])
    def test_end_kinds(self, kind, date, want):
        assert covers(_term("t", "ALDER", "2020-01-01", "2022-12-13", end_kind=kind), date, as_of="2026-10-14") is want

    @pytest.mark.parametrize("kind", ["stated", "bound", "window"])
    def test_start_is_inclusive(self, kind):
        t = _term("t", "ALDER", "2020-01-01", "2022-12-13", start_kind=kind)
        assert covers(t, "2020-01-01", as_of="2026-10-14") and not covers(t, "2019-12-31", as_of="2026-10-14")

    def test_open_end_runs_through_as_of_only(self):
        t = _term("t", "ALDER", "2020-01-01", None)
        assert covers(t, "2026-10-14", as_of="2026-10-14") and not covers(t, "2026-10-15", as_of="2026-10-14")


def _confirm_all(rows):
    return [{"item": r["item"], "option": "confirm", "note": None} for r in rows]


class TestResolver:
    def test_in_term(self):
        assert _resolver().resolve(BODY, "BIRCH", "2020-06-09") == ("ok", "person-bea-birch", "x-birch")

    @pytest.mark.parametrize("date, draft", [("2021-01-04", "x-alder-a"), ("2021-01-05", "x-alder-b"),
                                             ("2021-01-06", "x-alder-b")])
    def test_consecutive_terms_with_a_bound_end(self, date, draft):
        assert _resolver().resolve(BODY, "ALDER", date) == ("ok", "person-ann-alder", draft)

    def _shared_date(self, person_a):
        """Alder's first term ends `stated` on the day the second starts: both cover 2021-01-05."""
        a = {**ALDER_A, "end_kind": "stated"}
        drafts = _drafts(a, ALDER_B, BIRCH, CEDAR)
        items, answers = _confirmed(drafts)
        _, _, _, rows = _world()
        rows[0] = {**rows[0], "person_id": person_a,
                   "provenance": rows[0]["provenance"] if person_a == "person-ann-alder" else [],
                   "reviewer_basis": "fictional"}
        return Resolver(drafts, items, answers, rows, _confirm_all(rows), as_of="2026-10-14")

    def test_shared_date_same_person_resolves(self):
        r = self._shared_date("person-ann-alder")
        assert r.resolve(BODY, "ALDER", "2021-01-05") == ("ok", "person-ann-alder", "x-alder-b")

    def test_shared_date_different_persons_is_ambiguous_only_that_day(self):
        r = self._shared_date("person-f700-ann-alder")
        assert r.resolve(BODY, "ALDER", "2021-01-05") == ("held", "ambiguous_person")
        assert r.resolve(BODY, "ALDER", "2021-01-04") == ("ok", "person-f700-ann-alder", "x-alder-a")
        assert r.resolve(BODY, "ALDER", "2021-01-06") == ("ok", "person-ann-alder", "x-alder-b")

    def test_boundary_days(self):
        r = _resolver()
        assert r.resolve(BODY, "BIRCH", "2021-09-15")[0] == "ok"  # stated end, inclusive
        assert r.resolve(BODY, "CEDAR", "2022-12-13")[0] == "ok"  # observed end, inclusive
        assert r.resolve(BODY, "CEDAR", "2021-10-27")[0] == "ok"  # stated start
        assert r.resolve(BODY, "ALDER", "2020-01-01")[0] == "ok"  # window start

    def test_between_terms_and_after_the_last(self):
        r = _resolver()
        assert r.resolve(BODY, "BIRCH", "2021-09-16") == ("held", "out_of_term")
        assert r.resolve(BODY, "CEDAR", "2023-01-10") == ("held", "out_of_term")
        assert r.resolve(BODY, "ALDER", "2019-12-31") == ("held", "out_of_term")
        assert r.resolve(BODY, "ALDER", "2026-10-15") == ("held", "out_of_term")  # open term, after as-of

    def test_vacancy_has_no_voter(self):
        # District 5 is vacant 2021-09-16 → 2021-10-26: neither of its members resolves on a date in it
        r = _resolver()
        assert r.resolve(BODY, "BIRCH", "2021-10-01") == ("held", "out_of_term")
        assert r.resolve(BODY, "CEDAR", "2021-10-01") == ("held", "out_of_term")

    def test_typo_key_is_never_matched_fuzzily(self):
        r = _resolver()
        assert r.resolve(BODY, "BIRCHH", "2020-06-09") == ("held", "unknown_key")
        assert r.resolve(BODY, "birch", "2020-06-09") == ("held", "unknown_key")
        assert r.resolve("body-y", "BIRCH", "2020-06-09") == ("held", "unknown_key")

    def test_no_person_resolves_to_the_new_node(self):
        assert _resolver().resolve(BODY, "CEDAR", "2022-01-11") == ("ok", "person-cy-cedar", "x-cedar")

    @pytest.mark.parametrize("option", ["reject", "defer", "correct"])
    def test_an_unconfirmed_mapping_holds(self, option):
        _, _, _, rows = _world()
        answers = [{"item": r["item"], "option": option if r["item"] == "3" else "confirm",
                    "note": "x" if option == "correct" else None} for r in rows]
        r = _resolver(mapping_answers=answers)
        assert r.resolve(BODY, "BIRCH", "2020-06-09") == ("held", "missing_mapping")
        assert r.resolve(BODY, "ALDER", "2020-06-09")[0] == "ok"

    def test_an_unanswered_mapping_holds(self):
        r = _resolver(mapping_answers=[{"item": "1", "option": "confirm", "note": None}])
        assert r.resolve(BODY, "ALDER", "2020-06-09") == ("ok", "person-ann-alder", "x-alder-a")
        assert r.resolve(BODY, "ALDER", "2022-06-09") == ("held", "missing_mapping")

    def test_missing_mapping_row_holds(self):
        drafts, items, answers, rows = _world()
        rows[2] = {**rows[2], "status": "missing_mapping", "person_id": None, "provenance": []}
        r = Resolver(drafts, items, answers, rows, _confirm_all(rows), as_of="2026-10-14")
        assert r.resolve(BODY, "BIRCH", "2020-06-09") == ("held", "missing_mapping")

    def test_only_confirmed_roster_terms_count(self):
        drafts, items, answers, rows = _world()
        answers = [{**a, "option": "reject"} if a["item"] == "3" else a for a in answers]
        rows = [x for x in rows if x["item"] != "3"]
        r = Resolver(drafts, items, answers, rows, _confirm_all(rows), as_of="2026-10-14")
        assert r.resolve(BODY, "BIRCH", "2020-06-09") == ("held", "unknown_key")

    def test_nearest_term(self):
        r = _resolver()
        assert r.nearest_term(BODY, "BIRCH", "2021-10-01")["draft_id"] == "x-birch"
        assert r.nearest_term(BODY, "CEDAR", "2021-10-01")["draft_id"] == "x-cedar"
        assert r.nearest_term(BODY, "BIRCHH", "2021-10-01") is None


class TestValidateMapping:
    def test_the_world_is_valid(self):
        drafts, items, answers, rows = _world()
        assert _validate(rows, drafts, items, answers) == []

    def test_every_confirmed_term_has_exactly_one_row(self):
        drafts, items, answers, rows = _world()
        assert any("x-cedar has no mapping row" in p for p in _validate(rows[:3], drafts, items, answers))
        assert any("x-birch has 2 mapping rows" in p for p in _validate(rows + [rows[2]], drafts, items, answers))
        answers = [{**a, "option": "reject"} if a["item"] == "4" else a for a in answers]
        assert any("x-cedar is not a confirmed term" in p for p in _validate(rows, drafts, items, answers))

    def test_term_fields_must_equal_the_draft(self):
        drafts, items, answers, rows = _world()
        rows[2] = {**rows[2], "term_end": "2021-09-30"}
        assert any("x-birch: term_end" in p for p in _validate(rows, drafts, items, answers))

    def test_person_must_exist_and_be_a_person(self):
        drafts, items, answers, rows = _world()
        for bad in ("person-nobody", "org-body-x"):
            rows2 = [{**r, "person_id": bad} if r["item"] == "3" else r for r in rows]
            assert any("not a Person" in p for p in _validate(rows2, drafts, items, answers))

    def test_seat_service_must_be_held_by_the_person_and_belong_to_the_body(self):
        drafts, items, answers, rows = _world()
        wrong_person = [{**r, "provenance": [SEAT]} if r["item"] == "3" else r for r in rows]
        assert any("is not HELD_BY person-bea-birch" in p for p in _validate(wrong_person, drafts, items, answers))
        other_body = [{**r, "provenance": [{"kind": "seat_service", "seat_service_id": "seatservice-ann-alder-y-2021"}]}
                      if r["item"] == "2" else r for r in rows]
        assert any("not a seat of body-x" in p for p in _validate(other_body, drafts, items, answers))

    def test_filing_must_be_filed_by_the_person(self):
        drafts, items, answers, rows = _world()
        wrong = [{**r, "provenance": [FILING]} if r["item"] == "2" else r for r in rows]
        assert any("is not FILED_BY person-ann-alder" in p for p in _validate(wrong, drafts, items, answers))
        missing = [{**r, "provenance": [{"kind": "filing", "filing_id": "filing-nope"}]} if r["item"] == "3" else r
                   for r in rows]
        assert any("is not FILED_BY" in p for p in _validate(missing, drafts, items, answers))

    @pytest.mark.parametrize("filing", [RADIO, {"kind": "filing", "filing_id": "filing-form700-y-2020-birch-bea-annual-council"}])
    def test_a_filing_that_does_not_name_the_body_is_no_proof(self, filing):
        drafts, items, answers, rows = _world()
        weak = [{**r, "provenance": [filing]} if r["item"] == "3" else r for r in rows]
        assert any("x-birch: nothing proves the body" in p for p in _validate(weak, drafts, items, answers))
        based = [{**r, "provenance": [filing], "reviewer_basis": "appointed to the radio board as a councilmember"}
                 if r["item"] == "3" else r for r in rows]
        assert _validate(based, drafts, items, answers) == []

    def test_same_member_must_point_at_a_body_proved_row(self):
        drafts, items, answers, rows = _world()
        bare = [{**r, "provenance": []} if r["item"] == "3" else r for r in rows]
        assert any("x-birch: nothing proves the body" in p for p in _validate(bare, drafts, items, answers))
        chain = [{**r, "provenance": [{"kind": "same_member", "draft_id": "x-alder-a"}]} if r["item"] == "2" else r
                 for r in rows]
        assert any("same_member" in p for p in _validate(chain, drafts, items, answers))
        other = [{**r, "provenance": [{"kind": "same_member", "draft_id": "x-birch"}]} if r["item"] == "1" else r
                 for r in rows]
        assert any("same_member" in p for p in _validate(other, drafts, items, answers))

    def test_different_persons_for_one_member_are_allowed(self):
        drafts, items, answers, rows = _world()
        rows[0] = {**rows[0], "person_id": "person-f700-ann-alder", "provenance": [], "reviewer_basis": "fictional"}
        assert _validate(rows, drafts, items, answers) == []

    def test_verified_no_person_is_rechecked(self):
        drafts, items, answers, rows = _world()
        taken = [{**r, "person_id": "person-bea-birch"} if r["item"] == "4" else r for r in rows]
        assert any("already exists" in p for p in _validate(taken, drafts, items, answers))
        found = [{**r, "provenance": [{"kind": "searched", "patterns": ["cedar", "beatrice"]}]}
                 if r["item"] == "4" else r for r in rows]
        assert any("matches baseline Person person-birch-beatrice" in p for p in _validate(found, drafts, items, answers))
        for pats in ([], ["xyz"], [""]):
            bad = [{**r, "provenance": [{"kind": "searched", "patterns": pats}]} if r["item"] == "4" else r
                   for r in rows]
            assert any("must include the surname" in p for p in _validate(bad, drafts, items, answers))

    def test_search_ignores_punctuation(self):
        o_dell = _term("x-odell", "O'DELL", "2021-10-27", None, seat="District 3")
        drafts = _drafts(ALDER_A, ALDER_B, BIRCH, CEDAR, o_dell)
        items, answers = _confirmed(drafts)
        rows = _world()[3] + [_row(o_dell, "5", "person-di-odell", [{"kind": "searched", "patterns": ["odell"]}],
                                   status="verified_no_person")]
        assert any("matches baseline Person person-o-dell-di" in p for p in _validate(rows, drafts, items, answers))

    def test_alternates_must_exist(self):
        drafts, items, answers, rows = _world()
        rows[0] = {**rows[0], "alternates": ["person-ghost"]}
        assert any("alternate person-ghost" in p for p in _validate(rows, drafts, items, answers))

    def test_unknown_status_and_provenance_kind(self):
        drafts, items, answers, rows = _world()
        rows[2] = {**rows[2], "status": "guessed"}
        assert any("status" in p for p in _validate(rows, drafts, items, answers))
        drafts, items, answers, rows = _world()
        rows[2] = {**rows[2], "provenance": [FILING, {"kind": "name_slug"}]}
        assert any("provenance kind" in p for p in _validate(rows, drafts, items, answers))


class TestBatch:
    def _md(self, rows=None):
        rows = rows or _world()[3]
        return render_mapping_batch("map-001", rows, NODES, EDGES, body_org=BODY_ORG, body_filing=BODY_FILING,
                                    input_hashes=HASHES)

    def test_render_lists_each_row_with_evidence_in_words(self):
        md, batch = self._md()
        assert md.startswith("# Person mapping review — map-001")
        assert ("SeatService seatservice-ann-alder-x-2021 (2021-01-01 → 2024-12-31, overlaps this term) is HELD_BY "
                "this Person and is a seat of body-x") in md
        assert ("Form 700 filing filing-form700-x-2020-birch-bea-annual-council-member (City Council, Example Finance "
                "Authority / Council Member) is FILED_BY this Person and names body-x") in md
        assert "Same Person as item 2 (x-alder-b)" in md
        assert "No Person node matches “cedar”; a new Person person-cy-cedar is created" in md
        assert "person-f700-ann-alder (Ann Alder)" in md
        assert "Answer: `3 confirm` · `3 correct: …` · `3 reject` · `3 defer`" in md
        assert [i["item"] for i in batch["items"]] == ["1", "2", "3", "4"]
        assert batch["inputs"] == HASHES

    def test_weak_rows_and_split_members_are_flagged(self):
        _, _, _, rows = _world()
        rows[2] = {**rows[2], "provenance": [RADIO], "reviewer_basis": "appointed to the radio board as a councilmember"}
        rows[0] = {**rows[0], "person_id": "person-f700-ann-alder", "provenance": [], "reviewer_basis": "fictional"}
        md, _ = self._md(rows)
        assert ("related role only: Example Radio Authority / Board Member — it does not name body-x") in md
        assert "**WEAK — rests on your judgment:** appointed to the radio board as a councilmember" in md
        assert "**Split member:** ALDER maps to different Persons in different terms" in md

    def test_answers_are_bound_to_the_reviewed_inputs(self):
        _, batch = self._md()
        text = "batch map-001\n1 confirm\n3 correct: use person-birch-beatrice\n"
        assert load_mapping_answers(text, batch, HASHES) == [
            {"item": "1", "option": "confirm", "note": None},
            {"item": "3", "option": "correct", "note": "use person-birch-beatrice"}]
        with pytest.raises(MappingError, match="mapping.json changed"):
            load_mapping_answers(text, batch, {**HASHES, "mapping.json": "e" * 64})
        with pytest.raises(MappingError, match="answers-001.txt changed"):
            load_mapping_answers(text, batch, {**HASHES, "answers-001.txt": "e" * 64})
        with pytest.raises(MappingError, match="batch map-001"):
            load_mapping_answers("batch roster-001\n1 confirm\n", batch, HASHES)
