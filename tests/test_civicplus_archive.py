"""The CivicPlus Archive Center adapter (scripts/adapters/civicplus_archive.py).

One static listing page of titled items keyed by ADID. Every row is accounted for (included, excluded with a
reason, or unresolved); anything unresolved, a missing or truncated table, or a row count that does not add up
is an adapter error, so the pull fails its floors and nothing is written. Fixtures are fictional (Lakeport),
shaped from a saved real listing; titles are the real page's title shapes.
"""
from __future__ import annotations

import random
import re
import socket
import sys
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import robots_gate as rg  # noqa: E402
from adapters import get_adapter_class  # noqa: E402
from adapters.civicplus_archive import CivicPlusArchiveAdapter, parse_listing  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "civicplus-archive-lakeport.html"
SID = "lakeport-city-council"
BASE = "https://www.lakeport.example"
ITEM = BASE + "/Archive.aspx?ADID={}"


def _mid(key) -> str:
    return f"meeting-{SID}-adid-{key}"


@pytest.fixture(scope="module")
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _parse(html, **kwargs):
    return parse_listing(html, source_id=SID, base_url=BASE, backfill_from="2019-01-01",
                         archive_title="City Council Agendas", **kwargs)


@pytest.fixture(scope="module")
def parsed(html):
    return _parse(html)


def _by_id(parsed) -> dict[str, dict]:
    return {m["meeting_id"]: m for m in parsed["meetings"]}


def _rows(html):
    """(head, [row tables], tail) of the fixture, to build variants."""
    tables = re.findall(r'<table summary="Archive Details">.*?</table>', html, re.S)
    head = html[:html.index(tables[0])]
    tail = html[html.index(tables[-1]) + len(tables[-1]):]
    return head, tables, tail


# --- the inventory ----------------------------------------------------------------------------------


def test_every_row_is_accounted_for(parsed):
    inv = parsed["inventory"]
    assert inv["raw_rows"] == 29
    assert len(inv["included"]) + len(inv["excluded"]) + len(inv["unresolved"]) == 29
    assert {e["adid"]: e["reason"] for e in inv["excluded"]} == {
        9461: "index_of_same_day_agendas", 9324: "attendance_notice",
        8149: "before_backfill_from", 7957: "before_backfill_from", 7980: "before_backfill_from"}
    assert inv["unresolved"] == [] and parsed["errors"] == []


def test_a_plain_agenda_is_a_regular_meeting_with_its_agenda(parsed):
    m = _by_id(parsed)[_mid(9533)]
    assert (m["date"], m["meeting_type"], m["listing_key"]) == ("2026-10-07", "regular", "2026-10-07|regular|1")
    assert m["title"] == "October 7, 2026, City Council Agenda"
    assert m["archive_item_id"] == 9533 and m["superseded_item_ids"] == []
    assert m["artifacts"] == {"agenda": {"available": True, "url": ITEM.format(9533)}}


def test_same_day_regular_and_special_stay_distinct(parsed):
    ms = _by_id(parsed)
    assert ms[_mid(8412)]["listing_key"] == "2020-03-18|regular|1"
    assert ms[_mid(8411)]["listing_key"] == "2020-03-18|special|1"


def test_a_second_special_meeting_the_same_day_takes_ordinal_two(parsed):
    ms = _by_id(parsed)
    assert ms[_mid(9141)]["listing_key"] == "2023-12-13|special|1"
    assert ms[_mid(9143)]["listing_key"] == "2023-12-13|special|2"


@pytest.mark.parametrize("adid,mtype", [(9517, "cancelled_meeting"), (9494, "cancelled_meeting"),
                                        (9249, "cancelled_meeting"), (9248, "special"), (9208, "joint_meeting"),
                                        (9441, "workshop"), (9440, "regular"), (8315, "special"),
                                        (9151, "regular"), (9133, "regular")])
def test_meeting_types_follow_the_titles(parsed, adid, mtype):
    assert _by_id(parsed)[_mid(adid)]["meeting_type"] == mtype


def test_a_cancelled_meeting_carries_its_notice_not_an_agenda(parsed):
    m = _by_id(parsed)[_mid(9249)]
    assert m["artifacts"] == {"notice": {"available": True, "url": ITEM.format(9249)}}


def test_a_notice_naming_two_dates_is_two_cancelled_meetings_sharing_it(parsed):
    ms = _by_id(parsed)
    a, b = ms[_mid("9138-2023-12-06")], ms[_mid("9138-2023-12-20")]
    assert (a["date"], b["date"]) == ("2023-12-06", "2023-12-20")
    assert a["meeting_type"] == b["meeting_type"] == "cancelled_meeting"
    assert a["artifacts"] == b["artifacts"] == {"notice": {"available": True, "url": ITEM.format(9138)}}


def test_a_reposted_agenda_is_one_meeting_at_its_latest_posting(parsed):
    ms = _by_id(parsed)
    m = ms[_mid(9129)]
    assert _mid(9127) not in ms
    assert m["superseded_item_ids"] == [9127]
    assert m["artifacts"]["agenda"]["url"] == ITEM.format(9129)


def test_the_note_is_kept_as_the_description(parsed):
    assert _by_id(parsed)[_mid(9133)]["description"] == \
        "Agenda Packet for Regular Council Meeting on November 15, 2023"


def test_meeting_count(parsed):
    # 29 rows - 5 excluded = 24 included; 9138 is two meetings; 9127 merges into 9129.
    assert len(parsed["meetings"]) == 24


def test_ids_do_not_depend_on_row_order(html):
    head, tables, tail = _rows(html)
    shuffled = tables[:]
    random.Random(7).shuffle(shuffled)
    a = {m["meeting_id"]: m["listing_key"] for m in _parse(html)["meetings"]}
    b = {m["meeting_id"]: m["listing_key"] for m in _parse(head + "".join(shuffled) + tail)["meetings"]}
    assert a == b


# --- fail closed ------------------------------------------------------------------------------------


def _with(html, extra_rows: list[str], drop=lambda t: False):
    head, tables, tail = _rows(html)
    template = tables[0]
    added = [re.sub(r"ADID=\d+", f"ADID={adid}", re.sub(r"<span>.*?</span>", f"<span>{title}  </span>", template,
                                                          count=1, flags=re.S)) for adid, title in extra_rows]
    return head + "".join(added + [t for t in tables if not drop(t)]) + tail


def test_a_same_day_closed_session_stays_distinct_from_the_regular_meeting(html):
    ms = _by_id(_parse(_with(html, [(9534, "October 7, 2026, City Council Closed Session Agenda")])))
    assert ms[_mid(9534)]["listing_key"] == "2026-10-07|closed_session|1"
    assert ms[_mid(9533)]["listing_key"] == "2026-10-07|regular|1"


@pytest.mark.parametrize("title,reason", [
    ("City Council Agenda", "no_date"),
    ("March 3, 2021, Council Retreat", "no_type_word"),
])
def test_an_unparseable_row_fails_closed(html, title, reason):
    out = _parse(_with(html, [(9999, title)]))
    assert [u["adid"] for u in out["inventory"]["unresolved"]] == [9999]
    assert out["inventory"]["unresolved"][0]["reason"] == reason
    assert any("ADID 9999" in e and reason in e for e in out["errors"])


def test_plural_agendas_without_two_rows_that_day_is_unresolved(html):
    out = _parse(_with(html, [(9998, "March 3, 2021, City Council Agendas")]))
    assert any("ADID 9998" in e and "plural_agendas" in e for e in out["errors"])


def test_two_different_titles_on_one_listing_key_are_unresolved(html):
    out = _parse(_with(html, [(9997, "October 7, 2026, City Council Agenda - Revised")]))
    assert any("same_key_different_titles" in e and "9533" in e and "9997" in e for e in out["errors"])


def test_a_missing_table_fails_closed(html):
    out = _parse(html.replace('summary="Archive Details List"', 'summary="Something Else"'))
    assert out["meetings"] == [] and any("listing_table_missing" in e for e in out["errors"])


def test_the_wrong_archive_fails_closed(html):
    out = _parse(html.replace("City Council Agendas", "Planning Commission Agendas", 1))
    assert any("listing_table_missing" in e for e in out["errors"])


def test_a_truncated_table_that_lost_its_older_rows_fails_closed(html):
    out = _parse(_with(html, [], drop=lambda t: re.search(r"(2015|2016|2018)", t) is not None))
    assert out["meetings"] and any("listing_truncated" in e for e in out["errors"])


def test_a_row_count_that_does_not_add_up_fails_closed(html):
    broken = html.replace('<a href="Archive.aspx?ADID=9533" target="_blank">', '<a href="other.aspx">', 1)
    out = _parse(broken)
    assert any("row_count_mismatch" in e for e in out["errors"])


# --- the adapter: one request, through the gate, to the allowed host only ----------------------------


class _Spy:
    """Every TCP connection attempted, by host; robots.txt answered from memory."""

    def __init__(self, monkeypatch):
        self.connections: list[str] = []
        self.robots: list[str] = []

        def connect(address, *args, **kwargs):
            self.connections.append(address[0])
            raise OSError(f"test: no network to {address[0]}")

        monkeypatch.setattr(socket, "create_connection", connect)

    def robots_transport(self, url, timeout):
        self.robots.append(url)
        return rg.Reply(200, {}, b"User-agent: *\nDisallow: /admin\n", None)


def _config(**extra):
    return {"id": SID, "adapter": "civicplus_archive", "url": BASE + "/Archive.aspx?AMID=49",
            "allowed_hosts": ["www.lakeport.example"], "archive_title": "City Council Agendas",
            "jurisdiction_id": "place-lakeport", "institution_id": "org-lakeport-city-council",
            "backfill_from": "2019-01-01", **extra}


class _Reply:
    def __init__(self, body: bytes):
        self.body, self.headers = body, type("H", (), {"get_content_charset": lambda self, d=None: "utf-8"})()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_registered():
    assert get_adapter_class("civicplus_archive") is CivicPlusArchiveAdapter


def test_capture_reads_one_page_through_the_gate_with_the_host_allowlist(tmp_path, html, monkeypatch):
    calls = []

    class Gate:
        refusals = []

        def open(self, request, *, timeout, handlers=(), hosts=None):
            calls.append((request.full_url, hosts))
            return _Reply(html.encode())

    adapter = CivicPlusArchiveAdapter(_config(), tmp_path, gate=Gate())
    out = adapter.capture()
    assert calls == [(BASE + "/Archive.aspx?AMID=49", {"www.lakeport.example"})]
    assert out["adapter"] == "civicplus_archive" and out["errors"] == []
    assert out["meeting_count"] == 24 and out["inventory"]["raw_rows"] == 29
    assert all(m["institution_id"] == "org-lakeport-city-council" for m in out["meetings"])
    day = out["captured_at"][:10]
    assert out["record_refs"][0]["id"] == f"record-{SID}-archive-page-{day}"
    assert (tmp_path / out["raw_artifact"]).read_text() == html


def test_capture_without_an_allowlist_is_a_config_error(tmp_path):
    with pytest.raises(ValueError, match="allowed_hosts"):
        CivicPlusArchiveAdapter({k: v for k, v in _config().items() if k != "allowed_hosts"}, tmp_path)


def test_a_disallowed_listing_url_is_refused_without_a_request(tmp_path, monkeypatch):
    spy = _Spy(monkeypatch)

    def robots(url, timeout):
        spy.robots.append(url)
        return rg.Reply(200, {}, b"User-agent: *\nDisallow: /Archive.aspx\n", None)

    gate = rg.RobotsGate(robots_transport=robots)
    with pytest.raises(rg.RobotsDisallowed):
        CivicPlusArchiveAdapter(_config(), tmp_path, gate=gate).capture()
    assert spy.robots == [BASE + "/robots.txt"] and spy.connections == []


def test_a_listing_url_on_a_forbidden_host_makes_no_request_at_all(tmp_path, monkeypatch):
    spy = _Spy(monkeypatch)
    gate = rg.RobotsGate(robots_transport=spy.robots_transport)
    config = _config(url="https://records.lakeport.example/WebLink/Browse.aspx")
    with pytest.raises(rg.HostNotAllowed):
        CivicPlusArchiveAdapter(config, tmp_path, gate=gate).capture()
    assert spy.robots == [] and spy.connections == []


def test_a_cancellation_and_a_regular_agenda_on_one_date_are_unresolved(html):
    out = _parse(_with(html, [(9535, "October 7, 2026 - Meeting Cancelled")]))
    assert {u["adid"] for u in out["inventory"]["unresolved"]} == {9533, 9535}
    assert _mid(9533) not in _by_id(out) and _mid(9535) not in _by_id(out)
    assert any("ADID 9535" in e and "cancelled_and_regular_same_day" in e for e in out["errors"])


# --- Codex review (a): structural rows, invalid dates, plural rows judged against real ones -------------


@pytest.mark.parametrize("markup", ['<br/><span style="font-style: italic">{n}</span>',
                                    '<br><span class="note" style="font-style:italic">{n}</span>',
                                    '<br><em>{n}</em>'])
def test_a_note_in_other_markup_still_classifies_the_row(html, markup):
    variant = html.replace('</a><br>\n\t\t\t\t\t\t\t<span style="font-style: italic"></span>',
                           "</a>" + markup.format(n="Meeting Cancelled"), 1)
    assert variant != html
    m = _by_id(_parse(variant))[_mid(9537)]
    assert m["meeting_type"] == "cancelled_meeting" and m["description"] == "Meeting Cancelled"


def test_text_outside_the_title_and_note_is_unresolved(html):
    variant = html.replace('<td style="padding-left:0;padding-right:0;width:16px">',
                           '<td style="padding-left:0;padding-right:0;width:16px">REVISED ', 1)
    out = _parse(variant)
    assert any("ADID 9537" in e and "unconsumed_text" in e for e in out["errors"])


def test_an_invalid_date_beside_a_valid_one_is_unresolved(html):
    out = _parse(_with(html, [(9996, "December 6, 2023 and December 32, 2023 - Meeting Cancelled")]))
    assert any("ADID 9996" in e and "invalid_date" in e for e in out["errors"])
    assert _mid(9996) not in _by_id(out) and _mid("9996-2023-12-06") not in _by_id(out)


def test_plural_rows_cannot_vouch_for_each_other(html):
    three = [(9990 + i, "March 3, 2021, City Council Agendas") for i in range(3)]
    out = _parse(_with(html, three))
    assert {u["adid"] for u in out["inventory"]["unresolved"]} == {9990, 9991, 9992}
    two_and_one = [(9993, "March 4, 2021, City Council Agendas"), (9994, "March 4, 2021, City Council Agendas"),
                   (9995, "March 4, 2021, City Council Agenda")]
    out = _parse(_with(html, two_and_one))
    assert {9993, 9994} <= {u["adid"] for u in out["inventory"]["unresolved"]}


def test_a_table_without_its_link_cannot_be_offset_by_a_table_with_two(html):
    head, tables, tail = _rows(html)
    empty = re.sub(r'<a href="Archive\.aspx\?ADID=\d+"[^>]*>.*?</a>', "", tables[1], flags=re.S)
    double = tables[2].replace("</a>", '</a><a href="Archive.aspx?ADID=9800"><span>x</span></a>', 1)
    out = _parse(head + tables[0] + empty + double + "".join(tables[3:]) + tail)
    assert any("row_count_mismatch" in e for e in out["errors"])
