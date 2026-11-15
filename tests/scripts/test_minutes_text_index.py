"""Minutes text: the operator-local page index built from cached minutes documents (fictional fixtures)."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import minutes_text_index as mti  # noqa: E402

CM, SA, NOV = "corte-madera-town-council", "san-anselmo-town-council", "novato-city-council"


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF, one text line per page ('' = a blank page)."""
    objs: list[bytes] = []
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font = 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode())
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 700 Td ({safe}) Tj ET".encode() if text else b""
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


LONG = " Lorem civic filler about the imaginary Willowbrook Commons gazebo and its benches."


def _substrate(path: Path, meetings: list[tuple[str, str, str, str | None]]) -> Path:
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, search_label TEXT, props TEXT);"
                     "CREATE TABLE edges (source TEXT, rel TEXT, target TEXT, props TEXT);"
                     "CREATE TABLE meta (key TEXT, value TEXT);")
    db.execute("INSERT INTO meta VALUES ('as_of_date', '2030-01-01')")
    for mid, date, title, url in meetings:
        db.execute("INSERT INTO nodes VALUES (?, 'Meeting', '', ?)",
                   (mid, json.dumps({"meeting_date": date, "title": title})))
        if url is not None:
            rid = f"record-{mid}-minutes"
            db.execute("INSERT INTO nodes VALUES (?, 'Record', '', ?)",
                       (rid, json.dumps({"record_type": "meeting_minutes", "preferred_public_url": url})))
            db.execute("INSERT INTO edges VALUES (?, 'EVIDENCED_BY', ?, NULL)", (mid, rid))
    db.commit()
    db.close()
    return path


def _put(raw: Path, source: str, name: str, data: bytes) -> Path:
    p = raw / source / "minutes" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.fixture
def world(tmp_path):
    raw = tmp_path / "raw"
    m = lambda s, n: f"meeting-{s}-{n}"  # noqa: E731
    substrate = _substrate(tmp_path / "substrate.sqlite", [
        (m(CM, 1), "2030-03-03", "The agenda for the March 3, 2030 Regular Town Council Meeting",
         "https://town.example/m1"),
        (m(CM, 2), "2030-03-03", "Agenda for the meeting of the Planning Commission", "https://town.example/m2"),
        (m(CM, 3), "2030-04-01", "Agenda for the meeting of the Planning Commission", "https://town.example/m3"),
        (m(CM, 4), "2030-04-02", "The agenda for the April 2, 2030 Regular Town Council Meeting",
         "//town.example/m4"),
        (m(CM, 5), "2030-05-05", "Agenda for the meeting of the Planning Commission", "https://town.example/m5"),
        (m(CM, 6), "2030-05-06", "Agenda for the meeting of the Planning Commission", "https://town.example/m6"),
        (m(CM, 7), "2030-06-01", "Agenda for the meeting of the Planning Commission", "https://town.example/m7"),
        (m(CM, 8), "2030-06-02", "Agenda for the meeting of the Planning Commission", None),
        (m(NOV, 1), "2030-07-01", "City Council", "https://novato.example/1"),
        (m(NOV, 2), "2030-07-02", "City Council Special Meeting (No Video)", "https://novato.example/2"),
        (m(NOV, 3), "2030-07-03", "State of the City", "https://novato.example/3"),
        (m(SA, 10), "2030-08-08", "Town Council - Special Meeting", "https://sa.example/10"),
        (m(SA, 11), "2030-08-09", "Parks and Recreation Commission", "https://sa.example/11"),
    ])
    # plain documents
    _put(raw, CM, f"{m(CM, 1)}.pdf",
         make_pdf(["Minutes of the Town Council, March 3, 2030." + LONG, "The gazebo paint was approved." + LONG]))
    # one document's bytes under two meetings that print no date in common -> resolved by printed date
    shared = make_pdf(["Planning Commission minutes, April 1, 2030." + LONG])
    _put(raw, CM, f"{m(CM, 3)}.pdf", shared)
    _put(raw, CM, f"{m(CM, 4)}.pdf", shared)
    # one document's bytes under two meetings, printing a date neither has -> quarantined
    orphan = make_pdf(["Planning Commission minutes, December 9, 2031." + LONG])
    _put(raw, CM, f"{m(CM, 5)}.pdf", orphan)
    _put(raw, CM, f"{m(CM, 6)}.pdf", orphan)
    # a scanned image (no text layer) and a corrupt file
    _put(raw, CM, f"{m(CM, 7)}.pdf", make_pdf(["", ""]))
    _put(raw, CM, f"{m(CM, 8)}.pdf", b"%PDF-1.4\nthis is not really a pdf")
    # files that map to no Meeting
    _put(raw, CM, "meeting-corte-madera-town-council-999.pdf", make_pdf(["Orphan minutes." + LONG]))
    _put(raw, CM, "notes.txt", b"scratch")
    # Novato: html, and two versions of one meeting's minutes
    _put(raw, NOV, f"{m(NOV, 1)}.html",
         f"<html><body><h1>Novato City Council</h1><p>July 1, 2030. The kite ordinance passed.{LONG}</p>"
         "</body></html>".encode())
    _put(raw, NOV, f"{m(NOV, 2)}.pdf", make_pdf(["Draft minutes July 2, 2030, first version." + LONG]))
    _put(raw, NOV, f"{m(NOV, 2)}.html",
         f"<html><body><p>Final minutes July 2, 2030, second version.{LONG}</p></body></html>".encode())
    _put(raw, NOV, f"{m(NOV, 3)}.pdf", make_pdf(["State of the City remarks, July 3, 2030." + LONG]))
    (raw / NOV / "minutes-fetch-log.jsonl").write_text(
        json.dumps({"meeting_id": m(NOV, 2), "path": f"{m(NOV, 2)}.pdf", "status": "ok",
                    "fetched_at": "2030-07-03T10:00:00Z"}) + "\n"
        + json.dumps({"meeting_id": m(NOV, 2), "path": f"{m(NOV, 2)}.html", "status": "ok",
                      "fetched_at": "2030-07-09T10:00:00Z"}) + "\n")
    # San Anselmo: copied into the raw store with a manifest
    _put(raw, SA, f"{m(SA, 10)}.pdf", make_pdf(["Town Council special meeting August 8, 2030. "
                                                "Discussion of the Memorial Glade Picnic Lot." + LONG]))
    _put(raw, SA, f"{m(SA, 11)}.pdf", make_pdf(["Parks and Recreation August 9, 2030." + LONG]))
    (raw / SA / "minutes-manifest.json").write_text(json.dumps({"documents": [
        {"meeting_id": m(SA, 10), "file": f"{m(SA, 10)}.pdf", "url": "https://sa.example/10",
         "fetch_date": "2030-08-20"},
        {"meeting_id": m(SA, 11), "file": f"{m(SA, 11)}.pdf", "url": "https://sa.example/11",
         "fetch_date": "2030-08-20"}]}))
    return {"raw": raw, "substrate": substrate, "out": tmp_path / "research" / "minutes-text.sqlite",
            "sources": (CM, NOV, SA)}


def _build(world, out=None):
    return mti.build_index(raw=world["raw"], substrate=world["substrate"], out=out or world["out"],
                           sources=world["sources"])


def _disp(report):
    return {Path(f["path"]).name: (f["disposition"], f["reason"]) for f in report["files"]}


def test_every_file_gets_exactly_one_disposition_and_totals_match_disk(world):
    report = _build(world)
    on_disk = {s: sum(1 for p in (world["raw"] / s / "minutes").rglob("*") if p.is_file())
               for s in world["sources"]}
    assert {s: report["sources"][s]["files"] for s in world["sources"]} == on_disk
    for s in world["sources"]:
        assert sum(report["sources"][s]["dispositions"].values()) == on_disk[s]
    assert len(report["files"]) == len({f["path"] for f in report["files"]}) == sum(on_disk.values())
    assert all(f["disposition"] in mti.DISPOSITIONS for f in report["files"])
    for f in report["files"]:
        if f["disposition"] != "indexed":
            assert f["reason"], f


def test_dispositions_per_rule(world):
    d = _disp(_build(world))
    cm = lambda n: f"meeting-{CM}-{n}.pdf"  # noqa: E731
    assert d[cm(1)][0] == "indexed"
    assert d[cm(3)][0] == d[cm(4)][0] == "shared-indexed"
    assert d[cm(5)][0] == d[cm(6)][0] == "quarantined-ambiguous"
    assert d[cm(7)][0] == "no-text"
    assert d[cm(8)][0] == "unreadable"
    assert d["meeting-corte-madera-town-council-999.pdf"] == ("unmapped", "no Meeting with this id in the substrate")
    assert d["notes.txt"] == ("unmapped", "file name is not a meeting id")
    assert d[f"meeting-{NOV}-2.pdf"][0] == "superseded"
    assert f"meeting-{NOV}-2.html" in d[f"meeting-{NOV}-2.pdf"][1]
    assert d[f"meeting-{NOV}-2.html"][0] == "indexed"


def _rows(out, sql="SELECT meeting_id, body, meeting_date, page, text, official_url, source_sha256 FROM pages "
                   "ORDER BY meeting_id, page"):
    db = sqlite3.connect(out)
    try:
        return db.execute(sql).fetchall()
    finally:
        db.close()


def test_one_row_per_page_with_meeting_body_date_url_and_hash(world):
    _build(world)
    rows = [r for r in _rows(world["out"]) if r[0] == f"meeting-{CM}-1"]
    assert [r[3] for r in rows] == [1, 2]
    assert rows[0][1] == "Corte Madera Town Council" and rows[0][2] == "2030-03-03"
    assert "gazebo paint was approved" in rows[1][4]
    assert rows[0][5] == "https://town.example/m1" and len(rows[0][6]) == 64


def test_a_shared_document_is_indexed_once_under_the_meeting_whose_date_it_prints(world):
    _build(world)
    mids = {r[0] for r in _rows(world["out"]) if "April 1, 2030" in r[4]}
    assert mids == {f"meeting-{CM}-3"}
    assert not [r for r in _rows(world["out"]) if r[0] in (f"meeting-{CM}-5", f"meeting-{CM}-6")]


def test_superseded_version_is_not_indexed_and_unordered_versions_are_quarantined(world):
    _build(world)
    texts = [r[4] for r in _rows(world["out"]) if r[0] == f"meeting-{NOV}-2"]
    assert any("second version" in t for t in texts) and not any("first version" in t for t in texts)
    # without saved dates the two versions cannot be ordered: neither is guessed
    (world["raw"] / NOV / "minutes-fetch-log.jsonl").unlink()
    d = _disp(_build(world))
    assert d[f"meeting-{NOV}-2.pdf"][0] == d[f"meeting-{NOV}-2.html"][0] == "quarantined-ambiguous"


def test_body_comes_from_the_meeting_title_and_unknown_titles_are_reported(world):
    report = _build(world)
    bodies = dict(_rows(world["out"], "SELECT DISTINCT meeting_id, body FROM pages"))
    assert bodies[f"meeting-{SA}-10"] == "San Anselmo Town Council"
    assert bodies[f"meeting-{SA}-11"] == "San Anselmo Parks and Recreation Commission"
    assert bodies[f"meeting-{NOV}-2"] == "Novato City Council"
    assert bodies[f"meeting-{NOV}-3"] == "State of the City"
    assert {(u["source"], u["title"]) for u in report["unknown_titles"]} == {(NOV, "State of the City")}


def test_protocol_relative_urls_are_normalized_and_san_anselmo_urls_come_through(world):
    _build(world)
    urls = dict(_rows(world["out"], "SELECT DISTINCT meeting_id, official_url FROM pages"))
    assert urls[f"meeting-{CM}-3"] == "https://town.example/m3"
    assert urls[f"meeting-{SA}-10"] == "https://sa.example/10"


def test_full_text_search_finds_the_page(world):
    _build(world)
    hits = mti.search(world["out"], "Memorial Glade Picnic Lot")
    assert [(h["meeting_id"], h["page"]) for h in hits] == [(f"meeting-{SA}-10", 1)]
    assert "Picnic" in hits[0]["snippet"]


def test_build_twice_gives_an_identical_row_set_and_file(world, tmp_path):
    _build(world)
    first = _rows(world["out"], "SELECT * FROM pages ORDER BY id")
    first_cov = _rows(world["out"], "SELECT * FROM coverage ORDER BY meeting_id")
    first_bytes = world["out"].read_bytes()
    _build(world)  # in place, over the existing index
    assert _rows(world["out"], "SELECT * FROM pages ORDER BY id") == first
    assert _rows(world["out"], "SELECT * FROM coverage ORDER BY meeting_id") == first_cov
    other = tmp_path / "elsewhere" / "again.sqlite"
    _build(world, out=other)
    assert other.read_bytes() == first_bytes


def test_coverage_states_every_meeting_with_a_minutes_link(world):
    _build(world)
    cov = {r[0]: r[1] for r in _rows(world["out"], "SELECT meeting_id, state FROM coverage")}
    m = lambda s, n: f"meeting-{s}-{n}"  # noqa: E731
    assert cov[m(CM, 1)] == "indexed"
    assert cov[m(CM, 3)] == "indexed"
    assert cov[m(CM, 4)] == "not cached"  # its file was another meeting's minutes
    assert cov[m(CM, 5)] == cov[m(CM, 6)] == "quarantined"
    assert cov[m(CM, 7)] == "no-text"
    assert cov[m(CM, 2)] == "not cached"
    assert m(CM, 8) not in cov  # no minutes link
    assert set(cov.values()) <= set(mti.COVERAGE_STATES)


def test_report_lists_non_indexed_files_and_flags_sources_below_ninety_percent(world):
    report = _build(world)
    assert report["sources"][SA]["indexed_share"] == 1.0
    assert CM in report["shortfall"] and SA not in report["shortfall"]
    md = mti.render_report(report)
    assert md.index("Shortfall") < md.index("Dispositions")
    assert "notes.txt" in md and "file name is not a meeting id" in md


def test_the_index_is_written_outside_the_raw_tree_and_never_opens_neo4j(world):
    assert "neo4j" not in Path(mti.__file__).read_text().lower().replace("never touches neo4j", "")
    _build(world)
    assert world["out"].is_file()
    assert not any(p.suffix == ".sqlite" for p in world["raw"].rglob("*"))


# --- San Anselmo: staged documents enter the raw store --------------------------------------------------------

def _staging(tmp_path):
    st = tmp_path / "staging"
    (st / "cache").mkdir(parents=True)
    (st / "cache" / "2030-08-08_meeting-san-anselmo-town-council-10.pdf").write_bytes(make_pdf(["A" + LONG]))
    (st / "cache" / "2030-08-09_meeting-san-anselmo-town-council-11.html").write_bytes(b"<html>B</html>")
    (st / "index.json").write_text(json.dumps([
        {"meeting": f"meeting-{SA}-10", "date": "2030-08-08", "body": "Town Council", "url": "https://sa.example/10",
         "file": "2030-08-08_meeting-san-anselmo-town-council-10.pdf"},
        {"meeting": f"meeting-{SA}-11", "date": "2030-08-09", "body": "Parks", "url": "https://sa.example/11",
         "file": "2030-08-09_meeting-san-anselmo-town-council-11.html"}]))
    return st


def test_import_san_anselmo_copies_files_by_meeting_id_with_a_manifest(tmp_path):
    st, raw = _staging(tmp_path), tmp_path / "raw"
    manifest = mti.import_san_anselmo(st, raw)
    dest = raw / SA / "minutes"
    assert sorted(p.name for p in dest.iterdir()) == [f"meeting-{SA}-10.pdf", f"meeting-{SA}-11.html"]
    doc = manifest["documents"][0]
    assert doc["meeting_id"] == f"meeting-{SA}-10" and doc["url"] == "https://sa.example/10"
    assert len(doc["sha256"]) == 64 and len(doc["fetch_date"]) == 10
    assert json.loads((raw / SA / "minutes-manifest.json").read_text()) == manifest
    # idempotent
    assert mti.import_san_anselmo(st, raw) == manifest


def test_import_san_anselmo_refuses_to_overwrite_different_bytes(tmp_path):
    st, raw = _staging(tmp_path), tmp_path / "raw"
    mti.import_san_anselmo(st, raw)
    (raw / SA / "minutes" / f"meeting-{SA}-10.pdf").write_bytes(b"%PDF-other")
    with pytest.raises(mti.IndexBuildError, match="differs"):
        mti.import_san_anselmo(st, raw)


def test_a_legacy_word_doc_under_an_html_name_is_unreadable_with_that_reason(world):
    _put(world["raw"], NOV, f"meeting-{NOV}-3.pdf", bytes.fromhex("d0cf11e0a1b11ae1") + b"\0" * 64)
    d = _disp(_build(world))
    assert d[f"meeting-{NOV}-3.pdf"] == ("unreadable", "a legacy Word .doc (OLE2) under this name; no .doc reader")


def test_a_manifest_hash_that_does_not_match_the_file_is_unmapped(world):
    mpath = world["raw"] / SA / "minutes-manifest.json"
    manifest = json.loads(mpath.read_text())
    manifest["documents"][0]["sha256"] = "0" * 64
    mpath.write_text(json.dumps(manifest))
    d = _disp(_build(world))
    assert d[f"meeting-{SA}-10.pdf"] == ("unmapped", f"bytes differ from {SA}/minutes-manifest.json")


def test_fts_query_neutralises_search_syntax():
    assert mti.fts_query('Memorial Park "parking lot"') == '"Memorial" AND "Park" AND "parking lot"'
    assert mti.fts_query("NEAR( a* OR b") == '"NEAR" AND "a" AND "OR" AND "b"'
    assert mti.fts_query("  ") is None
