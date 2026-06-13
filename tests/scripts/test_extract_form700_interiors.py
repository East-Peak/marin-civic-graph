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


# ---------------------------------------------------------------------------
# Unit 5 — assembly + reconciliation
# ---------------------------------------------------------------------------
from extract_form700_interiors import (  # noqa: E402
    SCHEDULE_ORDER,
    extract_filing,
    parse_all_schedules,
)
from ingest_form700 import build_filing_node, normalize_name  # noqa: E402

WERBY_DIR = INTERIORS_DIR / "216262973"
werby_present = pytest.mark.skipif(
    not (WERBY_DIR / "document.pdf").is_file(), reason="local-only PDF absent"
)


class TestParseAllSchedules:
    def test_jones_schedule_counts(self):
        by_sched, unparsed, skipped_none = parse_all_schedules(JONES / "document.pdf")
        assert len(by_sched["A-1"]) == 2
        assert len(by_sched["A-2"]) == 3
        assert len(by_sched["C"]) == 1
        assert skipped_none == 1  # the literal-None part-3
        assert unparsed == []


class TestExtractFiling:
    def test_jones_six_economic_interest_nodes_with_spine(self):
        result = extract_filing(JONES)
        env = result["envelope"]
        assert env["extraction_status"] == "parsed"
        ei = [n for n in result["nodes"] if n["node_type"] == "EconomicInterest"]
        assert len(ei) == 6  # A-1:2 + A-2:3 + C:1
        # Filing id is byte-identical to the NetFile-index path.
        md = env  # filing_id stored on envelope
        expected_fid = build_filing_node(
            {"filer_name": "Jones, Sarah", "filed_at": "2026-03-24",
             "statement_type": "Annual", "job_title": "Director of Community Development",
             "department": "Community Development Agency"},
            agency_id="cmar", agency_label="Marin County",
        )["id"]
        assert env["filing_id"] == expected_fid
        # Edge spine: every EI has exactly one inbound DISCLOSED_AS (Filing→EI)
        # and ≥1 EVIDENCED_BY (EI→Record).
        for node in ei:
            disclosed = [e for e in result["edges"]
                         if e["relationship_type"] == "DISCLOSED_AS" and e["target_id"] == node["id"]]
            assert len(disclosed) == 1
            assert disclosed[0]["source_id"] == env["filing_id"]
            ev = [e for e in result["edges"]
                  if e["relationship_type"] == "EVIDENCED_BY" and e["source_id"] == node["id"]]
            assert len(ev) >= 1
            assert ev[0]["target_id"] == "record-form700-interior-216307037"
        # Exactly one FILED_BY (Filing→Person).
        filed = [e for e in result["edges"] if e["relationship_type"] == "FILED_BY"]
        assert len(filed) == 1
        assert filed[0]["source_id"] == env["filing_id"]
        # Record + Person + Filing nodes present.
        assert any(n["node_type"] == "Record" for n in result["nodes"])
        assert any(n["node_type"] == "Person" for n in result["nodes"])
        assert any(n["node_type"] == "Filing" for n in result["nodes"])
        # No validationchecks — cover §4 reconciles with parsed schedules.
        assert env["validation_checks"] == []

    def test_line_ordinals_are_per_schedule_document_order(self):
        result = extract_filing(JONES)
        ei = [n for n in result["nodes"] if n["node_type"] == "EconomicInterest"]
        a1 = [n for n in ei if n["properties"]["schedule"] == "A-1"]
        assert a1[0]["id"].endswith("-a-1-1")
        assert a1[1]["id"].endswith("-a-1-2")

    def test_alden_cover_only_clean_noop(self):
        result = extract_filing(ALDEN)
        env = result["envelope"]
        assert env["extraction_status"] == "parsed"
        assert [n for n in result["nodes"] if n["node_type"] == "EconomicInterest"] == []
        assert env["validation_checks"] == []
        assert env["schedule_line_counts"] == {}

    def test_no_text_layer_envelope_only_zero_graph_rows(self):
        result = extract_filing(JONES, text_extractor=lambda _p: "   ")
        env = result["envelope"]
        assert env["extraction_status"] == "no_text_layer"
        assert result["nodes"] == []  # zero graph rows
        assert result["edges"] == []
        assert len(env["validation_checks"]) == 1
        vc = env["validation_checks"][0]
        # validationcheck subject is the Filing id derived from metadata.
        assert vc["subject_node_id"] == env["filing_id"]
        assert vc["subject_node_type"] == "Filing"

    def test_constructed_filer_mismatch_zero_nodes_plus_validationcheck(self, tmp_path):
        # Construct a filing whose metadata filer_name disagrees with the cover.
        d = tmp_path / "216307037"
        d.mkdir()
        import shutil
        shutil.copy(JONES / "document.pdf", d / "document.pdf")
        md = json.loads((JONES / "metadata.json").read_text())
        md["filer_name"] = "Wrongname, Imposter"  # cover still says Jones, Sarah
        (d / "metadata.json").write_text(json.dumps(md))
        result = extract_filing(d)
        env = result["envelope"]
        assert env["extraction_status"] == "filer_mismatch"
        assert result["nodes"] == []
        assert len(env["validation_checks"]) == 1
        assert env["validation_checks"][0]["subject_node_type"] == "Filing"

    @werby_present
    def test_werby_51_nodes_by_schedule(self):
        result = extract_filing(WERBY_DIR)
        env = result["envelope"]
        counts = env["schedule_line_counts"]
        assert counts == {"A-1": 21, "A-2": 15, "B": 4, "C": 7, "D": 4}
        ei = [n for n in result["nodes"] if n["node_type"] == "EconomicInterest"]
        assert len(ei) == 51
        assert env["validation_checks"] == []


class TestScheduleOrder:
    def test_schedule_order_constant(self):
        assert SCHEDULE_ORDER == ["A-1", "A-2", "B", "C", "D", "E"]
