"""Tests for scripts/extract_form700_interiors.py (M4).

The interiors pipeline turns staged Form 700 schedule PDFs into EconomicInterest
nodes + the disclosure edge spine. This file grows unit-by-unit:
  Unit 3 — reader: metadata validation, sha256 verify, pdftotext extraction,
           extraction-status accounting (no_text_layer / filer reconciliation).
Fixtures are consumed byte-verbatim, never fetched/modified. Local-only PDFs
(Schedule-B-bearing) skipif when absent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from extract_form700_interiors import (  # noqa: E402
    REQUIRED_METADATA_KEYS,
    classify_text_status,
    extract_pdf_text,
    filer_matches,
    iter_image_dirs,
    load_metadata,
    read_interior,
    verify_pdf_sha256,
)

INTERIORS_DIR = REPO_ROOT / "tests" / "fixtures" / "form700" / "interiors"
# Committable (non-local-only) fixtures — always present.
JONES = INTERIORS_DIR / "216307037"   # A-1, A-2, C
FUSENIG = INTERIORS_DIR / "216034157"  # E (amendment)
ALDEN = INTERIORS_DIR / "216872504"   # cover-only


def _write_min_metadata(d: Path, **overrides) -> Path:
    base = json.loads((JONES / "metadata.json").read_text())
    base.update(overrides)
    d.mkdir(parents=True, exist_ok=True)
    (d / "metadata.json").write_text(json.dumps(base))
    return d


class TestMetadataValidation:
    def test_load_real_metadata(self):
        md = load_metadata(JONES)
        assert md["image_id"] == "216307037"
        assert md["filer_name"] == "Jones, Sarah"
        assert md["schedules"] == ["A-1", "A-2", "C"]

    def test_missing_key_fails_loud_naming_keys_only(self, tmp_path):
        d = _write_min_metadata(tmp_path / "999")
        md = json.loads((d / "metadata.json").read_text())
        del md["filer_name"]
        del md["filing_guid"]
        (d / "metadata.json").write_text(json.dumps(md))
        with pytest.raises(ValueError) as exc:
            load_metadata(d)
        msg = str(exc.value)
        # Names the missing KEYS, never the (absent) values.
        assert "filer_name" in msg and "filing_guid" in msg

    def test_required_keys_are_the_reader_contract(self):
        assert {"filer_name", "filed_at", "statement_type", "job_title",
                "department", "agency_id", "agency_label", "image_id",
                "filing_guid", "schedules", "source_url",
                "pdf_sha256"} <= REQUIRED_METADATA_KEYS


class TestSha256Preflight:
    def test_real_pdf_sha256_matches(self):
        md = load_metadata(JONES)
        verify_pdf_sha256(JONES, md)  # no raise

    def test_sha256_mismatch_blocks(self, tmp_path):
        d = _write_min_metadata(tmp_path / "888", pdf_sha256="deadbeef")
        (d / "document.pdf").write_bytes(b"%PDF-1.4 not the real bytes")
        with pytest.raises(ValueError, match="sha256"):
            verify_pdf_sha256(d, load_metadata(d))


class TestTextExtraction:
    def test_pdftotext_on_real_committable_pdf(self):
        text = extract_pdf_text(FUSENIG / "document.pdf")
        assert text.strip()
        # Schedule E is the only schedule on this filing.
        assert "SCHEDULE E" in text.upper()

    def test_classify_text_status(self):
        assert classify_text_status("   \n\t ") == "no_text_layer"
        assert classify_text_status("real content") == "parsed"


class TestFilerReconciliation:
    def test_inverted_metadata_name_matches_cover_name(self):
        # metadata stores "Last, First"; the cover prints "First Last".
        assert filer_matches("Jones, Sarah", "Sarah Jones") is True

    def test_case_insensitive_match(self):
        assert filer_matches("Jones, Sarah", "SARAH JONES") is True

    def test_different_person_does_not_match(self):
        assert filer_matches("Jones, Sarah", "Todd Werby") is False


class TestReadInterior:
    def test_reads_committable_filing_parsed(self):
        reading = read_interior(JONES)
        assert reading["extraction_status"] == "parsed"
        assert reading["text"].strip()
        assert reading["filing_id"].startswith("filing-form700-cmar-")
        # byte-identical to the index path: build_filing_node from metadata.
        assert "jones-sarah" in reading["filing_id"]
        assert reading["filing_node"]["node_type"] == "Filing"

    def test_no_text_layer_via_injected_extractor(self):
        reading = read_interior(JONES, text_extractor=lambda _p: "   ")
        assert reading["extraction_status"] == "no_text_layer"
        assert reading["text"] == ""

    def test_cover_only_filing_is_parsed_not_error(self):
        reading = read_interior(ALDEN)
        # cover-only still has a text layer (the cover sheet) → parsed.
        assert reading["extraction_status"] == "parsed"
        assert reading["metadata"]["schedules"] == []


class TestImageDirIteration:
    def test_iter_image_dirs_sorted(self):
        dirs = iter_image_dirs(INTERIORS_DIR)
        names = [d.name for d in dirs]
        # committable image-ids must all appear, sorted.
        assert names == sorted(names)
        assert "216307037" in names and "216872504" in names
