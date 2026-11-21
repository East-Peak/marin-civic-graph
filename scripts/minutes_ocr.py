#!/usr/bin/env python3
"""Minutes coverage: text sidecars for the minutes the index cannot read (minutes_sidecars has the contract).

    python scripts/minutes_ocr.py ocr        # every `no-text` PDF in the index → <raw>/<source>/minutes-ocr/
    python scripts/minutes_ocr.py convert    # every legacy Word .doc (`unreadable`) → <raw>/<source>/minutes-converted/

Targets come from the built index's dispositions, never from a guess. Each original's sha256 is checked against
the index before the tool runs and again after; the tool reads a private copy in a temporary directory, so the
original is never opened for writing. OCR is `ocrmypdf --force-ocr` (tesseract) into a throwaway PDF whose text
pdftotext reads page by page; the page count must equal the original's. A result under minutes_sidecars.MIN_CHARS
non-whitespace characters writes no sidecar: the document stays `no-text`. A report of every target's outcome
goes to the staging folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from minutes_sidecars import MIN_CHARS, check, make_sidecar, non_whitespace, read_sidecar, sidecar_path  # noqa: E402
from minutes_sources import SOURCE_MAP  # noqa: E402

HOME = Path.home()
DEFAULT_RAW = HOME / "projects/marin-civic-graph/data/raw"
DEFAULT_INDEX = HOME / "open-marin-research/minutes-text.sqlite"
STAGING = HOME / "open-marin-staging/minutes-coverage"

OCR_ARGS = ["--force-ocr", "-l", "eng", "--output-type", "pdf", "--optimize", "0", "--jobs", "2", "--quiet"]
OCR_SETTINGS = {"ocrmypdf": OCR_ARGS, "pdftotext": ["-enc", "UTF-8"], "threshold_non_whitespace": MIN_CHARS}
CONVERT_SETTINGS = {"textutil": ["-format", "doc", "-convert", "txt", "-stdout"]}
LEGACY_DOC = "a legacy Word .doc (OLE2)"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def targets(index: Path, kind: str) -> list[dict]:
    db = sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)
    try:
        if kind == "ocr":
            rows = db.execute("SELECT path, source, meeting_id, sha256 FROM dispositions WHERE disposition = 'no-text' "
                              "AND lower(path) LIKE '%.pdf' ORDER BY path").fetchall()
        elif kind == "convert":
            rows = db.execute("SELECT path, source, meeting_id, sha256 FROM dispositions WHERE disposition = "
                              "'unreadable' AND reason LIKE ? ORDER BY path", (f"{LEGACY_DOC}%",)).fetchall()
        else:
            raise ValueError(kind)
    finally:
        db.close()
    return [{"path": p, "source": s, "meeting_id": m, "sha256": h} for p, s, m, h in rows]


def _version(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=60)
    except FileNotFoundError:
        return ""
    return (out.stdout or out.stderr).decode("utf-8", "replace").strip().splitlines()[0] if (out.stdout or out.stderr) \
        else ""


def ocr_tools() -> dict:
    return {"ocrmypdf": _version(["ocrmypdf", "--version"]), "tesseract": _version(["tesseract", "--version"]),
            "pdftotext": _version(["pdftotext", "-v"])}


def pdf_pages(path: Path) -> int | None:
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=60)
    m = re.search(rb"^Pages:\s+(\d+)", out.stdout, re.M) if out.returncode == 0 else None
    return int(m.group(1)) if m else None


def ocrmypdf_pages(path: Path) -> list[str]:
    """OCR text of every page of `path`, in order (blank pages as ''), from a private copy."""
    with tempfile.TemporaryDirectory(prefix="minutes-ocr-") as tmp:
        src, out = Path(tmp) / "in.pdf", Path(tmp) / "out.pdf"
        shutil.copyfile(path, src)
        done = subprocess.run(["ocrmypdf", *OCR_ARGS, str(src), str(out)], capture_output=True, timeout=1800)
        if done.returncode != 0:
            raise RuntimeError(f"ocrmypdf exit {done.returncode}: {done.stderr.decode('utf-8', 'replace')[-300:]}")
        text = subprocess.run(["pdftotext", "-enc", "UTF-8", str(out), "-"], capture_output=True, timeout=300)
        if text.returncode != 0:
            raise RuntimeError(f"pdftotext exit {text.returncode}")
        pages = text.stdout.decode("utf-8", "replace").split("\f")
        n = pdf_pages(out)
        return [p.strip("\n") for p in pages[:n]] if n is not None else pages


def textutil_text(path: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="minutes-convert-") as tmp:
        src = Path(tmp) / "in.doc"
        shutil.copyfile(path, src)
        done = subprocess.run(["textutil", "-format", "doc", "-convert", "txt", "-stdout", str(src)],
                              capture_output=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError(f"textutil exit {done.returncode}: {done.stderr.decode('utf-8', 'replace')[-300:]}")
    return done.stdout.decode("utf-8", "replace")


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _one(raw: Path, t: dict, kind: str, runner, tools: dict) -> dict:
    original = Path(raw) / t["path"]
    source_dir = SOURCE_MAP[t["source"]].raw_dir
    text_source = "ocr" if kind == "ocr" else "converted"
    out = sidecar_path(raw, source_dir, t["meeting_id"], text_source)
    res = {"path": t["path"], "meeting_id": t["meeting_id"], "sha256_before": None, "sha256_after": None,
           "sidecar": out.relative_to(raw).as_posix()}
    before = _sha(original)
    res["sha256_before"] = before
    if before != t["sha256"]:
        return res | {"state": "hash-mismatch", "reason": "the original changed since the index was built"}
    n_pages = pdf_pages(original) if kind == "ocr" else 1
    existing = read_sidecar(out)
    if existing is not None and check(existing, t["path"], before, text_source, n_pages)[1] is None:
        return res | {"state": "exists", "sha256_after": before, "pages": len(existing["pages"]),
                      "chars": existing["non_whitespace_chars"]}
    try:
        pages = runner(original) if kind == "ocr" else [runner(original).strip()]
    except Exception as exc:
        return res | {"state": "failed", "reason": f"{type(exc).__name__}: {exc}", "sha256_after": _sha(original)}
    after = _sha(original)
    res |= {"sha256_after": after, "pages": len(pages), "chars": non_whitespace(pages)}
    if after != before:
        return res | {"state": "failed", "reason": "the original changed while the tool ran"}
    if kind == "ocr" and len(pages) != n_pages:
        return res | {"state": "failed", "reason": f"{len(pages)} pages of text for {n_pages} pages in the PDF"}
    if kind == "ocr" and res["chars"] < MIN_CHARS:
        return res | {"state": "below-threshold", "reason": f"{res['chars']} non-whitespace characters"}
    doc = make_sidecar(t["path"], before, pages, text_source, tools=tools,
                       settings=OCR_SETTINGS if kind == "ocr" else CONVERT_SETTINGS)
    _write(out, doc)
    return res | {"state": "written"}


def run_ocr(raw: Path, todo: list[dict], *, runner=ocrmypdf_pages, tools: dict | None = None,
            workers: int = 1) -> list[dict]:
    tools = ocr_tools() if tools is None else tools
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda t: _one(raw, t, "ocr", runner, tools), todo))


def run_convert(raw: Path, todo: list[dict], *, runner=textutil_text, tools: dict | None = None) -> list[dict]:
    if tools is None:
        tools = {"textutil": "macOS " + _version(["sw_vers", "-productVersion"])}
    return [_one(raw, t, "convert", runner, tools) for t in todo]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("kind", choices=("ocr", "convert"))
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    ap.add_argument("--report-dir", type=Path, default=STAGING)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args(argv)
    todo = targets(args.index, args.kind)
    results = (run_ocr(args.raw, todo, workers=args.workers) if args.kind == "ocr"
               else run_convert(args.raw, todo))
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report = args.report_dir / f"{args.kind}-report.json"
    report.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    counts: dict[str, int] = {}
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    print(f"{len(results)} targets: {counts}; report {report}")
    return 0 if not counts.get("failed") and not counts.get("hash-mismatch") else 1


if __name__ == "__main__":
    sys.exit(main())
