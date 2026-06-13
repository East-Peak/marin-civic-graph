"""extract_form700_interiors.py — Form 700 interiors → EconomicInterest (M4).

Turns staged FPPC Form 700 Statement-of-Economic-Interests schedule PDFs into
`EconomicInterest` nodes (COI spec §4.2), the disclosure edge spine
(DISCLOSED_AS / EVIDENCED_BY / gated INTEREST_IN), and Sch C → Membership
convergence, with per-filing extraction envelopes and bundle-level
validationcheck candidates.

This module NEVER fetches and NEVER touches a live database. Text comes from
`pdftotext -layout` over staged fixture PDFs (the only process boundary; no
OCR). The `--load` step lazy-imports load_neo4j_v2 and is operator-gated — the
loop never runs it, and there is no top-level neo4j import.

Imported (consume, never modify) from ingest_form700: build_filing_node,
person_id_from_name, normalize_name — so interior-derived Filing/Person ids are
byte-identical to the NetFile-index path.

Operator runbook (capture is an operator step — the loop never fetches):

    NetFile replatformed the public portal into a Vue SPA (~2026); the old
    /pub/ WebForms export referenced by ingest_form700.py is dead. Current
    endpoints (verified 2026-06-10; send a curl-style User-Agent — the default
    urllib UA gets a 403 from the WAF):
      - Portal SPA:  https://netfile.com/public/<aid>/sei
                     (old https://public.netfile.com/pub/?aid=<AID> 301s here)
      - API base:    https://netfile.com/api/public/sites/
      - Index:       POST api/searchfilings  (JSON: aid, searchFilerName,
                     searchStatementType ∈ Annual|Assuming|Leaving|Candidate|
                     null, afterFilingDate/beforeFilingDate, currentPage/
                     pageSize). `searchSchedules` does NOT filter filings here.
                     Items carry filerName, filingDate (agency-LOCAL, no Z),
                     departmentName, positionName, filingId (GUID), periodStart/
                     periodEnd, amendments[]. Statement type is obtained per
                     filing by re-querying with the filter set.
      - Schedules:   POST api/searchtransactions (same body; searchSchedules ∈
                     ["A1","A2","B","C","D","E","Comment"] DOES filter here) —
                     structured per-line JSON, legacy NUMERIC image id in
                     filingId. Coverage survey + independent cross-check only;
                     the PDF text layer is the extraction ground truth (the API
                     pre-redacts Schedule B tenant names as "Name(s) redacted").
      - Download:    GET api/SeiDocuments/download/<GUID>?aid=<aid>  OR legacy
                     https://netfile.com/Connect2/api/public/image/<numeric-id>
                     (both work; the staged basket used the latter — it is the
                     source_url in every metadata.json). The PDF cover prints
                     `Filing ID: <numeric>`; its E-Filed stamp matches the index
                     filingDate.
      - RSS (15-day window): https://netfile.com/Connect2/api/public/list/
                     filing/rss/<AID>/sei.xml

    Per filing, write `<image-id>/document.pdf` + `<image-id>/metadata.json`
    (index-derived fields; this layout, byte-for-byte, is what the extractor
    consumes — including the local-only/.gitignore discipline for Schedule-B-
    bearing PDFs whose text layers print residential addresses/APNs). Then:
    export existing orgs from the live graph, run with --existing-orgs, review
    the resolver sidecar queue, extract the approved-only file, re-run, --load.
    Survey the Belvedere / Fairfax / Mill Valley coverage gaps. NetFile agencies
    = county (cmar) + 8 cities; all Schedules A–E, text-layer-first.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest_form700 import (  # noqa: E402
    build_filing_node,
    normalize_name,
)

# Metadata keys the reader relies on. A staged filing missing any of these is a
# broken capture — fail loud naming the KEYS only (never the values).
REQUIRED_METADATA_KEYS: frozenset[str] = frozenset({
    "filer_name",
    "filed_at",
    "statement_type",
    "job_title",
    "department",
    "agency_id",
    "agency_label",
    "image_id",
    "filing_guid",
    "schedules",
    "source_url",
    "pdf_sha256",
})


def load_metadata(image_dir: Path) -> dict[str, Any]:
    """Read and validate `<image_dir>/metadata.json`.

    Missing required keys raise ValueError naming the absent KEYS only — the
    ethics keys-only rule (a fail-loud never echoes a raw field value).
    """
    path = image_dir / "metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_METADATA_KEYS - set(metadata))
    if missing:
        raise ValueError(
            f"metadata.json in {image_dir.name} missing required keys: "
            f"{', '.join(missing)}"
        )
    return metadata


def verify_pdf_sha256(image_dir: Path, metadata: dict[str, Any]) -> None:
    """Verify `<image_dir>/document.pdf` matches the pinned sha256.

    The fixture is evidence: a hash mismatch means the staged PDF is not the
    captured bytes — BLOCK (never fetch, never proceed on drift).
    """
    pdf_bytes = (image_dir / "document.pdf").read_bytes()
    actual = hashlib.sha256(pdf_bytes).hexdigest()
    expected = metadata["pdf_sha256"]
    if actual != expected:
        raise ValueError(
            f"document.pdf sha256 mismatch in {image_dir.name}: "
            f"expected {expected}, got {actual}"
        )


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract the PDF text layer via `pdftotext -layout` (the only process
    boundary; no OCR). Returns stdout as a string."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def classify_text_status(text: str) -> str:
    """`parsed` if the PDF has a usable text layer, else `no_text_layer`
    (a scanned filing — counted, never an error; OCR is out of M4)."""
    return "parsed" if text.strip() else "no_text_layer"


def filer_matches(metadata_filer: str, cover_filer: str) -> bool:
    """True when the cover-sheet filer reconciles with metadata `filer_name`.

    Both are run through the imported normalize_name ("Last, First" → "First
    Last") and compared case-insensitively. A mismatch is never resolved by
    guessing which identity is right (Predeclared 5).
    """
    return (
        normalize_name(metadata_filer).casefold()
        == normalize_name(cover_filer).casefold()
    )


def _metadata_to_filing_row(metadata: dict[str, Any]) -> dict[str, Any]:
    """Project metadata.json onto the row shape build_filing_node expects, so
    the interior-derived Filing id is byte-identical to the index path."""
    return {
        "filer_name": metadata["filer_name"],
        "filed_at": metadata["filed_at"],
        "statement_type": metadata["statement_type"],
        "job_title": metadata["job_title"],
        "department": metadata["department"],
    }


def filing_node_for(metadata: dict[str, Any]) -> dict[str, Any]:
    """Build the Filing node from metadata via the imported build_filing_node."""
    return build_filing_node(
        _metadata_to_filing_row(metadata),
        agency_id=metadata["agency_id"],
        agency_label=metadata["agency_label"],
    )


def read_interior(
    image_dir: Path,
    *,
    text_extractor: Callable[[Path], str] = extract_pdf_text,
) -> dict[str, Any]:
    """Read one staged interior filing: validate metadata, verify the PDF hash,
    extract the text layer, and classify extraction status.

    Returns a reading dict consumed by the assembly stage:
      {metadata, text, extraction_status, filing_node, filing_id}.
    `text_extractor` is injectable so the no_text_layer branch is testable
    without a scanned PDF.
    """
    metadata = load_metadata(image_dir)
    verify_pdf_sha256(image_dir, metadata)

    raw_text = text_extractor(image_dir / "document.pdf")
    status = classify_text_status(raw_text)
    text = raw_text if status == "parsed" else ""

    filing_node = filing_node_for(metadata)
    return {
        "metadata": metadata,
        "text": text,
        "extraction_status": status,
        "filing_node": filing_node,
        "filing_id": filing_node["id"],
    }


def iter_image_dirs(interiors_dir: Path) -> list[Path]:
    """Return the immediate `<image-id>/` child dirs (those holding a
    metadata.json), sorted by name for deterministic processing."""
    return sorted(
        (child for child in interiors_dir.iterdir()
         if child.is_dir() and (child / "metadata.json").is_file()),
        key=lambda p: p.name,
    )
