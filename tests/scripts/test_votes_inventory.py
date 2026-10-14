"""Votes Part A, increment a: the frozen meeting/minutes inventory for the two bodies."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from votes_inventory import (  # noqa: E402
    BODIES,
    InventoryError,
    build_inventory,
    classify_meeting,
    fetch_gaps,
    load_inventory,
    main,
    verify_documents,
    write_inventory,
)

NOVATO = "novato-city-council"
BOS = "marin-county-bos"


def _meeting(mid, date, title):
    return {"id": mid, "labels": ["Meeting"],
            "properties": {"id": mid, "meeting_date": date, "title": title}}


def _record(rid, url):
    return {"id": rid, "labels": ["Record"],
            "properties": {"id": rid, "record_type": "meeting_minutes", "preferred_public_url": url}}


def _edge(s, t, rel="EVIDENCED_BY"):
    return {"start_id": s, "end_id": t, "type": rel, "properties": {}}


def _write_export(root: Path, nodes, edges) -> Path:
    d = root / "export"
    d.mkdir()
    (d / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    (d / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges))
    return d


@pytest.fixture
def world(tmp_path):
    """Two Novato meetings (one cached, one with a record but no file), one Novato meeting with no
    minutes record, one planning commission meeting, one out-of-window meeting, and two BOS meetings
    where a dated cache file is byte-identical to a meeting-keyed one."""
    nodes = [
        _meeting(f"meeting-{NOVATO}-101", "2019-02-05", "City Council"),
        _meeting(f"meeting-{NOVATO}-102", "2019-03-05", "City Council"),
        _meeting(f"meeting-{NOVATO}-103", "2019-04-02", "City Council Closed Session (No Video)"),
        _meeting(f"meeting-{NOVATO}-104", "2019-04-09", "Planning Commission"),
        _meeting(f"meeting-{NOVATO}-105", "2026-09-01", "City Council"),
        _meeting(f"meeting-{BOS}-201", "2020-05-19", "Board of Supervisors 2020"),
        _meeting(f"meeting-{BOS}-202", "2025-12-16", "Board of Supervisors 2025"),
        _record(f"record-{NOVATO}-101-minutes", "https://example.invalid/m/101"),
        _record(f"record-{NOVATO}-102-minutes", "//example.invalid/m/102"),
        _record(f"record-{BOS}-201-minutes", "https://example.invalid/b/201"),
        _record(f"record-{BOS}-202-minutes", "https://example.invalid/b/202"),
        {"id": "decision-x", "labels": ["Decision"], "properties": {"id": "decision-x"}},
    ]
    edges = [
        _edge(f"meeting-{NOVATO}-101", f"record-{NOVATO}-101-minutes"),
        _edge(f"meeting-{NOVATO}-102", f"record-{NOVATO}-102-minutes"),
        _edge(f"meeting-{BOS}-201", f"record-{BOS}-201-minutes"),
        _edge(f"meeting-{BOS}-202", f"record-{BOS}-202-minutes"),
    ]
    export = _write_export(tmp_path, nodes, edges)
    raw = tmp_path / "raw"
    (raw / NOVATO / "minutes").mkdir(parents=True)
    (raw / BOS / "minutes").mkdir(parents=True)
    (raw / BOS / "minutes-test").mkdir(parents=True)
    (raw / NOVATO / "minutes" / f"meeting-{NOVATO}-101.pdf").write_bytes(b"%PDF-1.4 fictional 101")
    (raw / BOS / "minutes" / f"meeting-{BOS}-201.html").write_bytes(b"<html>fictional 201</html>")
    (raw / BOS / "minutes" / f"meeting-{BOS}-202.html").write_bytes(b"<html>fictional 202</html>")
    (raw / BOS / "minutes-test" / "2025-12-16.pdf").write_bytes(b"<html>fictional 202</html>")
    windows = {NOVATO: ("2019-01-01", "2026-03-10"), BOS: ("2019-01-01", "2026-03-20")}
    return {"export": export, "raw": raw, "fetched": tmp_path / "fetched", "windows": windows,
            "tmp": tmp_path}


def _build(world):
    return build_inventory(world["export"], world["raw"], world["fetched"], world["windows"])


def _row(inv, mid):
    return next(r for b in inv["bodies"].values() for r in b["meetings"] if r["meeting_id"] == mid)


class TestClassify:
    @pytest.mark.parametrize("title,expected", [
        ("City Council", "council"),
        ("City Council Closed Session (No Video)", "council"),
        ("Joint City Council / City Council as Successor Agency", "council_joint"),
        ("Joint City Council / Novato Public Finance Authority", "council_joint"),
        ("Planning Commission", "planning_commission"),
        ("Planning Commission Hearing", "planning_commission"),
        ("Joint Special Meeting - City Council / Design Review Commission / Planning Commission",
         "council_joint"),
        ("State of the City", "council_other"),
    ])
    def test_novato_titles(self, title, expected):
        assert classify_meeting(NOVATO, title) == expected

    @pytest.mark.parametrize("title,expected", [
        ("Board of Supervisors 2020", "bos"),
        ("Budget 2021", "bos"),
        ("Joint BOS/Planning Commission", "bos_joint"),
        ("Spanish Audio Files", "bos_media_duplicate"),
        ("TRUTH Act Forum", "bos_other"),
    ])
    def test_bos_titles(self, title, expected):
        assert classify_meeting(BOS, title) == expected

    def test_planning_commission_is_out_of_scope_everything_else_in(self):
        assert BODIES[NOVATO]["out_of_scope_classes"] == {"planning_commission"}
        assert BODIES[BOS]["out_of_scope_classes"] == set()


class TestBuild:
    def test_every_in_window_meeting_appears_once_out_of_window_never(self, world):
        inv = _build(world)
        ids = [r["meeting_id"] for b in inv["bodies"].values() for r in b["meetings"]]
        assert sorted(ids) == sorted(set(ids))
        assert f"meeting-{NOVATO}-105" not in ids
        assert len(ids) == 6

    def test_cached_document_is_hashed(self, world):
        r = _row(_build(world), f"meeting-{NOVATO}-101")
        assert r["gap"] is None
        [doc] = r["documents"]
        assert doc["sha256"] == hashlib.sha256(b"%PDF-1.4 fictional 101").hexdigest()
        assert doc["format"] == "pdf" and doc["origin"] == "cache"
        assert doc["paths"] == [f"raw/{NOVATO}/minutes/meeting-{NOVATO}-101.pdf"]

    def test_record_without_file_is_a_fetchable_gap(self, world):
        r = _row(_build(world), f"meeting-{NOVATO}-102")
        assert r["documents"] == []
        assert r["gap"] == "not_cached"
        assert r["minutes_url"] == "https://example.invalid/m/102"  # protocol-relative normalized

    def test_meeting_without_minutes_record_is_a_gap(self, world):
        r = _row(_build(world), f"meeting-{NOVATO}-103")
        assert r["minutes_record_id"] is None and r["gap"] == "no_minutes_record"

    def test_out_of_scope_body_is_listed_with_its_gap_reason(self, world):
        r = _row(_build(world), f"meeting-{NOVATO}-104")
        assert r["body_class"] == "planning_commission" and r["gap"] == "not_in_scope_body"

    def test_identical_dated_file_merges_into_the_meeting_document(self, world):
        r = _row(_build(world), f"meeting-{BOS}-202")
        [doc] = r["documents"]
        assert doc["paths"] == [f"raw/{BOS}/minutes-test/2025-12-16.pdf",
                                f"raw/{BOS}/minutes/meeting-{BOS}-202.html"]
        assert doc["format"] == "html"  # sniffed from content, not the extension

    def test_distinct_dated_file_becomes_a_second_document(self, world):
        (world["raw"] / BOS / "minutes-test" / "2020-05-19.pdf").write_bytes(b"%PDF-1.6 other")
        r = _row(_build(world), f"meeting-{BOS}-201")
        assert [d["origin"] for d in r["documents"]] == ["cache", "cache_dated"]

    def test_dated_file_matching_no_meeting_is_recorded_unplaced(self, world):
        (world["raw"] / BOS / "minutes-test" / "2021-01-01.pdf").write_bytes(b"%PDF-1.6 x")
        inv = _build(world)
        assert inv["bodies"][BOS]["unplaced_documents"][0]["paths"] == [
            f"raw/{BOS}/minutes-test/2021-01-01.pdf"]

    def test_inventory_pins_its_inputs(self, world):
        inv = _build(world)
        assert inv["export"]["nodes_sha256"] == hashlib.sha256(
            (world["export"] / "nodes.jsonl").read_bytes()).hexdigest()
        assert inv["windows"][BOS] == ["2019-01-01", "2026-03-20"]
        assert "pdftotext" in inv["tools"]

    def test_fetched_documents_are_picked_up(self, world):
        world["fetched"].mkdir()
        (world["fetched"] / f"meeting-{NOVATO}-102.pdf").write_bytes(b"%PDF-1.4 fetched")
        r = _row(_build(world), f"meeting-{NOVATO}-102")
        assert r["gap"] is None and r["documents"][0]["origin"] == "fetched"

    def test_a_recorded_fetch_failure_is_kept_as_the_gap(self, world):
        world["fetched"].mkdir()
        (world["fetched"] / "fetch-log.jsonl").write_text(json.dumps(
            {"meeting_id": f"meeting-{NOVATO}-102", "status": "failed", "error": "http_404",
             "attempt": 3}) + "\n")
        assert _row(_build(world), f"meeting-{NOVATO}-102")["gap"] == "fetch_failed:http_404"


def _docx_bytes(text="fictional minutes"):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
                                        "</w:body></w:document>")
    return buf.getvalue()


class TestFormats:
    def test_docx_is_sniffed(self):
        from votes_inventory import sniff_format
        assert sniff_format(_docx_bytes()) == "docx"
        assert sniff_format(b"PK\x03\x04 not a docx") is None
        assert sniff_format(b"%PDF-1.7") == "pdf"

    def test_record_without_a_link_is_its_own_gap(self, world):
        nodes = (world["export"] / "nodes.jsonl").read_text().replace(
            '"preferred_public_url": "//example.invalid/m/102"', '"preferred_public_url": null')
        (world["export"] / "nodes.jsonl").write_text(nodes)
        r = _row(_build(world), f"meeting-{NOVATO}-102")
        assert r["gap"] == "no_minutes_link" and r["minutes_url"] is None


class TestWriteAndVerify:
    def test_write_is_deterministic_and_round_trips(self, world, tmp_path):
        inv = _build(world)
        a, b = tmp_path / "a", tmp_path / "b"
        write_inventory(inv, a)
        write_inventory(_build(world), b)
        assert (a / "inventory.json").read_bytes() == (b / "inventory.json").read_bytes()
        assert (a / "inventory.sha256").read_text().split()[0] == hashlib.sha256(
            (a / "inventory.json").read_bytes()).hexdigest()
        assert load_inventory(a) == json.loads((a / "inventory.json").read_text())

    def test_tampered_inventory_is_refused(self, world, tmp_path):
        write_inventory(_build(world), tmp_path / "a")
        p = tmp_path / "a" / "inventory.json"
        p.write_text(p.read_text().replace("2019", "2018", 1))
        with pytest.raises(InventoryError, match="sha256"):
            load_inventory(tmp_path / "a")

    def test_changed_document_is_refused(self, world):
        inv = _build(world)
        verify_documents(inv, world["tmp"])
        (world["raw"] / NOVATO / "minutes" / f"meeting-{NOVATO}-101.pdf").write_bytes(b"changed")
        with pytest.raises(InventoryError, match="meeting-novato-city-council-101"):
            verify_documents(inv, world["tmp"])


MINUTES_HTML = (b"<html><body><p>MINUTES OF THE FICTIONAL CITY COUNCIL</p><p>Roll Call Present: "
                b"Councilmember Alder; Councilmember Birch</p>" + b"<p>filler text</p>" * 30
                + b"<p>The meeting adjourned at 9:00 p.m.</p></body></html>")
MAINTENANCE_HTML = (b"<html><body><h1>Service temporarily unavailable</h1><p>The requested page cannot be "
                    b"displayed at this time. Our service is undergoing maintenance. Please try again in a "
                    b"few minutes. If the problem persists, contact the website administrator for "
                    b"assistance. Present your ticket number when you call.</p></body></html>")
ERROR_HTML = b"<html><body>Service unavailable</body></html>"
OK = lambda: True  # noqa: E731


class TestFetch:
    def _fetcher(self, responses):
        """responses: url -> list of (status, body[, location]) or exceptions, consumed in order."""
        calls = []

        def fetch(url):
            calls.append(url)
            r = responses[url].pop(0)
            if isinstance(r, Exception):
                raise r
            return r if len(r) == 3 else (r[0], r[1], None)
        return fetch, calls

    def _clock(self):
        """A fake monotonic clock that sleep() advances, so request spacing is observable."""
        t = {"now": 100.0, "stamps": []}

        def sleep(s):
            t["now"] += s

        def stamp():
            t["stamps"].append(t["now"])
        return t, sleep, stamp

    def _log(self, world):
        return [json.loads(x) for x in (world["fetched"] / "fetch-log.jsonl").read_text().splitlines()]

    def test_fetches_only_not_cached_rows(self, world):
        inv = _build(world)
        fetch, calls = self._fetcher({"https://example.invalid/m/102": [(200, MINUTES_HTML)]})
        summary = fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None)
        assert calls == ["https://example.invalid/m/102"]
        assert (world["fetched"] / f"meeting-{NOVATO}-102.html").read_bytes() == MINUTES_HTML
        assert summary == [{"meeting_id": f"meeting-{NOVATO}-102", "status": "ok", "attempts": 1,
                            "url": "https://example.invalid/m/102", "format": "html",
                            "sha256": hashlib.sha256(MINUTES_HTML).hexdigest()}]
        assert [(e["attempt"], e["status"]) for e in self._log(world)] == [(1, "started"), (1, "ok")]

    def test_every_http_request_including_redirect_hops_is_a_second_apart(self, world):
        inv = _build(world)
        row = _row(inv, f"meeting-{NOVATO}-101")
        row.update(documents=[], gap="not_cached")
        t, sleep, stamp = self._clock()
        responses = {
            "https://example.invalid/m/101": [(302, b"", "https://example.invalid/m/101b")],
            "https://example.invalid/m/101b": [(200, MINUTES_HTML)],
            "https://example.invalid/m/102": [(500, b""), (200, MINUTES_HTML)],
        }
        fetch, calls = self._fetcher(responses)

        def timed(url):
            stamp()
            return fetch(url)
        fetch_gaps(inv, world["fetched"], fetch=timed, sleep=sleep, now=lambda: t["now"])
        assert calls == ["https://example.invalid/m/101", "https://example.invalid/m/101b",
                         "https://example.invalid/m/102", "https://example.invalid/m/102"]
        gaps = [b - a for a, b in zip(t["stamps"], t["stamps"][1:])]
        assert gaps and all(g >= 1.0 for g in gaps)

    def test_redirect_hops_are_bounded(self, world):
        inv = _build(world)
        loop = {"https://example.invalid/m/102": [(302, b"", "https://example.invalid/m/102")] * 30}
        fetch, calls = self._fetcher(loop)
        summary = fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None)
        assert summary[0]["status"] == "failed" and summary[0]["error"] == "too_many_redirects"
        assert len(calls) <= 3 * 6

    def test_three_attempts_then_recorded_failure(self, world):
        inv = _build(world)
        fetch, calls = self._fetcher({"https://example.invalid/m/102": [
            OSError("x"), (503, b""), (404, b"")]})
        summary = fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None)
        assert len(calls) == 3
        assert summary[0]["status"] == "failed" and summary[0]["error"] == "http_404"
        assert summary[0]["attempts"] == 3
        assert [e["attempt"] for e in self._log(world) if e["status"] != "started"] == [1, 2, 3]
        assert not list(world["fetched"].glob("meeting-*"))

    def test_attempts_are_cumulative_across_runs(self, world):
        inv = _build(world)
        fetch, calls = self._fetcher({"https://example.invalid/m/102": [(503, b"")] * 6})
        fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None)
        fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None)
        assert len(calls) == 3

    def test_an_interrupted_run_keeps_its_journaled_attempts(self, world):
        inv = _build(world)

        def boom(url):
            raise KeyboardInterrupt
        fetch, calls = self._fetcher({"https://example.invalid/m/102": [(503, b"")] * 3})
        fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None)  # 3 attempts used
        with pytest.raises(KeyboardInterrupt):
            row = _row(inv, f"meeting-{NOVATO}-101")
            row.update(documents=[], gap="not_cached")
            fetch_gaps(inv, world["fetched"], fetch=boom, sleep=lambda s: None)
        assert [e["meeting_id"] for e in self._log(world)].count(f"meeting-{NOVATO}-102") == 6

    def test_an_interrupted_request_still_counts_as_an_attempt(self, world):
        inv = _build(world)

        def boom(url):
            raise KeyboardInterrupt
        for _ in range(3):
            with pytest.raises(KeyboardInterrupt):
                fetch_gaps(inv, world["fetched"], fetch=boom, sleep=lambda s: None)
        fetch, calls = self._fetcher({"https://example.invalid/m/102": [(200, MINUTES_HTML)]})
        assert fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None) == []
        assert calls == []
        assert _row(_build(world), f"meeting-{NOVATO}-102")["gap"] == "fetch_failed:interrupted"

    def test_docx_minutes_are_saved_as_docx(self, world):
        inv = _build(world)
        body = _docx_bytes("MINUTES of the fictional city council. Roll call. " + "words " * 60
                           + "The meeting adjourned.")
        fetch, _ = self._fetcher({"https://example.invalid/m/102": [(200, body)]})
        summary = fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None)
        assert summary[0]["format"] == "docx"
        assert (world["fetched"] / f"meeting-{NOVATO}-102.docx").read_bytes() == body
        assert _row(_build(world), f"meeting-{NOVATO}-102")["documents"][0]["format"] == "docx"

    @pytest.mark.parametrize("body,error", [
        (b"", "empty_body"),
        (ERROR_HTML, "not_minutes"),
        (MAINTENANCE_HTML, "not_minutes"),
        (b"<html><body></body></html>", "not_minutes"),
        (b"plain text", "unknown_format"),
    ])
    def test_a_200_that_is_not_minutes_is_a_failure(self, world, body, error):
        inv = _build(world)
        fetch, _ = self._fetcher({"https://example.invalid/m/102": [(200, body)] * 3})
        summary = fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None)
        assert summary[0]["status"] == "failed" and summary[0]["error"] == error
        assert _row(_build(world), f"meeting-{NOVATO}-102")["gap"] == f"fetch_failed:{error}"

    @pytest.mark.parametrize("bad", [-1, 151])
    def test_document_cap_is_validated(self, world, bad):
        with pytest.raises(ValueError):
            fetch_gaps(_build(world), world["fetched"], fetch=lambda u: (200, b"", None),
                       sleep=lambda s: None, max_docs=bad)

    def test_document_cap_is_cumulative_across_runs(self, world):
        inv = _build(world)
        fetch, calls = self._fetcher({"https://example.invalid/m/102": [(503, b"")] * 3})
        assert fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None, max_docs=1)
        row = _row(inv, f"meeting-{NOVATO}-101")
        row.update(documents=[], gap="not_cached")
        assert fetch_gaps(inv, world["fetched"], fetch=fetch, sleep=lambda s: None, max_docs=1) == []
        assert len(calls) == 3

    def test_document_cap_zero(self, world):
        fetch, calls = self._fetcher({})
        assert fetch_gaps(_build(world), world["fetched"], fetch=fetch, sleep=lambda s: None,
                          max_docs=0) == []
        assert calls == []


class TestMinutesRecords:
    def test_several_minutes_records_for_one_meeting_are_refused(self, world):
        nodes = (world["export"] / "nodes.jsonl").read_text() + json.dumps(
            _record(f"record-{NOVATO}-101-minutes-2", "https://example.invalid/m/101-2")) + "\n"
        (world["export"] / "nodes.jsonl").write_text(nodes)
        with (world["export"] / "edges.jsonl").open("a") as fh:
            fh.write(json.dumps(_edge(f"meeting-{NOVATO}-101", f"record-{NOVATO}-101-minutes-2")) + "\n")
        with pytest.raises(InventoryError, match="several minutes records"):
            _build(world)


class TestCli:
    def test_build_cli_writes_inventory(self, world, tmp_path):
        out = tmp_path / "out"
        rc = main(["build", "--export", str(world["export"]), "--raw", str(world["raw"]),
                   "--fetched", str(world["fetched"]), "--out", str(out),
                   "--window", f"{NOVATO}:2019-01-01:2026-03-10",
                   "--window", f"{BOS}:2019-01-01:2026-03-20"])
        assert rc == 0
        assert load_inventory(out)["bodies"][NOVATO]["meetings"]

    def test_module_never_imports_neo4j(self):
        import subprocess
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import votes_inventory; "
                "print('neo4j' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code,
                              str(Path(__file__).resolve().parents[2] / "scripts")],
                             capture_output=True, text=True, check=True).stdout.strip()
        assert out == "False"
