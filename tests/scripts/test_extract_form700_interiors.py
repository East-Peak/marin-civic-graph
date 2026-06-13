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
import re
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


# ---------------------------------------------------------------------------
# Unit 6 — resolution + Membership + e2e + ethics + determinism
# ---------------------------------------------------------------------------
import hashlib  # noqa: E402
import socket  # noqa: E402

from extract_form700_interiors import (  # noqa: E402
    apply_resolutions,
    build_schedule_c_membership,
    load_approved_resolutions,
    resolution_refs,
    resolve_counterparties,
    run,
)
from membership_builders import build_membership_node  # noqa: E402

HOLM_DIR = INTERIORS_DIR / "215754761"
STRIPPED = INTERIORS_DIR / "LOCAL_ONLY_STRIPPED_STRINGS.json"
# The pinned e2e needs the FULL basket (incl. the two local-only filings whose
# Werby rows are the resolution candidates).
full_basket = pytest.mark.skipif(
    not (WERBY_DIR / "document.pdf").is_file()
    or not (HOLM_DIR / "document.pdf").is_file(),
    reason="local-only PDFs absent (contributor checkout)",
)
EXISTING = [{"id": "org-test-grosvenor-properties", "display_label": "Grosvenor Properties Ltd."}]

PRE_APPROVAL = {
    "filings": {"captured": 6, "filer_mismatch": 0, "no_text_layer": 0, "parsed": 6},
    "interests": {"by_schedule": {"A-1": 25, "A-2": 20, "B": 5, "C": 9, "D": 4, "E": 2},
                  "emitted": 65, "unparsed_lines": 0},
    "memberships_emitted": 0,
    "resolution": {"approved_edges": 0, "deterministic_edges": 0,
                   "queued_candidates": 2, "unresolved_rows": 58},
    "validation_checks": 0,
}
POST_APPROVAL = {
    **PRE_APPROVAL,
    "memberships_emitted": 1,
    "resolution": {"approved_edges": 1, "deterministic_edges": 0,
                   "queued_candidates": 1, "unresolved_rows": 57},
}


def _approve_werby_c3(candidates, path):
    """Flip the Werby Sch C ordinal-3 candidate (President & CEO, Grosvenor
    Properties Ltd.) to approved — the operator act the e2e performs."""
    c3 = next(c for c in candidates if c["subject_ref"].endswith("-c-3"))
    path.write_text(json.dumps({**c3, "status": "approved"}) + "\n")
    return c3


class TestResolutionE2E:
    @full_basket
    def test_pre_approval_coverage_and_candidates(self, tmp_path):
        r = run(interiors_dirs=[INTERIORS_DIR], out_dir=tmp_path / "o",
                review_dir=tmp_path / "r", existing_orgs=EXISTING)
        assert r["coverage"] == PRE_APPROVAL
        # SAME_AS asserted empty inside resolve_counterparties (no raise).
        assert len(r["candidates"]) == 2
        assert all(c["confidence"] == 0.9 for c in r["candidates"])
        ii = [e for e in r["edges"] if e["relationship_type"] == "INTEREST_IN"]
        memb = [n for n in r["nodes"] if n["node_type"] == "Membership"]
        assert ii == [] and memb == []

    @full_basket
    def test_post_approval_emits_one_interest_in_and_one_membership(self, tmp_path):
        pre = run(interiors_dirs=[INTERIORS_DIR], out_dir=tmp_path / "o1",
                  review_dir=tmp_path / "r1", existing_orgs=EXISTING)
        approved = tmp_path / "approved.jsonl"
        c3 = _approve_werby_c3(pre["candidates"], approved)
        post = run(interiors_dirs=[INTERIORS_DIR], out_dir=tmp_path / "o2",
                   review_dir=tmp_path / "r2", existing_orgs=EXISTING,
                   approved_path=approved)
        assert post["coverage"] == POST_APPROVAL
        # exactly one INTEREST_IN: the C-3 node → the existing org.
        ii = [e for e in post["edges"] if e["relationship_type"] == "INTEREST_IN"]
        assert len(ii) == 1
        assert ii[0]["source_id"] == c3["subject_ref"]
        assert ii[0]["target_id"] == "org-test-grosvenor-properties"
        # exactly one Membership, role verbatim "President & CEO".
        memb = [n for n in post["nodes"] if n["node_type"] == "Membership"]
        assert len(memb) == 1
        assert memb[0]["properties"]["role"] == "President & CEO"
        assert memb[0]["properties"]["organization_id"] == "org-test-grosvenor-properties"
        # spine: MEMBER + MEMBER_OF_ORG + EVIDENCED_BY all sourced from the node.
        mid = memb[0]["id"]
        rels = {e["relationship_type"] for e in post["edges"] if e["source_id"] == mid}
        assert {"MEMBER", "MEMBER_OF_ORG", "EVIDENCED_BY"} <= rels

    @full_basket
    def test_real_property_rows_never_enter_resolution(self, tmp_path):
        r = run(interiors_dirs=[INTERIORS_DIR], out_dir=tmp_path / "o",
                review_dir=tmp_path / "r", existing_orgs=EXISTING)
        # No candidate subject is a real-property node.
        rp_nodes = {n["id"] for n in r["nodes"]
                    if n["node_type"] == "EconomicInterest"
                    and n["properties"]["interest_type"] == "real property"}
        cand_subjects = {c["subject_ref"] for c in r["candidates"]}
        assert rp_nodes and not (rp_nodes & cand_subjects)
        # 58 of 65 nodes are resolution-eligible.
        assert r["coverage"]["resolution"]["unresolved_rows"] == 58


class TestApprovedLoaderFailLouds:
    def test_non_approved_status_raises(self, tmp_path):
        p = tmp_path / "a.jsonl"
        p.write_text(json.dumps({"subject_ref": "economicinterest-x",
                                 "candidate_ref": "org-y", "status": "queued"}) + "\n")
        with pytest.raises(ValueError, match="status"):
            load_approved_resolutions(p, emitted_ei_ids={"economicinterest-x"},
                                      existing_org_ids={"org-y"})

    def test_stale_subject_ref_raises(self, tmp_path):
        p = tmp_path / "a.jsonl"
        p.write_text(json.dumps({"subject_ref": "economicinterest-ghost",
                                 "candidate_ref": "org-y", "status": "approved"}) + "\n")
        with pytest.raises(ValueError, match="subject_ref"):
            load_approved_resolutions(p, emitted_ei_ids={"economicinterest-x"},
                                      existing_org_ids={"org-y"})

    def test_stale_candidate_ref_raises(self, tmp_path):
        p = tmp_path / "a.jsonl"
        p.write_text(json.dumps({"subject_ref": "economicinterest-x",
                                 "candidate_ref": "org-ghost", "status": "approved"}) + "\n")
        with pytest.raises(ValueError, match="candidate_ref"):
            load_approved_resolutions(p, emitted_ei_ids={"economicinterest-x"},
                                      existing_org_ids={"org-y"})

    def test_byte_identical_duplicates_dedupe(self, tmp_path):
        p = tmp_path / "a.jsonl"
        row = json.dumps({"subject_ref": "economicinterest-x",
                          "candidate_ref": "org-y", "status": "approved"})
        p.write_text(row + "\n" + row + "\n")
        out = load_approved_resolutions(p, emitted_ei_ids={"economicinterest-x"},
                                        existing_org_ids={"org-y"})
        assert len(out) == 1


class TestMembershipConvergence:
    def test_schedule_c_and_990_paths_yield_identical_membership_id(self):
        # The P3 substrate: the SAME (person, org, role) via the Sch C path and
        # the M2b 990-officer path must produce the IDENTICAL membership id, so
        # load_neo4j dedups them onto one node.
        sch_c_node, _ = build_schedule_c_membership(
            person_id="person-f700-jane-doe", person_name="Jane Doe",
            organization_id="org-990-ein-123456789", organization_name="Acme Foundation",
            role="President & CEO", record_id="record-form700-interior-1",
        )
        m2b_node = build_membership_node(
            person_id="person-f700-jane-doe", person_name="Jane Doe",
            organization_id="org-990-ein-123456789", organization_name="Acme Foundation",
            role="President & CEO", confidence=1.0, source_basis="form_990",
            evidence_record_ids=["record-990-123456789-2023"],
        )
        assert sch_c_node["id"] == m2b_node["id"]


class TestDeterminism:
    @full_basket
    def test_two_runs_byte_identical(self, tmp_path):
        def run_once(tag):
            run(interiors_dirs=[INTERIORS_DIR], out_dir=tmp_path / tag,
                review_dir=tmp_path / f"rev{tag}", existing_orgs=EXISTING)
            digests = {}
            for f in sorted((tmp_path / tag).rglob("*")):
                if f.is_file():
                    digests[f.relative_to(tmp_path / tag).as_posix()] = \
                        hashlib.sha256(f.read_bytes()).hexdigest()
            return digests
        assert run_once("a") == run_once("b")


def _all_output_text(out_dir, review_dir):
    text = []
    for d in (out_dir, review_dir):
        for f in d.rglob("*"):
            if f.is_file():
                text.append(f.read_text(encoding="utf-8"))
    return "\n".join(text)


# Address/APN shapes the extractor must never emit. A street address is a number
# followed by a capitalized street name + suffix; an APN is the d-d-d parcel form.
_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Way|Court|Ct|"
    r"Boulevard|Blvd|Place|Pl|Circle|Cir|Terrace)\b"
)
_APN_RE = re.compile(r"\b\d{3}-\d{3}-\d{2,3}\b")


class TestEthicsScans:
    @full_basket
    def test_no_address_or_apn_shape_in_any_output(self, tmp_path):
        out, rev = tmp_path / "o", tmp_path / "r"
        run(interiors_dirs=[INTERIORS_DIR], out_dir=out, review_dir=rev,
            existing_orgs=EXISTING)
        text = _all_output_text(out, rev)
        # Mask allowlisted entity names (legit names that match address shapes).
        if STRIPPED.is_file():
            allow = json.loads(STRIPPED.read_text())
            for names in allow.get("allowed_containing", {}).values():
                for name in names:
                    text = text.replace(name, "<<ALLOWLISTED>>")
        assert not _ADDRESS_RE.search(text), "street-address shape leaked"
        assert not _APN_RE.search(text), "APN shape leaked"

    @full_basket
    def test_no_forbidden_stripped_string_in_any_output(self, tmp_path):
        assert STRIPPED.is_file(), (
            "local-only PDFs present but LOCAL_ONLY_STRIPPED_STRINGS.json absent "
            "— broken half-staged state, the leak detector must not be skipped"
        )
        out, rev = tmp_path / "o", tmp_path / "r"
        run(interiors_dirs=[INTERIORS_DIR], out_dir=out, review_dir=rev,
            existing_orgs=EXISTING)
        text = _all_output_text(out, rev)
        allow = json.loads(STRIPPED.read_text())
        for names in allow.get("allowed_containing", {}).values():
            for name in names:
                text = text.replace(name, "<<ALLOWLISTED>>")
        forbidden = [s for group in allow["forbidden"].values() for s in group]
        for bad in forbidden:
            assert bad not in text, "a forbidden stripped string leaked into output"

    @full_basket
    def test_cli_stdout_has_no_address_or_apn(self, tmp_path, capsys):
        from extract_form700_interiors import main
        main([
            "--interiors-dir", str(INTERIORS_DIR),
            "--out-dir", str(tmp_path / "o"),
            "--review-dir", str(tmp_path / "r"),
        ])
        captured = capsys.readouterr()
        assert not _ADDRESS_RE.search(captured.out + captured.err)
        assert not _APN_RE.search(captured.out + captured.err)


class TestZeroNetwork:
    @full_basket
    def test_no_socket_during_full_e2e(self, tmp_path, monkeypatch):
        # Ban network: any socket construction raises during the full e2e.
        def _banned(*a, **k):
            raise AssertionError("network access attempted")
        monkeypatch.setattr(socket, "socket", _banned)
        run(interiors_dirs=[INTERIORS_DIR], out_dir=tmp_path / "o",
            review_dir=tmp_path / "r", existing_orgs=EXISTING)

    def test_extractor_never_imports_neo4j(self, tmp_path):
        # In a CLEAN interpreter (the full pytest session pollutes global
        # sys.modules via other ingestors' tests), importing + running the
        # extractor must never pull in neo4j — no top-level import, --load lazy.
        import subprocess
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "import extract_form700_interiors as E;"
            "from pathlib import Path;"
            "E.run(interiors_dirs=[Path(sys.argv[2])], out_dir=Path(sys.argv[3]),"
            " review_dir=Path(sys.argv[4]),"
            " existing_orgs=[{'id':'org-test-grosvenor-properties',"
            " 'display_label':'Grosvenor Properties Ltd.'}]);"
            "assert 'neo4j' not in sys.modules, 'neo4j imported by extractor path';"
            "print('NO_NEO4J_OK')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(REPO_ROOT / "scripts"),
             str(INTERIORS_DIR), str(tmp_path / "o"), str(tmp_path / "r")],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "NO_NEO4J_OK" in result.stdout


class TestCommittedTextScan:
    """COMPLETION 3 — no forbidden address/APN string (or shape) reaches the
    PUBLIC repo history or the workspace evidence file. Mask the allowlisted
    entity names first (they legitimately appear in committed golden tests),
    then scan the full text of `git diff 2c24ebc..HEAD` (PDFs excluded) AND the
    workspace evidence file. Skipif the local-only strings file is absent."""

    @pytest.mark.skipif(not STRIPPED.is_file(), reason="local-only strings file absent")
    def test_no_forbidden_string_or_shape_in_committed_diff_or_evidence(self):
        import subprocess

        diff = subprocess.run(
            ["git", "diff", "2c24ebc..HEAD"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=True,
        ).stdout
        text = diff
        evidence = Path.home() / ".openclaw" / "workspace" / "goals" / "evidence" \
            / "2026-06-10-m4-evidence.md"
        if evidence.is_file():
            text += "\n" + evidence.read_text(encoding="utf-8")

        allow = json.loads(STRIPPED.read_text())
        for names in allow.get("allowed_containing", {}).values():
            for name in names:
                text = text.replace(name, "<<ALLOWLISTED>>")

        forbidden = [s for group in allow["forbidden"].values() for s in group]
        for bad in forbidden:
            assert bad not in text, "forbidden stripped string in committed diff/evidence"
        assert not _ADDRESS_RE.search(text), "street-address shape in committed diff/evidence"
        assert not _APN_RE.search(text), "APN shape in committed diff/evidence"
