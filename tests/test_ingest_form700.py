"""Tests for ingest_form700.py — Form 700 index ingestion via the NetFile JSON API.

No live HTTP: every API response comes from a recorded fixture under
tests/fixtures/form700/searchfilings/ (see SOURCES.md there).
"""

from __future__ import annotations

import copy
import json
import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ingest_form700  # noqa: E402
from ingest_form700 import (  # noqa: E402
    KNOWN_AGENCIES,
    build_filing_node,
    build_filed_by_edge,
    build_in_jurisdiction_edge,
    build_nodes_and_edges,
    build_search_body,
    fetch_filings_for_agency,
    main,
    normalize_name,
    parse_filings_page,
    slugify,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "form700" / "searchfilings"
PAGE_FIRST = json.loads((FIXTURES / "ross-page-1.json").read_text(encoding="utf-8"))
PAGE_LAST = json.loads((FIXTURES / "ross-page-60.json").read_text(encoding="utf-8"))
RECORDED_ITEMS = PAGE_FIRST["items"] + PAGE_LAST["items"]

# The April 2026 output of the (then-working) HTML scraper for the same filing,
# copied verbatim from data/normalized/form700/nodes.jsonl. The JSON path must
# reproduce it byte-for-byte so graph ids and extract_form700_interiors agree.
APRIL_AHRENS_FILING = {
    "id": "filing-form700-ross-2022-06-02-ahrens-thomas-leaving-office-building-official-building",
    "node_type": "Filing",
    "labels": ["Filing"],
    "display_label": "Form 700 — Thomas Ahrens (Leaving Office) — 2022-06-02",
    "properties": {
        "filing_type": "form_700",
        "filer_name": "Ahrens, Thomas",
        "filed_at": "2022-06-02",
        "statement_type": "Leaving Office",
        "job_title": "Building Official",
        "department": "Building",
        "agency_id": "ross",
        "agency": "Town of Ross",
    },
}
APRIL_WOLTERING_FILING_ID = (
    "filing-form700-ross-2022-02-28-woltering-david-annual-planning-and-building-director-planning"
)


def paged_server(items: list[dict], page_size: int, calls: list[dict] | None = None):
    """A fake post_json serving `items` in consistent recorded-shape envelopes."""
    pages = [items[i : i + page_size] for i in range(0, len(items), page_size)] or [[]]

    def post_json(url: str, body: dict) -> dict:
        if calls is not None:
            calls.append(copy.deepcopy(body))
        n = body["currentPage"]
        return {
            "aid": body["aid"],
            "items": copy.deepcopy(pages[n - 1]),
            "pageSize": page_size,
            "currentPage": n,
            "pageCount": len(pages),
            "totalCount": len(items),
            "hasNextPage": n < len(pages),
            "hasPreviousPage": n > 1,
        }

    return post_json


# ---------------------------------------------------------------------------
# Agencies
# ---------------------------------------------------------------------------


class TestKnownAgencies:
    def test_nine_netfile_agency_ids_preserved(self):
        assert set(KNOWN_AGENCIES) == {
            "cmar", "raf", "nvo", "sau", "tib", "ctm", "lark", "smo", "ross",
        }

    def test_place_ids_preserved(self):
        assert KNOWN_AGENCIES["cmar"]["place_id"] == "place-marin-county"
        assert KNOWN_AGENCIES["raf"]["place_id"] == "place-san-rafael"
        assert KNOWN_AGENCIES["ross"]["place_id"] == "place-ross"

    def test_portal_urls_point_at_new_sei_spa(self):
        for aid, info in KNOWN_AGENCIES.items():
            assert info["url"] == f"https://netfile.com/public/{aid.upper()}/sei"


# ---------------------------------------------------------------------------
# Request contract
# ---------------------------------------------------------------------------


class TestBuildSearchBody:
    def test_body_shape(self):
        body = build_search_body("ross", date(2019, 1, 1), date(2026, 9, 28), page=2, page_size=100)
        assert body == {
            "aid": "ROSS",
            "searchFilerName": "",
            "searchStatementType": None,
            "afterFilingDate": "2019-01-01",
            "beforeFilingDate": "2026-09-28",
            "currentPage": 2,
            "pageSize": 100,
        }


class TestPostJson:
    def test_sends_json_post_with_curl_style_user_agent(self, monkeypatch):
        seen = {}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(PAGE_LAST).encode()

        def fake_urlopen(req, timeout):
            seen["req"] = req
            return FakeResp()

        monkeypatch.setattr(ingest_form700.urllib.request, "urlopen", fake_urlopen)
        out = ingest_form700._post_json(ingest_form700.API_URL, {"aid": "ROSS"})
        req = seen["req"]
        assert out == PAGE_LAST
        assert req.full_url == "https://netfile.com/api/public/sites/api/searchfilings"
        assert req.get_method() == "POST"
        assert json.loads(req.data) == {"aid": "ROSS"}
        assert req.get_header("Content-type") == "application/json"
        # The WAF 403s urllib's default UA; a curl-style UA is required.
        assert req.get_header("User-agent").startswith("curl/")


# ---------------------------------------------------------------------------
# Parser: JSON page → row dicts (same shape the HTML parser produced)
# ---------------------------------------------------------------------------


class TestParseFilingsPage:
    def test_maps_recorded_items_to_row_schema(self):
        rows = parse_filings_page(PAGE_FIRST)
        assert rows[1] == {
            "filer_name": "Ahrens, Thomas",
            "filed_at": "2022-06-02",
            "statement_type": "Leaving Office",
            "job_title": "Building Official",
            "department": "Building",
        }

    def test_one_row_per_item(self):
        assert len(parse_filings_page(PAGE_FIRST)) == len(PAGE_FIRST["items"])

    def test_filed_at_is_agency_local_calendar_date(self):
        # "2026-05-13T08:26:01.48" is agency-local (no Z): take the date as printed.
        assert parse_filings_page(PAGE_FIRST)[0]["filed_at"] == "2026-05-13"

    def test_strips_and_tolerates_null_fields(self):
        item = dict(PAGE_LAST["items"][0], positionName=None, departmentName="  Planning ")
        row = parse_filings_page({"items": [item]})[0]
        assert row["job_title"] == ""
        assert row["department"] == "Planning"

    def test_empty_items_returns_empty_list(self):
        assert parse_filings_page({"items": []}) == []

    @pytest.mark.parametrize("payload", [{}, {"items": None}, [], "<html></html>"])
    def test_malformed_payload_raises(self, payload):
        with pytest.raises(ValueError):
            parse_filings_page(payload)


class TestOutputSchemaUnchanged:
    def test_filing_node_matches_april_output_byte_for_byte(self):
        nodes, _ = build_nodes_and_edges(parse_filings_page(PAGE_FIRST), "ross")
        ahrens = next(n for n in nodes if n["id"] == APRIL_AHRENS_FILING["id"])
        assert json.dumps(ahrens, ensure_ascii=False) == json.dumps(
            APRIL_AHRENS_FILING, ensure_ascii=False
        )

    def test_last_page_filing_id_matches_april_output(self):
        nodes, _ = build_nodes_and_edges(parse_filings_page(PAGE_LAST), "ross")
        assert nodes[0]["id"] == APRIL_WOLTERING_FILING_ID

    def test_edges_and_person_nodes(self):
        nodes, edges = build_nodes_and_edges(parse_filings_page(PAGE_FIRST), "ross")
        people = [n for n in nodes if n["node_type"] == "Person"]
        assert {p["id"] for p in people} == {
            "person-f700-raul-aguilar", "person-f700-thomas-ahrens",
        }
        assert {e["relationship_type"] for e in edges} == {"FILED_BY", "IN_JURISDICTION"}
        assert len(edges) == 2 * len(PAGE_FIRST["items"])


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------


class TestFetchPaging:
    def test_collects_every_page(self):
        calls: list[dict] = []
        rows = fetch_filings_for_agency(
            "ross",
            date(2019, 1, 1),
            post_json=paged_server(RECORDED_ITEMS, page_size=2, calls=calls),
            page_size=2,
        )
        assert [c["currentPage"] for c in calls] == [1, 2]
        assert [r["filer_name"] for r in rows] == [
            "Aguilar, Raul", "Ahrens, Thomas", "Ahrens, Thomas", "Woltering, David",
        ]

    def test_requests_use_agency_aid_and_floor(self):
        calls: list[dict] = []
        fetch_filings_for_agency(
            "cmar", date(2020, 1, 1), post_json=paged_server(RECORDED_ITEMS, 3, calls), page_size=3
        )
        assert {c["aid"] for c in calls} == {"CMAR"}
        assert {c["afterFilingDate"] for c in calls} == {"2020-01-01"}
        assert {c["pageSize"] for c in calls} == {3}

    def test_floor_date_filters_client_side(self):
        rows = fetch_filings_for_agency(
            "ross", date(2022, 6, 1), post_json=paged_server(RECORDED_ITEMS, 4)
        )
        assert [r["filed_at"] for r in rows] == ["2026-05-13", "2022-06-02"]

    def test_short_read_against_total_count_raises(self):
        # The recorded last page claims totalCount=178 but holds one item.
        with pytest.raises(RuntimeError, match="178"):
            fetch_filings_for_agency("ross", post_json=lambda url, body: PAGE_LAST)

    def test_empty_page_with_has_next_raises(self):
        def post_json(url, body):
            return dict(PAGE_FIRST, items=[], currentPage=body["currentPage"])

        with pytest.raises(RuntimeError):
            fetch_filings_for_agency("ross", post_json=post_json)

    def test_failure_mid_paging_propagates(self):
        def post_json(url, body):
            if body["currentPage"] == 1:
                return PAGE_FIRST
            raise urllib.error.URLError("boom")

        with pytest.raises(urllib.error.URLError):
            fetch_filings_for_agency("ross", post_json=post_json)

    def test_unknown_agency_raises(self):
        with pytest.raises(ValueError):
            fetch_filings_for_agency("zzz", post_json=paged_server(RECORDED_ITEMS, 4))


# ---------------------------------------------------------------------------
# CLI: never overwrite on empty / failed pulls
# ---------------------------------------------------------------------------


@pytest.fixture
def prior_output(tmp_path):
    out = tmp_path / "form700"
    out.mkdir()
    (out / "nodes.jsonl").write_bytes(b'{"id": "filing-form700-prior"}\n')
    (out / "edges.jsonl").write_bytes(b'{"source_id": "filing-form700-prior"}\n')
    snapshot = {p.name: p.read_bytes() for p in out.iterdir()}
    return out, snapshot


@pytest.fixture
def no_load(monkeypatch):
    calls: list = []
    monkeypatch.setattr(ingest_form700, "_load_into_neo4j", lambda **kw: calls.append(kw))
    return calls


def _server_by_aid(by_aid: dict):
    def post_json(url, body):
        handler = by_aid[body["aid"]]
        return handler(url, body)

    return post_json


class TestMainNeverOverwritesOnFailure:
    def _run(self, monkeypatch, out, post_json, *extra):
        monkeypatch.setattr(ingest_form700, "_post_json", post_json)
        return main(["--output-dir", str(out), "--password", "x", "--load", *extra])

    def test_zero_rows_exits_nonzero_and_leaves_files_byte_identical(
        self, monkeypatch, prior_output, no_load
    ):
        out, snapshot = prior_output
        rc = self._run(monkeypatch, out, paged_server([], 100), "--agency", "ross")
        assert rc != 0
        assert {p.name: p.read_bytes() for p in out.iterdir()} == snapshot
        assert no_load == []

    def test_fetch_error_exits_nonzero_and_leaves_files_byte_identical(
        self, monkeypatch, prior_output, no_load
    ):
        out, snapshot = prior_output

        def boom(url, body):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

        rc = self._run(monkeypatch, out, boom, "--agency", "ross")
        assert rc != 0
        assert {p.name: p.read_bytes() for p in out.iterdir()} == snapshot
        assert no_load == []

    def test_one_failed_agency_in_all_blocks_the_whole_write(
        self, monkeypatch, prior_output, no_load
    ):
        out, snapshot = prior_output
        good = paged_server(RECORDED_ITEMS, 100)
        handlers = {aid.upper(): good for aid in KNOWN_AGENCIES}
        handlers["TIB"] = paged_server([], 100)
        rc = self._run(monkeypatch, out, _server_by_aid(handlers), "--all")
        assert rc != 0
        assert {p.name: p.read_bytes() for p in out.iterdir()} == snapshot
        assert no_load == []

    def test_success_writes_outputs_then_loads(self, monkeypatch, prior_output, no_load):
        out, _ = prior_output
        rc = self._run(monkeypatch, out, paged_server(RECORDED_ITEMS, 2), "--agency", "ross")
        assert rc == 0
        nodes = [json.loads(line) for line in (out / "nodes.jsonl").read_text().splitlines()]
        edges = [json.loads(line) for line in (out / "edges.jsonl").read_text().splitlines()]
        assert APRIL_AHRENS_FILING in nodes
        assert sum(n["node_type"] == "Filing" for n in nodes) == len(RECORDED_ITEMS)
        assert len(edges) == 2 * len(RECORDED_ITEMS)
        assert sorted(p.name for p in out.iterdir()) == ["edges.jsonl", "nodes.jsonl"]
        assert len(no_load) == 1 and no_load[0]["nodes"] == nodes


# ---------------------------------------------------------------------------
# TestNormalizeName
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_last_first_inverted(self):
        assert normalize_name("Colin, Kate") == "Kate Colin"

    def test_single_name_unchanged(self):
        assert normalize_name("Madonna") == "Madonna"

    def test_already_normal_order(self):
        # If no comma, return as-is
        assert normalize_name("Kate Colin") == "Kate Colin"

    def test_strips_whitespace(self):
        assert normalize_name("  Hill, Eli  ") == "Eli Hill"

    def test_middle_name_preserved(self):
        assert normalize_name("Smith, John A.") == "John A. Smith"


# ---------------------------------------------------------------------------
# TestSlugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic_slug(self):
        assert slugify("Kate Colin") == "kate-colin"

    def test_comma_and_space(self):
        assert slugify("Colin, Kate") == "colin-kate"

    def test_special_chars_replaced(self):
        assert slugify("O'Brien, Sean") == "o-brien-sean"

    def test_multiple_spaces_collapsed(self):
        assert slugify("City  Council") == "city-council"

    def test_lowercase(self):
        assert slugify("ANNUAL") == "annual"


# ---------------------------------------------------------------------------
# TestBuildFilingNode
# ---------------------------------------------------------------------------


class TestBuildFilingNode:
    def _row(self, **overrides) -> dict:
        base = {
            "filer_name": "Colin, Kate",
            "filed_at": "2025-03-15",
            "statement_type": "Annual",
            "job_title": "Mayor",
            "department": "City Council",
        }
        base.update(overrides)
        return base

    def test_node_type_is_filing(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["node_type"] == "Filing"

    def test_labels_contains_filing(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert "Filing" in node["labels"]

    def test_filing_type_is_form_700(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["filing_type"] == "form_700"

    def test_filer_name_preserved(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["filer_name"] == "Colin, Kate"

    def test_filed_at_preserved(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["filed_at"] == "2025-03-15"

    def test_statement_type_preserved(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["statement_type"] == "Annual"

    def test_job_title_preserved(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["job_title"] == "Mayor"

    def test_department_preserved(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["properties"]["department"] == "City Council"

    def test_id_prefix(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert node["id"].startswith("filing-form700-raf-")

    def test_id_is_deterministic(self):
        row = self._row()
        n1 = build_filing_node(row, agency_id="raf")
        n2 = build_filing_node(row, agency_id="raf")
        assert n1["id"] == n2["id"]

    def test_id_differs_by_agency(self):
        row = self._row()
        n_raf = build_filing_node(row, agency_id="raf")
        n_cmar = build_filing_node(row, agency_id="cmar")
        assert n_raf["id"] != n_cmar["id"]

    def test_id_contains_date_and_name_slug(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert "2025-03-15" in node["id"]
        assert "colin-kate" in node["id"]

    def test_agency_id_stored_in_properties(self):
        node = build_filing_node(self._row(), agency_id="cmar")
        assert node["properties"]["agency_id"] == "cmar"

    def test_cmar_agency_label(self):
        node = build_filing_node(self._row(), agency_id="cmar", agency_label="Marin County")
        assert node["properties"]["agency"] == "Marin County"

    def test_agency_label_defaults_to_agency_id_upper(self):
        node = build_filing_node(self._row(), agency_id="raf")
        # Without explicit label, should still have agency field
        assert "agency_id" in node["properties"]

    def test_display_label_contains_filer(self):
        node = build_filing_node(self._row(), agency_id="raf")
        assert "Colin" in node["display_label"] or "Kate" in node["display_label"]


# ---------------------------------------------------------------------------
# TestBuildFiledByEdge
# ---------------------------------------------------------------------------


class TestBuildFiledByEdge:
    def test_relationship_type(self):
        edge = build_filed_by_edge("filing-form700-raf-abc", "person-kate-colin")
        assert edge["relationship_type"] == "FILED_BY"

    def test_source_is_filing(self):
        edge = build_filed_by_edge("filing-form700-raf-abc", "person-kate-colin")
        assert edge["source_id"] == "filing-form700-raf-abc"

    def test_target_is_person(self):
        edge = build_filed_by_edge("filing-form700-raf-abc", "person-kate-colin")
        assert edge["target_id"] == "person-kate-colin"

    def test_properties_is_dict(self):
        edge = build_filed_by_edge("filing-form700-raf-abc", "person-kate-colin")
        assert isinstance(edge["properties"], dict)


# ---------------------------------------------------------------------------
# TestBuildInJurisdictionEdge
# ---------------------------------------------------------------------------


class TestBuildInJurisdictionEdge:
    def test_relationship_type(self):
        edge = build_in_jurisdiction_edge("filing-form700-raf-abc", "place-san-rafael")
        assert edge["relationship_type"] == "IN_JURISDICTION"

    def test_source_is_filing(self):
        edge = build_in_jurisdiction_edge("filing-form700-raf-abc", "place-san-rafael")
        assert edge["source_id"] == "filing-form700-raf-abc"

    def test_target_is_place(self):
        edge = build_in_jurisdiction_edge("filing-form700-raf-abc", "place-san-rafael")
        assert edge["target_id"] == "place-san-rafael"

    def test_properties_is_dict(self):
        edge = build_in_jurisdiction_edge("filing-form700-raf-abc", "place-san-rafael")
        assert isinstance(edge["properties"], dict)


# ---------------------------------------------------------------------------
# TestPersonIdFromName
# ---------------------------------------------------------------------------


class TestPersonIdFromName:
    """Test the person ID lookup / generation logic."""

    def setup_method(self):
        from ingest_form700 import person_id_from_name
        self.fn = person_id_from_name

    def test_generates_stable_id(self):
        pid = self.fn("Colin, Kate")
        assert pid == self.fn("Colin, Kate")

    def test_inverted_and_normal_match(self):
        # "Colin, Kate" and "Kate Colin" should produce the same stable ID
        pid_inverted = self.fn("Colin, Kate")
        pid_normal = self.fn("Kate Colin")
        assert pid_inverted == pid_normal

    def test_id_prefix(self):
        pid = self.fn("Colin, Kate")
        assert pid.startswith("person-f700-"), (
            f"Form 700 person IDs must use 'f700' namespace: {pid}"
        )

    def test_id_is_lowercase_slug(self):
        pid = self.fn("Colin, Kate")
        assert pid == pid.lower()
        assert " " not in pid
        assert "," not in pid

    def test_no_collision_with_campaign_finance(self):
        """Form 700 person IDs must not collide with campaign finance person IDs."""
        pid = self.fn("Smith, John")
        assert "f700" in pid, f"Form 700 person ID must be namespaced: {pid}"
