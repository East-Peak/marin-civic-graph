"""Which sources and meetings the weekly agenda-items stage may touch (scripts/agenda_items.py).

A source is eligible from its registry entry alone: weekly, not Granicus, an `agenda_items` block, and a parser
qualified at its current version. A meeting is a candidate when its body is confirmed, it has exactly one agenda
Record that no other meeting shares, and it has no AgendaItems. Fixtures are fictional (Lakeport).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agenda_items as ai  # noqa: E402
from agenda_parsers import Parser  # noqa: E402

SID = "lakeport-town-council"
INST = "org-lakeport-town-council"
PARSERS = {"outline": Parser(version=2, parse=lambda text: {"printed_date": None, "items": []})}
BLOCK = {"artifact": "agenda", "parser": "outline", "hosts": ["www.lakeport.example"],
         "body": {"category": ["Town Council"]}, "qualified": {"parser": "outline", "version": 2, "report": "r"}}


def _config(**extra):
    config = {"id": SID, "adapter": "civicplus", "schedule": "weekly", "institution_id": INST,
              "backfill_from": "2019-01-01", "agenda_items": dict(BLOCK)}
    config.update(extra)
    return config


# --- eligibility -------------------------------------------------------------------------------------


def test_a_weekly_qualified_source_is_eligible():
    assert ai.eligibility(_config(), PARSERS) == (True, "eligible")


@pytest.mark.parametrize("change, reason", [
    ({"schedule": "manual"}, "schedule manual"),
    ({"schedule": "saved-page"}, "schedule saved-page"),
    ({"adapter": "granicus"}, "adapter granicus"),
    ({"agenda_items": None}, "no agenda_items block"),
])
def test_a_source_off_the_weekly_path_is_not_eligible(change, reason):
    config = {k: v for k, v in _config(**change).items() if v is not None}
    assert ai.eligibility(config, PARSERS) == (False, reason)


def test_a_granicus_source_is_never_eligible_even_if_configured_and_weekly():
    assert ai.eligibility(_config(adapter="granicus"), PARSERS)[0] is False


def test_an_unqualified_parser_is_not_selected():
    block = {k: v for k, v in BLOCK.items() if k != "qualified"}
    assert ai.eligibility(_config(agenda_items=block), PARSERS) == (False, "parser not qualified")


def test_a_qualification_for_an_older_parser_version_no_longer_counts():
    block = {**BLOCK, "qualified": {"parser": "outline", "version": 1, "report": "r"}}
    assert ai.eligibility(_config(agenda_items=block), PARSERS) == (False, "parser not qualified")


def test_a_qualification_for_another_parser_does_not_count():
    block = {**BLOCK, "qualified": {"parser": "flat", "version": 2, "report": "r"}}
    assert ai.eligibility(_config(agenda_items=block), PARSERS) == (False, "parser not qualified")


def test_an_unknown_parser_is_not_eligible():
    block = {**BLOCK, "parser": "nonesuch", "qualified": {"parser": "nonesuch", "version": 2, "report": "r"}}
    assert ai.eligibility(_config(agenda_items=block), PARSERS) == (False, "unknown parser nonesuch")


@pytest.mark.parametrize("missing", ["artifact", "hosts", "body"])
def test_an_incomplete_block_is_not_eligible(missing):
    block = {k: v for k, v in BLOCK.items() if k != missing}
    assert ai.eligibility(_config(agenda_items=block), PARSERS) == (False, f"agenda_items.{missing} missing")


def test_eligible_sources_reads_every_meeting_registry(tmp_path):
    import yaml

    (tmp_path / "registry").mkdir()
    (tmp_path / "registry" / "civicplus-sources.yaml").write_text(yaml.safe_dump({"sources": [_config()]}))
    (tmp_path / "registry" / "granicus-sources.yaml").write_text(yaml.safe_dump({"sources": [
        {**_config(), "id": "lakeport-granicus", "adapter": "granicus", "schedule": "saved-page"}]}))
    (tmp_path / "registry" / "netfile-sources.yaml").write_text(yaml.safe_dump({"sources": [{"id": "cf"}]}))
    verdicts = ai.eligible_sources(tmp_path, PARSERS)
    assert [(c["id"], ok, why) for c, ok, why in verdicts] == [  # registry order: granicus first
        ("lakeport-granicus", False, "adapter granicus"), ("lakeport-town-council", True, "eligible")]


# --- the body check ---------------------------------------------------------------------------------


def test_a_category_rule_reads_the_meetings_category():
    config = _config()
    assert ai.body_class(config, {"category": "Town Council", "title": "anything"}) == "council"
    assert ai.body_class(config, {"category": "Planning Commission", "title": "Town Council"}) == "other"
    assert ai.body_class(config, {"title": "Town Council"}) == "unconfirmed"  # no category: no evidence


def test_a_title_rule_needs_positive_evidence_and_names_other_bodies():
    config = _config(agenda_items={**BLOCK, "body": {"title": "Town Council", "other": "Committee|Group"}})
    assert ai.body_class(config, {"title": "Special Meeting of the Lakeport Town Council"}) == "council"
    assert ai.body_class(config, {"title": "Town Council Finance Committee"}) == "other"
    assert ai.body_class(config, {"title": "Design Review Group"}) == "other"
    assert ai.body_class(config, {"title": "Annual Budget Workshop"}) == "unconfirmed"


# --- candidates ----------------------------------------------------------------------------------------

AGENDA = "https://www.lakeport.example/AgendaCenter/ViewFile/Agenda/_{}"


def _meeting(day, *, category="Town Council", records=(), has_items=False, title=None):
    return {"props": {"meeting_date": day, "category": category, "title": title or f"Town Council {day}"},
            "records": [{"id": rid, "record_type": rtype, "source_url": url} for rid, rtype, url in records],
            "item_ids": ["agenda-item-x"] if has_items else []}


def _agenda(mid, n):
    return (f"record-{mid}-agenda", "meeting_agenda", AGENDA.format(n))


def test_candidates_are_council_meetings_with_one_unshared_agenda_and_no_items():
    meetings = {
        "meeting-1": _meeting("2026-10-06", records=[_agenda("meeting-1", 1)]),
        "meeting-2": _meeting("2026-09-15", records=[_agenda("meeting-2", 2)], has_items=True),
        "meeting-3": _meeting("2026-09-14", category="Planning Commission", records=[_agenda("meeting-3", 3)]),
        "meeting-4": _meeting("2018-12-04", records=[_agenda("meeting-4", 4)]),
        "meeting-5": _meeting("2026-09-01"),  # no agenda yet
        "meeting-6": _meeting("2026-08-04", records=[_agenda("meeting-6", 6)]),
        "meeting-7": _meeting("2026-08-05", records=[("record-meeting-7-agenda", "meeting_agenda", AGENDA.format(6))]),
        "meeting-8": _meeting("2026-07-07", records=[_agenda("meeting-8", 8),
                                                     ("record-x", "agenda_pdf", AGENDA.format(88))]),
        "meeting-9": _meeting("2026-07-21", records=[("record-m9-minutes", "meeting_minutes", AGENDA.format(9))]),
        "meeting-10": _meeting("2026-06-02", category=None, records=[_agenda("meeting-10", 10)]),
    }
    sel = ai.select(meetings, _config(), ledger={}, today="2026-10-18")
    assert [c["meeting_id"] for c in sel["selected"]] == ["meeting-1"]
    assert sel["selected"][0] == {"meeting_id": "meeting-1", "meeting_date": "2026-10-06",
                                  "record_id": "record-meeting-1-agenda", "url": AGENDA.format(1), "retry": False,
                                  "title": "Town Council 2026-10-06", "siblings": False}
    assert {h["meeting_id"]: h["reason"] for h in sel["holds"]} == {
        "meeting-6": "agenda_url_shared", "meeting-7": "agenda_url_shared",
        "meeting-8": "agenda_records_ambiguous", "meeting-10": "body_unconfirmed"}
    assert sel["excluded"] == {"other_body": 1, "before_backfill": 1, "has_items": 1, "no_agenda_record": 2}
    assert sel["backlog"] == 1


def test_the_artifact_kind_comes_from_the_registry_block():
    meetings = {"meeting-1": _meeting("2026-10-06", records=[("record-p", "meeting_packet", AGENDA.format(1))])}
    config = _config(agenda_items={**BLOCK, "artifact": "packet"})
    assert [c["record_id"] for c in ai.select(meetings, config, ledger={}, today="2026-10-18")["selected"]] == \
        ["record-p"]
    assert ai.select(meetings, _config(), ledger={}, today="2026-10-18")["selected"] == []


def test_the_cap_takes_the_newest_first_and_counts_the_rest_as_backlog():
    meetings = {f"meeting-{d:02d}": _meeting(f"2026-03-{d:02d}", records=[_agenda(f"meeting-{d:02d}", d)])
                for d in range(1, 26)}
    sel = ai.select(meetings, _config(), ledger={}, today="2026-10-18", cap=20)
    assert [c["meeting_date"] for c in sel["selected"]] == [f"2026-03-{d:02d}" for d in range(25, 5, -1)]
    assert sel["backlog"] == 25


def test_a_ties_on_date_break_by_id():
    meetings = {m: _meeting("2026-03-03", records=[_agenda(m, i)]) for i, m in enumerate(["meeting-b", "meeting-a"])}
    assert [c["meeting_id"] for c in ai.select(meetings, _config(), ledger={}, today="2026-10-18")["selected"]] == \
        ["meeting-a", "meeting-b"]


def test_a_meeting_the_ledger_manages_is_not_a_candidate_again():
    meetings = {"meeting-1": _meeting("2026-10-06", records=[_agenda("meeting-1", 1)])}
    ledger = {"meeting-1": {"state": "revised", "source_id": SID}}
    assert ai.select(meetings, _config(), ledger=ledger, today="2026-10-18")["selected"] == []


def test_held_candidates_retry_on_their_own_slower_budget_and_never_starve_the_cap():
    meetings = {f"meeting-{d:02d}": _meeting(f"2026-03-{d:02d}", records=[_agenda(f"meeting-{d:02d}", d)])
                for d in range(1, 13)}
    held = lambda last: {"state": "held", "source_id": SID, "hold": {"reason": "unparseable", "last_attempt": last}}  # noqa: E731
    ledger = {f"meeting-{d:02d}": held("2026-10-11") for d in range(6, 13)}  # the 7 newest held last week
    ledger.update({"meeting-05": held("2026-09-01"), "meeting-04": held("2026-09-21")})  # one due, one not yet
    sel = ai.select(meetings, _config(), ledger=ledger, today="2026-10-18", cap=2, held_retry_cap=5)
    fresh = [c["meeting_id"] for c in sel["selected"] if not c["retry"]]
    retried = [c["meeting_id"] for c in sel["selected"] if c["retry"]]
    assert fresh == ["meeting-03", "meeting-02"]  # the cap goes to candidates never held
    assert retried == ["meeting-05"]  # due after 28 days, from its own budget
    assert sel["held_waiting"] == 8


def test_a_held_retry_budget_bounds_retries():
    meetings = {f"meeting-{d:02d}": _meeting(f"2026-03-{d:02d}", records=[_agenda(f"meeting-{d:02d}", d)])
                for d in range(1, 9)}
    ledger = {m: {"state": "held", "source_id": SID, "hold": {"reason": "unparseable", "last_attempt": "2026-01-01"}}
              for m in meetings}
    sel = ai.select(meetings, _config(), ledger=ledger, today="2026-10-18", cap=20, held_retry_cap=5)
    assert [c["meeting_id"] for c in sel["selected"]] == [f"meeting-{d:02d}" for d in range(8, 3, -1)]
    assert all(c["retry"] for c in sel["selected"])


# --- session identity --------------------------------------------------------------------------------------


@pytest.mark.parametrize("header, title, siblings, reason", [
    # Ross 2025-12-11 (fictionalized): two meetings that day, one closed-session file under both
    ("Special Meeting Closed Session of the Town Council", "Town Council Meeting", True, "agenda_session_mismatch"),
    ("Special Meeting Closed Session of the Town Council", "Town Council Closed Session", True, None),
    ("Regular Meeting of the Town Council", "Town Council Meeting", True, None),
    ("Agenda of the Town Council", "Town Council Meeting", True, None),  # names neither: regular
    ("Special Meeting of the Town Council", "Special Town Council Meeting", True, None),
    ("Special Meeting of the Town Council", "Town Council Closed Session", True, "agenda_session_mismatch"),
    # no sibling: only a closed-only file under an open meeting (or the reverse) holds
    ("Special Meeting Closed Session", "Town Council Meeting", False, "agenda_session_mismatch"),
    ("Regular Meeting\nClosed Session at 5:30", "Town Council Meeting", False, None),
    ("Special Meeting of the Town Council", "Town Council Closed Session", False, None),
    ("Special Meeting", "Town Council Meeting", False, None),
])
def test_the_files_session_must_be_the_meetings(header, title, siblings, reason):
    assert ai.session_hold(header, title, siblings=siblings) == reason


@pytest.mark.parametrize("header, meeting, siblings, reason", [
    # `session: {match: exact}`: with a same-day sibling the kinds must be equal
    ("HARBORVIEW CITY COUNCIL SPECIAL CLOSED SESSION", "meeting 2026 04 06 harborview closed session", True, None),
    ("HARBORVIEW CITY COUNCIL SPECIAL CLOSED SESSION", "meeting 2026 04 06 harborview", True,
     "agenda_session_mismatch"),
    ("HARBORVIEW CITY COUNCIL SPECIAL CLOSED SESSION", "meeting 2026 04 06 harborview special", True,
     "agenda_session_mismatch"),
    ("HARBORVIEW CITY COUNCIL SPECIAL MEETING", "meeting 2026 04 06 harborview closed session", True,
     "agenda_session_mismatch"),
    ("HARBORVIEW CITY COUNCIL SPECIAL MEETING", "meeting 2026 04 06 harborview special", True, None),
    ("REGULAR MEETING AT 6:00 P.M.", "meeting 2026 04 06 harborview", True, None),
    ("REGULAR MEETING AT 6:00 P.M.", "meeting 2026 04 06 harborview closed session", True, "agenda_session_mismatch"),
    # without one, only a closed-session file under a meeting known as regular holds
    ("HARBORVIEW CITY COUNCIL SPECIAL CLOSED SESSION", "meeting 2023 12 06 harborview special", False, None),
    ("HARBORVIEW CITY COUNCIL SPECIAL CLOSED SESSION", "meeting 2023 12 06 harborview", False,
     "agenda_session_mismatch"),
    ("HARBORVIEW CITY COUNCIL SPECIAL MEETING", "meeting 2023 12 06 harborview", False, None),
])
def test_an_exact_session_rule_matches_the_files_kind_to_the_meetings(header, meeting, siblings, reason):
    assert ai.session_hold(header, meeting, siblings=siblings, exact=True) == reason


def test_a_configured_session_source_reads_the_meetings_title_and_id():
    config = _config(agenda_items={**BLOCK, "session": {"from": ["title", "id"], "match": "exact"}})
    meetings = {"meeting-2026-10-06-lakeport-closed-session": _meeting(
        "2026-10-06", records=[_agenda("m", 1)], title="Lakeport Town Council meeting")}
    [pick] = ai.select(meetings, config, ledger={}, today="2026-10-18")["selected"]
    assert pick["session_text"] == "Lakeport Town Council meeting meeting 2026 10 06 lakeport closed session"
    assert pick["title"] == "Lakeport Town Council meeting"


def test_without_a_session_block_a_pick_is_exactly_as_before():
    meetings = {"meeting-a": _meeting("2026-10-06", records=[_agenda("meeting-a", 1)], title="Town Council Meeting")}
    [pick] = ai.select(meetings, _config(), ledger={}, today="2026-10-18")["selected"]
    assert set(pick) == {"meeting_id", "meeting_date", "record_id", "url", "retry", "title", "siblings"}


def test_a_pick_knows_its_title_and_whether_it_has_a_same_day_sibling():
    meetings = {
        "meeting-a": _meeting("2026-10-06", records=[_agenda("meeting-a", 1)], title="Town Council Meeting"),
        "meeting-b": _meeting("2026-10-06", records=[_agenda("meeting-b", 2)], title="Town Council Closed Session"),
        "meeting-c": _meeting("2026-10-06", category="Planning Commission", records=[_agenda("meeting-c", 3)]),
        "meeting-d": _meeting("2026-09-01", records=[_agenda("meeting-d", 4)], title="Town Council Meeting"),
    }
    picks = {c["meeting_id"]: c for c in ai.select(meetings, _config(), ledger={}, today="2026-10-18")["selected"]}
    assert (picks["meeting-a"]["title"], picks["meeting-a"]["siblings"]) == ("Town Council Meeting", True)
    assert picks["meeting-b"]["siblings"] is True and picks["meeting-d"]["siblings"] is False  # other bodies don't count


# --- the real registry --------------------------------------------------------------------------------------


COUNCILS = ["belvedere-city-council", "corte-madera-town-council", "fairfax-town-council", "ross-town-council"]


NEW = {"san-rafael-city-council": ("lettered", 3), "larkspur-city-council": ("decimal", 1)}


def _registry():
    import yaml

    return {c["id"]: c for name in ai.MEETING_REGISTRIES if (REPO / "registry" / f"{name}-sources.yaml").is_file()
            for c in yaml.safe_load((REPO / "registry" / f"{name}-sources.yaml").read_text())["sources"]}


def test_the_registry_makes_exactly_the_qualified_weekly_councils_eligible():
    verdicts = {c["id"]: (ok, why) for c, ok, why in ai.eligible_sources(REPO)}
    registry = _registry()
    weekly_new = sorted(sid for sid in NEW if registry[sid]["schedule"] == "weekly")  # once each flip lands
    assert sorted(sid for sid, (ok, _) in verdicts.items() if ok) == sorted(COUNCILS + weekly_new)
    assert all(why == "adapter granicus" for c, ok, why in ai.eligible_sources(REPO) if c["adapter"] == "granicus")


@pytest.mark.parametrize("sid", sorted(NEW))
def test_a_qualified_new_council_is_ineligible_while_manual_and_eligible_once_weekly(sid):
    config = _registry()[sid]
    parser, version = NEW[sid]
    block = config["agenda_items"]
    assert (block["parser"], block["qualified"]["parser"], block["qualified"]["version"]) == (parser, parser, version)
    assert ai.eligibility({**config, "schedule": "manual"}) == (False, "schedule manual")
    assert ai.eligibility({**config, "schedule": "weekly"}) == (True, "eligible")


def test_the_four_qualified_councils_stay_pinned_to_the_versions_they_were_measured_at():
    import yaml

    pinned = {}
    for name in ai.MEETING_REGISTRIES:
        path = REPO / "registry" / f"{name}-sources.yaml"
        for config in (yaml.safe_load(path.read_text()) if path.is_file() else {}).get("sources") or []:
            if config["id"] in COUNCILS:
                block = config["agenda_items"]
                pinned[config["id"]] = (block["parser"], block["qualified"]["version"])
                assert ai.eligibility(config) == (True, "eligible")
    assert pinned == {"belvedere-city-council": ("outline", 8), "corte-madera-town-council": ("outline", 8),
                      "fairfax-town-council": ("flat", 1), "ross-town-council": ("outline", 8)}
