"""Tests for the ProudCity WordPress adapter."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter
from adapters.proudcity import (
    extract_meeting_urls,
    parse_meeting_date_from_title,
    extract_artifacts_from_detail,
    ProudCityAdapter,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestRegistry:
    def test_proudcity_registered(self):
        cls = get_adapter_class("proudcity")
        assert issubclass(cls, BaseAdapter)


class TestParseMeetingDateFromTitle:
    def test_standard_format(self):
        assert parse_meeting_date_from_title("Town Council Meeting: January 8, 2025") == "2025-01-08"

    def test_dash_separated(self):
        assert parse_meeting_date_from_title("City Council - April 6, 2026") == "2026-04-06"

    def test_no_date_returns_none(self):
        assert parse_meeting_date_from_title("Special Joint Session") is None

    def test_month_day_year(self):
        assert parse_meeting_date_from_title("Planning Commission Meeting: December 15, 2023") == "2023-12-15"


class TestExtractMeetingUrls:
    def test_belvedere_has_meetings(self):
        html = (FIXTURES / "wordpress-belvedere.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://www.cityofbelvedere.org")
        assert len(meetings) > 0

    def test_meeting_entry_has_url_and_title(self):
        html = (FIXTURES / "wordpress-belvedere.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://www.cityofbelvedere.org")
        if meetings:
            m = meetings[0]
            assert "url" in m
            assert "title" in m
            assert "/meetings/" in m["url"]

    def test_fairfax_fixture_returns_list(self):
        html = (FIXTURES / "wordpress-fairfax.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://townoffairfaxca.gov")
        # The main /meetings/ page may show upcoming /event/ links — either way, a list
        assert isinstance(meetings, list)

    def test_no_duplicate_urls(self):
        html = (FIXTURES / "wordpress-belvedere.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://www.cityofbelvedere.org")
        urls = [m["url"] for m in meetings]
        assert len(urls) == len(set(urls))

    def test_date_extracted_from_title(self):
        html = (FIXTURES / "wordpress-belvedere.html").read_text(errors="ignore")
        meetings = extract_meeting_urls(html, "https://www.cityofbelvedere.org")
        dated = [m for m in meetings if m["date"]]
        assert len(dated) > 0


class TestExtractArtifactsFromDetail:
    def test_extracts_gcs_pdf_urls(self):
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        assert isinstance(artifacts, dict)
        # Should find at least one available artifact
        has_any = any(a.get("available") for a in artifacts.values())
        assert has_any

    def test_artifact_format(self):
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        for art in artifacts.values():
            assert "available" in art
            assert "url" in art

    def test_gcs_url_pattern(self):
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        for art in artifacts.values():
            if art["available"] and art["url"]:
                assert (
                    "storage.googleapis.com" in art["url"]
                    or "proudcity" in art["url"]
                    or art["url"].startswith("http")
                )

    def test_known_tabs_present(self):
        """Tab sections present in fixture are correctly detected."""
        fixture = FIXTURES / "wordpress-fairfax-meeting.html"
        if not fixture.exists():
            pytest.skip("Meeting detail fixture not captured yet")
        html = fixture.read_text(errors="ignore")
        artifacts = extract_artifacts_from_detail(html)
        # The fixture has tab-agenda-packet with a PDF
        assert "packet" in artifacts
        assert artifacts["packet"]["available"] is True


class TestProudCityAdapterCapture:
    def _make_adapter(self, source_id, list_html, detail_htmls, tmp_path, archive_pages=None):
        config = {
            "id": source_id,
            "adapter": "proudcity",
            "url": "https://example.gov/meetings/",
            "jurisdiction_id": "place-test",
            "institution_id": f"org-{source_id}",
            "backfill_from": "2019-01-01",
        }
        if archive_pages:
            config["archive_pages"] = archive_pages
        adapter = ProudCityAdapter(config, tmp_path)
        adapter._request_delay = 0
        # Mock: list page returns list_html, detail pages return from dict
        adapter._fetch_page = lambda url: detail_htmls.get(url, list_html)
        return adapter

    def test_capture_returns_dict(self, tmp_path):
        list_html = '''
        <table>
        <tr><td><a href="/meetings/test-meeting-january-5-2025/">Test Meeting: January 5, 2025</a></td></tr>
        </table>
        '''
        detail_html = '''
        <div id="tab-agenda">
            <a href="https://storage.googleapis.com/proudcity/testca/uploads/2025/01/agenda.pdf">Agenda</a>
        </div>
        '''
        adapter = self._make_adapter("test-city", list_html,
            {"https://example.gov/meetings/test-meeting-january-5-2025/": detail_html}, tmp_path)
        result = adapter.capture()
        assert isinstance(result, dict)
        assert result["adapter"] == "proudcity"

    def test_capture_has_required_fields(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Meeting: March 1, 2025</a></td></tr></table>'
        detail = '<div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/agenda.pdf">PDF</a></div>'
        adapter = self._make_adapter("test", list_html,
            {"https://example.gov/meetings/m1/": detail}, tmp_path)
        result = adapter.capture()
        for field in ["capture_id", "source_id", "captured_at", "institution_id",
                      "meeting_count", "meetings", "record_refs", "errors"]:
            assert field in result

    def test_capture_extracts_artifacts(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Council: February 10, 2025</a></td></tr></table>'
        detail = '''
        <div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/agenda.pdf">PDF</a></div>
        <div id="tab-minutes"><a href="https://storage.googleapis.com/proudcity/x/minutes.pdf">PDF</a></div>
        '''
        adapter = self._make_adapter("test", list_html,
            {"https://example.gov/meetings/m1/": detail}, tmp_path)
        result = adapter.capture()
        m = result["meetings"][0]
        assert m["artifacts"]["agenda"]["available"] is True
        assert m["artifacts"]["minutes"]["available"] is True

    def test_capture_uses_archive_pages(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Meeting: March 1, 2025</a></td></tr></table>'
        archive_html = '<table><tr><td><a href="/meetings/m2/">Meeting: June 5, 2024</a></td></tr></table>'
        detail = '<div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/a.pdf">PDF</a></div>'
        adapter = self._make_adapter(
            "test", list_html,
            {
                "https://example.gov/meetings/m1/": detail,
                "https://example.gov/meetings/m2/": detail,
                "https://example.gov/2024-archive/": archive_html,
            },
            tmp_path,
            archive_pages=["https://example.gov/2024-archive/"],
        )
        result = adapter.capture()
        assert result["meeting_count"] == 2

    def test_capture_filters_by_backfill(self, tmp_path):
        list_html = '''
        <table>
        <tr><td><a href="/meetings/old/">Meeting: January 5, 2018</a></td></tr>
        <tr><td><a href="/meetings/new/">Meeting: March 1, 2025</a></td></tr>
        </table>
        '''
        detail = '<div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/a.pdf">PDF</a></div>'
        adapter = self._make_adapter("test", list_html,
            {
                "https://example.gov/meetings/old/": detail,
                "https://example.gov/meetings/new/": detail,
            },
            tmp_path)
        result = adapter.capture()
        # 2018 meeting filtered out, only 2025 remains
        assert result["meeting_count"] == 1
        assert result["meetings"][0]["date"] == "2025-03-01"

    def test_capture_handles_fetch_error(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Meeting: March 1, 2025</a></td></tr></table>'

        def bad_fetch(url):
            if "m1" in url:
                raise ConnectionError("timeout")
            return list_html

        config = {
            "id": "test",
            "adapter": "proudcity",
            "url": "https://example.gov/meetings/",
            "jurisdiction_id": "place-test",
            "institution_id": "org-test",
            "backfill_from": "2019-01-01",
        }
        adapter = ProudCityAdapter(config, tmp_path)
        adapter._request_delay = 0
        adapter._fetch_page = bad_fetch
        result = adapter.capture()
        assert len(result["errors"]) == 1
        assert result["meetings"][0]["artifacts"]["agenda"]["available"] is False


def test_a_failed_archive_page_is_recorded_not_skipped(tmp_path):
    list_html = '<table><tr><td><a href="/meetings/m1/">Meeting: March 1, 2025</a></td></tr></table>'
    detail = '<div id="tab-agenda"><a href="https://storage.googleapis.com/proudcity/x/a.pdf">PDF</a></div>'

    def fetch(url):
        if "archive" in url:
            raise ConnectionError("429 Too Many Requests")
        return detail if url.endswith("/m1/") else list_html

    config = {"id": "test", "adapter": "proudcity", "url": "https://example.gov/meetings/",
              "jurisdiction_id": "place-test", "institution_id": "org-test",
              "archive_pages": ["https://example.gov/2024-archive/"]}
    adapter = ProudCityAdapter(config, tmp_path)
    adapter._request_delay = 0
    adapter._fetch_page = fetch
    result = adapter.capture()
    assert result["meeting_count"] == 1
    assert len(result["errors"]) == 1 and "2024-archive" in result["errors"][0]


# ---------------------------------------------------------------------------
# agenda_artifact: attached (San Rafael). The agenda tab's body links staff
# reports, minutes and correspondence; the agenda itself is the tab's attached
# file, rendered as a sidebar and a footer file block with a `download` button.
# ---------------------------------------------------------------------------

GCS = "https://storage.googleapis.com/proudcity/examplecityca/2026/05"


def _file_block(url, name="cc-agenda-2026-05-04", quote='"', download=f'download="cc-agenda"'):
    return (f"<div title={quote}{name}{quote}>{name}.pdf</div><p><a href={quote}{url}{quote} "
            f"class={quote}btn btn-primary btn-sm{quote} {download}><i class=\"fa fa-download\"></i>Download</a></p>")


def _detail(agenda_body, *, after_agenda="", packet=f"{GCS}/agenda-packet-2026-05-04.pdf"):
    return f'''
    <ul><li><a data-toggle="tab" href="#tab-agenda">Agenda</a></li></ul>
    <div class="tab-content">
      <div id="tab-agenda" class="tab-pane fade in active">
        <div class="row"><div class="col-md-9">{agenda_body}</div></div>
      </div>
      {after_agenda}
      <div id="tab-agenda-packet" class="tab-pane fade">{_file_block(packet, "agenda-packet-2026-05-04")}</div>
      <div id="tab-minutes" class="tab-pane fade"></div>
    </div>'''


SR_BODY = (f'<p>CONSENT CALENDAR<br/><a href="{GCS}/2.a-minutes-2026-04-20.pdf">Minutes</a><br/>'
           f'<a href="{GCS}/2.b-harbor-spit-lighting.pdf">Staff Report</a><br/>'
           f'<a href="{GCS}/letter-from-a-resident.pdf">Correspondence</a></p>')
AGENDA = f"{GCS}/cc-agenda-2026-05-04.pdf"


class TestAttachedAgendaArtifact:
    def test_the_attached_file_is_the_agenda_not_the_first_pdf(self):
        html = _detail(SR_BODY + "</div><div class=\"col-md-3\">" + _file_block(AGENDA) + _file_block(AGENDA))
        assert extract_artifacts_from_detail(html, agenda_artifact="attached")["agenda"] == \
            {"available": True, "url": AGENDA}
        # Today's rule, unchanged when the option is absent: the first PDF in the tab.
        assert extract_artifacts_from_detail(html)["agenda"] == \
            {"available": True, "url": f"{GCS}/2.a-minutes-2026-04-20.pdf"}

    def test_no_attached_file_is_unavailable_with_a_reason_never_the_first_pdf(self):
        got = extract_artifacts_from_detail(_detail(SR_BODY), agenda_artifact="attached")["agenda"]
        assert got == {"available": False, "url": None, "reason": "no attached file in the agenda tab"}

    def test_no_agenda_tab_is_unavailable_with_a_reason(self):
        html = f'<div id="tab-minutes">{_file_block(f"{GCS}/cc-minutes.pdf")}</div>'
        got = extract_artifacts_from_detail(html, agenda_artifact="attached")["agenda"]
        assert got == {"available": False, "url": None, "reason": "no agenda tab"}

    def test_two_distinct_attached_files_are_unavailable_no_tie_break(self):
        other = f"{GCS}/cc-agenda-2026-05-04-revised.pdf"
        html = _detail(SR_BODY + _file_block(AGENDA) + _file_block(other, "revised"))
        got = extract_artifacts_from_detail(html, agenda_artifact="attached")["agenda"]
        assert got == {"available": False, "url": None, "reason": "2 attached files in the agenda tab"}

    def test_other_tabs_are_selected_exactly_as_before(self):
        html = _detail(SR_BODY + _file_block(AGENDA))
        new, old = extract_artifacts_from_detail(html, agenda_artifact="attached"), extract_artifacts_from_detail(html)
        assert {k: v for k, v in new.items() if k != "agenda"} == {k: v for k, v in old.items() if k != "agenda"}
        assert new["packet"] == {"available": True, "url": f"{GCS}/agenda-packet-2026-05-04.pdf"}

    def test_the_agenda_element_bounds_the_search_not_the_next_known_tab(self):
        # A download in a following unknown tab (contact) or after the agenda element is not the agenda's.
        contact = f'<div id="tab-contact" class="tab-pane fade">{_file_block(f"{GCS}/clerk-contacts.pdf")}</div>'
        html = _detail(SR_BODY, after_agenda=contact) + _file_block(f"{GCS}/outside.pdf")
        got = extract_artifacts_from_detail(html, agenda_artifact="attached")["agenda"]
        assert got == {"available": False, "url": None, "reason": "no attached file in the agenda tab"}

    def test_an_attachment_far_into_a_last_agenda_tab_is_found(self):
        filler = "<p>" + "Item text. " * 2000 + "</p>"  # well past the legacy 8 KB tail
        html = f'<div id="tab-agenda"><div>{SR_BODY}{filler}</div>{_file_block(AGENDA)}</div>'
        assert extract_artifacts_from_detail(html, agenda_artifact="attached")["agenda"] == \
            {"available": True, "url": AGENDA}

    def test_attribute_variants_single_quotes_and_a_bare_download(self):
        html = _detail(SR_BODY + _file_block(AGENDA, quote="'", download="download"))
        assert extract_artifacts_from_detail(html, agenda_artifact="attached")["agenda"] == \
            {"available": True, "url": AGENDA}

    def test_a_download_that_is_not_a_pdf_does_not_count(self):
        html = _detail(SR_BODY + _file_block(f"{GCS}/agenda.docx") + _file_block(f"{AGENDA}?v=2"))
        assert extract_artifacts_from_detail(html, agenda_artifact="attached")["agenda"] == \
            {"available": True, "url": f"{AGENDA}?v=2"}

    def test_an_unknown_option_is_refused(self):
        with pytest.raises(ValueError, match="agenda_artifact"):
            extract_artifacts_from_detail(_detail(SR_BODY), agenda_artifact="first")

    def test_capture_applies_the_registry_option(self, tmp_path):
        list_html = '<table><tr><td><a href="/meetings/m1/">Council: May 4, 2026</a></td></tr></table>'
        detail = _detail(SR_BODY + _file_block(AGENDA))
        pages = {"https://example.gov/meetings/m1/": detail}
        results = {}
        for option in (None, "attached"):
            config = {"id": "test", "adapter": "proudcity", "url": "https://example.gov/meetings/",
                      "jurisdiction_id": "place-test", "institution_id": "org-test"}
            if option:
                config["agenda_artifact"] = option
            adapter = ProudCityAdapter(config, tmp_path / str(option))
            adapter._request_delay = 0
            adapter._fetch_page = lambda url: pages.get(url, list_html)
            results[option] = adapter.capture()["meetings"][0]["artifacts"]["agenda"]["url"]
        assert results == {None: f"{GCS}/2.a-minutes-2026-04-20.pdf", "attached": AGENDA}


def test_only_san_rafael_opts_into_the_attached_agenda_rule():
    import yaml

    sources = yaml.safe_load((Path(__file__).resolve().parent.parent / "registry" / "proudcity-sources.yaml")
                             .read_text())["sources"]
    assert {s["id"]: s.get("agenda_artifact") for s in sources if s.get("agenda_artifact")} == \
        {"san-rafael-city-council": "attached"}


def test_fairfax_saved_page_is_unchanged_by_the_option_it_does_not_set():
    # Fairfax and Belvedere set no agenda_artifact: their pages go through the untouched first-PDF path.
    html = (FIXTURES / "wordpress-fairfax-meeting.html").read_text(errors="ignore")
    assert extract_artifacts_from_detail(html, agenda_artifact=None) == extract_artifacts_from_detail(html)


def test_a_bad_registry_option_stops_the_capture_before_any_detail_page(tmp_path):
    config = {"id": "test", "adapter": "proudcity", "url": "https://example.gov/meetings/",
              "jurisdiction_id": "place-test", "institution_id": "org-test", "agenda_artifact": "first"}
    adapter = ProudCityAdapter(config, tmp_path)
    adapter._fetch_page = lambda url: pytest.fail(f"fetched {url}")
    with pytest.raises(ValueError, match="agenda_artifact"):
        adapter.capture()


def test_an_attached_file_that_is_also_the_packet_is_no_agenda():
    # A meeting whose agenda tab attaches the agenda packet: one url on two artifacts of a meeting holds
    # the whole load (guarded_load artifact_url_shared), and the packet Record already carries it.
    packet = f"{GCS}/agenda-packet-2026-05-04.pdf"
    html = _detail(SR_BODY + _file_block(packet, "agenda-packet-2026-05-04"), packet=packet)
    got = extract_artifacts_from_detail(html, agenda_artifact="attached")
    assert got["agenda"] == {"available": False, "url": None,
                             "reason": "the agenda tab's attached file is this meeting's packet"}
    assert got["packet"] == {"available": True, "url": packet}


class TestAttachedAgendaBoundaries:
    """Codex diff r1: the agenda element must be a div that visibly opens and closes; anything else is no agenda."""

    CONTACT = f'<div id="tab-contact">{_file_block(f"{GCS}/clerk-contacts.pdf")}</div>'

    def _agenda(self, html):
        return extract_artifacts_from_detail(html, agenda_artifact="attached")["agenda"]

    def test_an_id_on_a_void_element_is_no_agenda_tab(self):
        got = self._agenda(f'<input id="tab-agenda">{self.CONTACT}')
        assert got == {"available": False, "url": None, "reason": "no agenda tab"}

    def test_an_ancestor_closing_inside_the_agenda_element_is_refused(self):
        got = self._agenda(f'<main><div id="tab-agenda">{SR_BODY}</main>{self.CONTACT}')
        assert got == {"available": False, "url": None, "reason": "the agenda tab is not well-formed"}

    def test_an_agenda_element_that_never_closes_is_refused(self):
        got = self._agenda(f'<div id="tab-agenda">{SR_BODY}{_file_block(AGENDA)}')
        assert got == {"available": False, "url": None, "reason": "the agenda tab is not well-formed"}

    def test_an_element_left_open_inside_a_closed_div_cannot_mask_an_outer_close(self):
        # Codex diff r2: an inner <section> never closed inside its div must not absorb the outer </section>.
        html = (f'<section><div id="tab-agenda"><div><section>body</div></section>'
                f'{self.CONTACT}</div>')
        got = self._agenda(html)
        assert got == {"available": False, "url": None, "reason": "the agenda tab is not well-formed"}

    def test_stray_paragraph_and_list_ends_inside_are_harmless(self):
        got = self._agenda(f'<div id="tab-agenda"><p>One<p>Two</p></li>{_file_block(AGENDA)}</div>{self.CONTACT}')
        assert got == {"available": True, "url": AGENDA}

    def test_a_relative_attached_url_is_refused_not_kept(self):
        for href in ("/files/agenda.PDF?v=2", "//storage.example/agenda.pdf"):
            got = self._agenda(_detail(SR_BODY + _file_block(href)))
            assert got == {"available": False, "url": None, "reason": "an attached file's url is not absolute http(s)"}

    def test_a_malformed_url_is_contained_and_other_tabs_survive(self):
        got = extract_artifacts_from_detail(_detail(SR_BODY + _file_block("https://[broken/agenda.pdf")),
                                            agenda_artifact="attached")
        assert got["agenda"]["available"] is False and got["agenda"]["reason"].startswith("the agenda tab could not be read")
        assert got["packet"] == {"available": True, "url": f"{GCS}/agenda-packet-2026-05-04.pdf"}

    def test_the_packet_collision_compares_decoded_urls(self):
        packet = f"{GCS}/agenda-packet-a&amp;b.pdf"
        html = _detail(SR_BODY + _file_block(packet), packet=packet)
        assert self._agenda(html) == {"available": False, "url": None,
                                      "reason": "the agenda tab's attached file is this meeting's packet"}
