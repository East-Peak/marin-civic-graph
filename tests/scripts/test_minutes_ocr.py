"""Minutes coverage: OCR and .doc-conversion sidecars, bound to their original and never modifying it
(fake runners for the rules; one real ocrmypdf run on an invented scan when the tool is installed)."""
import hashlib
import io
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import minutes_ocr as mo  # noqa: E402
import minutes_sidecars as msc  # noqa: E402
from test_minutes_text_index import make_pdf  # noqa: E402

SZ = "sausalito-city-council"
SA = "san-anselmo-town-council"
PAGE1 = "MINUTES OF THE CITY COUNCIL OF THE IMAGINARY TOWN OF WILLOWMERE, MARCH 3, 2030. " * 3
PAGE3 = "The council approved the invented Larkfield footbridge contract on a five to nothing vote. " * 3


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put(raw, source, name, data, sub="minutes"):
    p = raw / source / sub / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def index_with(path, rows):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE dispositions (path TEXT PRIMARY KEY, source TEXT NOT NULL, meeting_id TEXT, "
               "sha256 TEXT, disposition TEXT NOT NULL, reason TEXT, text_source TEXT)")
    db.executemany("INSERT INTO dispositions VALUES (?, ?, ?, ?, ?, ?, NULL)", rows)
    db.commit()
    db.close()
    return path


@pytest.fixture
def scan(tmp_path):
    raw = tmp_path / "raw"
    mid = f"meeting-{SZ}-77"
    data = make_pdf(["", "", ""])
    original = put(raw, SZ, f"{mid}.pdf", data)
    idx = index_with(tmp_path / "idx.sqlite", [
        (f"{SZ}/minutes/{mid}.pdf", SZ, mid, sha(data), "no-text", "no text layer (0 characters)"),
        (f"{SZ}/minutes/meeting-{SZ}-78.pdf", SZ, f"meeting-{SZ}-78", "0" * 64, "indexed", None)])
    return raw, idx, mid, original


def fake(pages):
    calls = []

    def runner(path):
        calls.append(path)
        return list(pages)
    runner.calls = calls
    return runner


def test_targets_are_the_index_no_text_pdfs_and_legacy_docs(tmp_path, scan):
    raw, idx, mid, _ = scan
    assert [t["meeting_id"] for t in mo.targets(idx, "ocr")] == [mid]
    doc_idx = index_with(tmp_path / "d.sqlite", [
        (f"{SA}/minutes/meeting-{SA}-9.html", SA, f"meeting-{SA}-9", "a" * 64, "unreadable",
         "a legacy Word .doc (OLE2) under this name; no .doc reader"),
        (f"{SA}/minutes/meeting-{SA}-10.pdf", SA, f"meeting-{SA}-10", "b" * 64, "unreadable", "could not be read")])
    assert [t["meeting_id"] for t in mo.targets(doc_idx, "convert")] == [f"meeting-{SA}-9"]


def test_a_multipage_scan_with_a_blank_page_gets_one_entry_per_page(scan):
    raw, idx, mid, original = scan
    before = original.read_bytes()
    runner = fake([PAGE1, "", PAGE3])
    [res] = mo.run_ocr(raw, mo.targets(idx, "ocr"), runner=runner, tools={"ocrmypdf": "fixture"})
    assert res["state"] == "written" and res["pages"] == 3
    doc = json.loads(msc.sidecar_path(raw, SZ, mid, "ocr").read_text())
    assert [(e["page"], e["text"]) for e in doc["pages"]] == [(1, PAGE1), (2, ""), (3, PAGE3)]
    assert doc["original"] == {"path": f"{SZ}/minutes/{mid}.pdf", "sha256": sha(before)}
    assert doc["tools"] == {"ocrmypdf": "fixture"} and doc["settings"] == mo.OCR_SETTINGS
    assert msc.check(doc, f"{SZ}/minutes/{mid}.pdf", sha(before), "ocr", 3)[1] is None
    assert original.read_bytes() == before
    assert not any(p.suffix == ".pdf" for p in (raw / SZ / "minutes-ocr").iterdir())


def test_a_below_threshold_result_writes_no_sidecar_and_stays_no_text(scan):
    raw, idx, mid, _ = scan
    [res] = mo.run_ocr(raw, mo.targets(idx, "ocr"), runner=fake(["Page 1 of 3", "", "  "]), tools={})
    assert res["state"] == "below-threshold" and res["chars"] < msc.MIN_CHARS
    assert not msc.sidecar_path(raw, SZ, mid, "ocr").exists()


def test_a_page_count_that_differs_from_the_pdf_is_a_failure(scan):
    raw, idx, mid, _ = scan
    [res] = mo.run_ocr(raw, mo.targets(idx, "ocr"), runner=fake([PAGE1, PAGE3]), tools={})
    assert res["state"] == "failed" and "pages" in res["reason"]
    assert not msc.sidecar_path(raw, SZ, mid, "ocr").exists()


def test_an_original_that_changed_since_the_index_is_not_ocrd(scan):
    raw, idx, mid, original = scan
    original.write_bytes(make_pdf(["", ""]))
    runner = fake([PAGE1, "", PAGE3])
    [res] = mo.run_ocr(raw, mo.targets(idx, "ocr"), runner=runner, tools={})
    assert res["state"] == "hash-mismatch" and runner.calls == []


def test_a_valid_existing_sidecar_is_kept_and_not_redone(scan):
    raw, idx, mid, _ = scan
    mo.run_ocr(raw, mo.targets(idx, "ocr"), runner=fake([PAGE1, "", PAGE3]), tools={})
    again = fake([PAGE1, "", PAGE3])
    [res] = mo.run_ocr(raw, mo.targets(idx, "ocr"), runner=again, tools={})
    assert res["state"] == "exists" and again.calls == []


def test_a_legacy_doc_is_converted_into_a_one_page_sidecar(tmp_path):
    raw = tmp_path / "raw"
    mid = f"meeting-{SA}-9"
    data = bytes.fromhex("d0cf11e0a1b11ae1") + b"\0" * 64
    original = put(raw, SA, f"{mid}.html", data)
    idx = index_with(tmp_path / "d.sqlite", [(f"{SA}/minutes/{mid}.html", SA, mid, sha(data), "unreadable",
                                              "a legacy Word .doc (OLE2) under this name; no .doc reader")])
    [res] = mo.run_convert(raw, mo.targets(idx, "convert"), runner=lambda p: "Town Council minutes text.\n" + PAGE3,
                           tools={"textutil": "fixture"})
    assert res["state"] == "written"
    doc = json.loads(msc.sidecar_path(raw, SA, mid, "converted").read_text())
    assert doc["text_source"] == "converted" and len(doc["pages"]) == 1
    assert doc["settings"] == mo.CONVERT_SETTINGS and original.read_bytes() == data


def test_the_textutil_runner_names_the_doc_format_explicitly(monkeypatch, tmp_path):
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, b"converted text", b""

    def fake_run(args, **kw):
        seen["args"] = args
        return Done()

    monkeypatch.setattr(mo.subprocess, "run", fake_run)
    (tmp_path / "x.html").write_bytes(bytes.fromhex("d0cf11e0a1b11ae1"))
    assert mo.textutil_text(tmp_path / "x.html") == "converted text"
    assert seen["args"][:5] == ["textutil", "-format", "doc", "-convert", "txt"]


@pytest.mark.skipif(not (shutil.which("ocrmypdf") and shutil.which("tesseract")), reason="ocrmypdf not installed")
def test_real_ocr_keeps_page_positions_of_an_invented_scan(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=44)
    imgs = []
    for text in ("WILLOWMERE COUNCIL MINUTES", None, "LARKFIELD FOOTBRIDGE APPROVED"):
        img = Image.new("L", (1700, 2200), 255)
        if text:
            d = ImageDraw.Draw(img)
            for row in range(8):
                d.text((120, 200 + row * 120), f"{text} {row + 1}", fill=0, font=font)
        imgs.append(img.convert("RGB"))
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", resolution=200, save_all=True, append_images=imgs[1:])
    raw = tmp_path / "raw"
    mid = f"meeting-{SZ}-90"
    original = put(raw, SZ, f"{mid}.pdf", buf.getvalue())
    idx = index_with(tmp_path / "i.sqlite", [(f"{SZ}/minutes/{mid}.pdf", SZ, mid, sha(buf.getvalue()), "no-text",
                                             "no text layer")])
    [res] = mo.run_ocr(raw, mo.targets(idx, "ocr"))
    assert res["state"] == "written", res
    doc = json.loads(msc.sidecar_path(raw, SZ, mid, "ocr").read_text())
    texts = [e["text"] for e in doc["pages"]]
    assert len(texts) == 3 and "WILLOWMERE" in texts[0] and texts[1].strip() == "" and "LARKFIELD" in texts[2]
    assert original.read_bytes() == buf.getvalue()
    assert doc["tools"]["ocrmypdf"] and doc["tools"]["tesseract"]
