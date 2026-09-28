"""I2 — meeting ids are stable across runs (never derived from row position).

Contract, per adapter (Granicus, Drupal/Ross, CivicPlus):
  * a meeting's id is identical across two parses, even when rows are
    reordered or new rows are inserted above it;
  * rows carrying a source-native key keep exactly today's id;
  * distinct meetings on the same date get distinct ids.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters.civicplus import CivicPlusAdapter
from adapters.drupal_ross import DrupalRossAdapter
from adapters.granicus import GranicusAdapter
from adapters.meeting_ids import assign_meeting_ids, normalize_title, title_hash

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _config(source_id, adapter, url):
    return {
        "id": source_id,
        "adapter": adapter,
        "url": url,
        "jurisdiction_id": "place-test",
        "institution_id": f"org-{source_id}",
        "backfill_from": "2019-01-01",
    }


def _ids_by_title(result):
    return {m["title"]: m["meeting_id"] for m in result["meetings"]}


# ---------------------------------------------------------------------------
# Shared rule
# ---------------------------------------------------------------------------


class TestTitleNormalization:
    def test_lowercases_strips_punctuation_and_collapses_whitespace(self):
        assert normalize_title("  City Council -  CANCELLED!! ") == "city council cancelled"

    def test_punctuation_variants_normalize_identically(self):
        assert normalize_title("Meeting-CANCELLED") == normalize_title("Meeting - Cancelled")

    def test_title_hash_is_short_and_deterministic(self):
        assert title_hash("City Council") == title_hash("city   council.")
        assert len(title_hash("City Council")) == 8
        assert title_hash("City Council") != title_hash("Planning Commission")


class TestAssignMeetingIds:
    def test_native_key_wins(self):
        meetings = [{"date": "2026-04-21", "title": "City Council", "k": "42"}]
        assign_meeting_ids(meetings, "src", lambda m: m["k"])
        assert meetings[0]["meeting_id"] == "meeting-src-42"

    def test_fallback_is_date_plus_title_hash(self):
        meetings = [{"date": "2026-04-21", "title": "City Council"}]
        assign_meeting_ids(meetings, "src", lambda m: None)
        assert meetings[0]["meeting_id"] == f"meeting-src-2026-04-21-{title_hash('City Council')}"

    def test_undated_fallback(self):
        meetings = [{"date": None, "title": "City Council"}]
        assign_meeting_ids(meetings, "src", lambda m: None)
        assert meetings[0]["meeting_id"] == f"meeting-src-undated-{title_hash('City Council')}"

    def test_identical_fallback_twins_get_distinct_ids(self):
        meetings = [{"date": "2026-04-21", "title": "Racial Equity Committee"} for _ in range(2)]
        assign_meeting_ids(meetings, "src", lambda m: None)
        first, second = (m["meeting_id"] for m in meetings)
        assert first != second
        assert second == f"{first}-2"

    def test_duplicate_native_keys_are_not_suffixed(self):
        """Two rows with the same native key are the same meeting: keep one id."""
        meetings = [{"date": "2026-04-21", "title": "x", "k": "7"} for _ in range(2)]
        assign_meeting_ids(meetings, "src", lambda m: m["k"])
        assert {m["meeting_id"] for m in meetings} == {"meeting-src-7"}


# ---------------------------------------------------------------------------
# Granicus
# ---------------------------------------------------------------------------


def _granicus_upcoming(title, date, event_id=None):
    agenda = (
        f'<a href="//x.granicus.com/AgendaViewer.php?view_id=7&event_id={event_id}">Agenda</a>'
        if event_id
        else ""
    )
    return (
        '<tr class="listingRow">'
        f'<td class="listItem">{title}</td><td class="listItem">{date}</td>'
        f'<td class="listItem">{agenda}</td><td class="listItem"></td><td class="listItem"></td>'
        "</tr>"
    )


def _granicus_archive(title, date, clip_id):
    return (
        '<tr class="listingRow">'
        f'<td class="listItem">{title}</td><td class="listItem">{date}</td>'
        '<td class="listItem">01h 00m</td>'
        f'<td class="listItem"><a href="//x.granicus.com/AgendaViewer.php?view_id=7&clip_id={clip_id}">Agenda</a></td>'
        '<td class="listItem"></td><td class="listItem"></td>'
        "</tr>"
    )


def _granicus_capture(tmp_path, rows):
    adapter = GranicusAdapter(
        _config("sausalito-city-council", "granicus", "https://x.granicus.com/ViewPublisher.php"),
        tmp_path,
    )
    html = "<table>" + "".join(rows) + "</table>"
    adapter._fetch = lambda url: html
    return adapter.capture()


class TestGranicusStableIds:
    def test_keyless_ids_survive_reorder_and_insertion(self, tmp_path):
        a = _granicus_upcoming("City Council", "Apr 21, 2026")
        b = _granicus_upcoming("Planning Commission", "May 05, 2026")
        new = _granicus_upcoming("Special Budget Workshop", "Apr 01, 2026")
        first = _ids_by_title(_granicus_capture(tmp_path / "1", [a, b]))
        second = _ids_by_title(_granicus_capture(tmp_path / "2", [new, b, a]))
        assert first["City Council"] == second["City Council"]
        assert first["Planning Commission"] == second["Planning Commission"]

    def test_no_row_position_ids(self, tmp_path):
        rows = [_granicus_upcoming("City Council", "Apr 21, 2026")]
        result = _granicus_capture(tmp_path, rows)
        assert "-row-" not in result["meetings"][0]["meeting_id"]

    def test_clip_id_rows_keep_todays_id(self, tmp_path):
        rows = [_granicus_archive("City Council", "Mar 03, 2026", "1234")]
        result = _granicus_capture(tmp_path, rows)
        assert result["meetings"][0]["meeting_id"] == "meeting-sausalito-city-council-1234"

    def test_clip_ids_unchanged_on_real_fixture(self, tmp_path):
        adapter = GranicusAdapter(
            _config("novato-city-council", "granicus", "https://x.granicus.com/ViewPublisher.php"),
            tmp_path,
        )
        html = (FIXTURES / "granicus-novato-city-council.html").read_text(errors="ignore")
        adapter._fetch = lambda url: html
        clipped = [m for m in adapter.capture()["meetings"] if m.get("clip_id")]
        assert len(clipped) > 200
        for m in clipped:
            assert m["meeting_id"] == f"meeting-novato-city-council-{m['clip_id']}"

    def test_event_id_row_is_keyed_on_event_id(self, tmp_path):
        rows = [_granicus_upcoming("City Council", "Apr 14, 2026", event_id="1126")]
        result = _granicus_capture(tmp_path, rows)
        assert result["meetings"][0]["meeting_id"] == "meeting-sausalito-city-council-event-1126"

    def test_distinct_meetings_same_date_get_distinct_ids(self, tmp_path):
        rows = [
            _granicus_upcoming("City Council", "Apr 21, 2026"),
            _granicus_upcoming("City Council Closed Session", "Apr 21, 2026"),
        ]
        ids = [m["meeting_id"] for m in _granicus_capture(tmp_path, rows)["meetings"]]
        assert len(set(ids)) == 2


# ---------------------------------------------------------------------------
# Drupal / Ross
# ---------------------------------------------------------------------------


def _ross_upcoming(title, iso, detail=None):
    cell = f'<a href="{detail}">{title}</a>' if detail else title
    return (
        f'<tr class="odd"><td><span content="{iso}T18:00:00-07:00">x</span></td>'
        f"<td>{cell}</td><td></td><td></td><td></td></tr>"
    )


def _ross_past(title, iso, detail):
    return (
        f'<tr class="odd"><td><span content="{iso}T18:00:00-07:00">x</span></td>'
        f"<td>{title}</td><td></td><td></td><td></td><td></td><td></td>"
        f'<td><a href="{detail}">View Details</a></td></tr>'
    )


def _ross_capture(tmp_path, upcoming, past=()):
    html = (
        '<table class="views-table cols-5"><tbody>' + "".join(upcoming) + "</tbody></table>"
        '<table class="views-table cols-8"><tbody>' + "".join(past) + "</tbody></table>"
    )
    adapter = DrupalRossAdapter(
        _config("ross-town-council", "drupal_ross", "https://www.townofrossca.gov/meetings"),
        tmp_path,
    )
    adapter._fetch_page = lambda url: html
    return adapter.capture()


class TestRossStableIds:
    def test_ids_survive_reorder_and_insertion(self, tmp_path):
        a = _ross_upcoming("Ross Town Council Meeting", "2026-04-29", "/towncouncil/page/ross-town-council-meeting-10")
        b = _ross_upcoming("Advisory Design Review Group", "2026-05-19")
        new = _ross_upcoming("Town of Ross Annual Budget Workshop", "2026-04-23", "/towncouncil/page/budget")
        first = _ids_by_title(_ross_capture(tmp_path / "1", [a, b]))
        second = _ids_by_title(_ross_capture(tmp_path / "2", [new, b, a]))
        assert first == {k: second[k] for k in first}
        assert all("-row-" not in mid for mid in second.values())

    def test_keyed_on_detail_url_in_either_table(self, tmp_path):
        result = _ross_capture(
            tmp_path,
            [_ross_upcoming("Ross Town Council Meeting", "2026-04-29", "/towncouncil/page/ross-town-council-meeting-10")],
            [_ross_past("Ross Town Council Meeting", "2026-03-12", "/towncouncil/page/ross-town-council-meeting-0")],
        )
        ids = [m["meeting_id"] for m in result["meetings"]]
        assert ids == [
            "meeting-ross-town-council-towncouncil-page-ross-town-council-meeting-10",
            "meeting-ross-town-council-towncouncil-page-ross-town-council-meeting-0",
        ]
        assert result["meetings"][0]["detail_url"] == (
            "https://www.townofrossca.gov/towncouncil/page/ross-town-council-meeting-10"
        )

    def test_distinct_meetings_same_date_get_distinct_ids(self, tmp_path):
        result = _ross_capture(
            tmp_path,
            [
                _ross_upcoming("Town Council Closed Session", "2026-04-29"),
                _ross_upcoming("Ross Town Council Meeting", "2026-04-29"),
            ],
        )
        ids = [m["meeting_id"] for m in result["meetings"]]
        assert len(set(ids)) == 2

    def test_real_fixture_ids_are_unique_and_positionless(self, tmp_path):
        adapter = DrupalRossAdapter(
            _config("ross-town-council", "drupal_ross", "https://www.townofrossca.gov/meetings"),
            tmp_path,
        )
        html = (FIXTURES / "drupal-ross.html").read_text(errors="ignore")
        adapter._fetch_page = lambda url: html
        ids = [m["meeting_id"] for m in adapter.capture()["meetings"]]
        assert len(ids) == len(set(ids)) > 5
        assert not any("-row-" in mid for mid in ids)


# ---------------------------------------------------------------------------
# CivicPlus
# ---------------------------------------------------------------------------


def _civicplus_row(date_label, agenda_id=None, title="Town Council"):
    link = (
        f'<p><a href="/AgendaCenter/ViewFile/Agenda/_04212026-{agenda_id}">{title}</a></p>'
        if agenda_id
        else f"<p>{title}</p>"
    )
    return (
        '<tr id="rowx" class="catAgendaRow"><td>'
        f'<strong aria-label="Agenda for {date_label}">x</strong>{link}</td></tr>'
    )


def _civicplus_capture(tmp_path, rows):
    adapter = CivicPlusAdapter(
        _config("corte-madera-town-council", "civicplus", "https://example.gov/AgendaCenter"),
        tmp_path,
    )
    adapter._request_delay = 0
    html = "<table>" + "".join(rows) + "</table>"
    adapter._fetch_page = lambda url: html
    adapter._fetch_year = lambda url, cat_id, year, cookies: ""
    return adapter.capture()


class TestCivicPlusStableIds:
    def test_keyless_ids_survive_reorder_and_insertion(self, tmp_path):
        a = _civicplus_row("April 21, 2026")
        b = _civicplus_row("May 5, 2026")
        new = _civicplus_row("April 1, 2026", agenda_id="99")
        first = [m["meeting_id"] for m in _civicplus_capture(tmp_path / "1", [a, b])["meetings"]]
        second = {m["date"]: m["meeting_id"] for m in _civicplus_capture(tmp_path / "2", [new, b, a])["meetings"]}
        assert first == [second["2026-04-21"], second["2026-05-05"]]
        assert not any("-row-" in mid for mid in first)

    def test_agenda_id_rows_keep_todays_id(self, tmp_path):
        result = _civicplus_capture(tmp_path, [_civicplus_row("April 21, 2026", agenda_id="1620")])
        assert result["meetings"][0]["meeting_id"] == "meeting-corte-madera-town-council-1620"

    def test_agenda_ids_unchanged_on_real_fixture(self, tmp_path):
        adapter = CivicPlusAdapter(
            _config("corte-madera-town-council", "civicplus", "https://example.gov/AgendaCenter"),
            tmp_path,
        )
        adapter._request_delay = 0
        html = (FIXTURES / "civicplus-corte-madera.html").read_text(errors="ignore")
        adapter._fetch_page = lambda url: html
        adapter._fetch_year = lambda url, cat_id, year, cookies: ""
        keyed = [m for m in adapter.capture()["meetings"] if m.get("agenda_id")]
        assert len(keyed) > 20
        for m in keyed:
            assert m["meeting_id"] == f"meeting-corte-madera-town-council-{m['agenda_id']}"

    def test_keyless_row_on_landing_and_year_page_is_one_meeting(self, tmp_path):
        panel = f'<div id="category-panel-1"><table>{_civicplus_row("April 21, 2026")}</table></div>'
        landing = (
            '<input name="chkCategoryID" value="1"><div id="cat1"><h2>Town Council</h2></div>'
            f'<a onclick="changeYear(2026, 1)">2026</a>{panel}'
        )
        adapter = CivicPlusAdapter(
            _config("corte-madera-town-council", "civicplus", "https://example.gov/AgendaCenter"),
            tmp_path,
        )
        adapter._request_delay = 0
        adapter._fetch_page = lambda url: landing
        adapter._fetch_year = lambda url, cat_id, year, cookies: panel
        meetings = adapter.capture()["meetings"]
        assert len(meetings) == 1
        assert meetings[0]["category"] == "Town Council"

    def test_distinct_categories_same_date_get_distinct_ids(self):
        from adapters.civicplus import native_meeting_key, meeting_name

        meetings = [
            {"date": "2026-04-21", "title": "", "category": "Town Council", "agenda_id": None},
            {"date": "2026-04-21", "title": "", "category": "Planning Commission", "agenda_id": None},
        ]
        assign_meeting_ids(meetings, "src", native_meeting_key, name=meeting_name)
        assert meetings[0]["meeting_id"] != meetings[1]["meeting_id"]
        assert not meetings[1]["meeting_id"].endswith("-2")
