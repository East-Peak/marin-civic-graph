#!/usr/bin/env python3
"""Minutes coverage: text sidecars bound to their original document.

A sidecar is the text of a document that has none of its own: OCR of a scanned PDF (`ocr`, one entry per original
page, blank pages kept as empty entries so page numbers match the PDF) or a legacy Word .doc converted by macOS
textutil (`converted`, one page). It lives beside, never inside, the minutes directory:

    <raw>/<source>/minutes-ocr/<meeting_id>.json        <raw>/<source>/minutes-converted/<meeting_id>.json

and records the original's raw-relative path and sha256, the text's own sha256, the tool versions and the
settings. The original is never modified. The index uses a sidecar only after `check` passes against the file it
is about to index; any mismatch is reported and the sidecar ignored.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA = "minutes-sidecar-v1"
TEXT_SOURCES = {"ocr": "minutes-ocr", "converted": "minutes-converted"}
MIN_CHARS = 200  # fewer non-whitespace characters than this over the whole document: it stays no-text


def text_sha256(pages: list[str]) -> str:
    return hashlib.sha256(json.dumps(pages, ensure_ascii=False).encode("utf-8")).hexdigest()


def non_whitespace(pages: list[str]) -> int:
    return sum(len(re.sub(r"\s", "", p)) for p in pages)


def sidecar_path(raw: Path, source_dir: str, meeting_id: str, text_source: str) -> Path:
    return Path(raw) / source_dir / TEXT_SOURCES[text_source] / f"{meeting_id}.json"


def make_sidecar(original_rel: str, original_sha256: str, pages: list[str], text_source: str, *, tools: dict,
                 settings: dict) -> dict:
    if text_source not in TEXT_SOURCES:
        raise ValueError(f"unknown text source {text_source}")
    return {"schema": SCHEMA, "text_source": text_source,
            "original": {"path": original_rel, "sha256": original_sha256},
            "pages": [{"page": n, "text": t} for n, t in enumerate(pages, start=1)],
            "text_sha256": text_sha256(pages), "non_whitespace_chars": non_whitespace(pages),
            "tools": tools, "settings": settings}


def read_sidecar(path: Path) -> dict | None:
    """The sidecar's JSON, or None when there is none; raises on an unreadable or undecodable one."""
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else None


def check(doc: dict, original_rel: str, original_sha256: str, text_source: str,
          page_count: int | None = None) -> tuple[list[str] | None, str | None]:
    """(the page texts, None) when the sidecar is this document's, else (None, the problem)."""
    try:
        if doc.get("schema") != SCHEMA or doc.get("text_source") != text_source:
            return None, f"not a {text_source} sidecar of schema {SCHEMA}"
        if doc["original"]["path"] != original_rel:
            return None, f"bound to another path ({doc['original']['path']})"
        if doc["original"]["sha256"] != original_sha256:
            return None, (f"the original's sha256 is now {original_sha256[:12]}…, the sidecar was made from "
                          f"{doc['original']['sha256'][:12]}…")
        entries = doc["pages"]
        if [e["page"] for e in entries] != list(range(1, len(entries) + 1)):
            return None, "page entries are not 1..n in order"
        pages = [e["text"] for e in entries]
        if text_sha256(pages) != doc["text_sha256"]:
            return None, "its text does not match its own text sha256"
        if text_source == "ocr" and not (isinstance(page_count, int) and page_count > 0):
            return None, "the original's page count could not be read, so the OCR pages cannot be verified"
        if page_count is not None and len(pages) != page_count:
            return None, f"{len(pages)} pages in the sidecar, {page_count} in the original"
        if text_source == "converted" and len(pages) != 1:
            return None, "a converted document is one page"
        if text_source == "ocr" and (n := non_whitespace(pages)) < MIN_CHARS:
            return None, f"{n} non-whitespace characters, under the {MIN_CHARS}-character threshold"
        return pages, None
    except (KeyError, TypeError) as exc:
        return None, f"malformed sidecar ({type(exc).__name__}: {exc})"
