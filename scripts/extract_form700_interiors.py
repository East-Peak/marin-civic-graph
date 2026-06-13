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
    build_filed_by_edge,
    build_filing_node,
    normalize_name,
    person_id_from_name,
)
from economic_interest_builders import (  # noqa: E402
    build_disclosed_as_edge,
    build_economic_interest_node,
    build_evidenced_by_edge,
)
from form700_schedule_parsers import (  # noqa: E402
    find_schedule_pages,
    parse_cover,
    parse_schedule_a1,
    parse_schedule_a2,
    parse_schedule_b,
    parse_schedule_c,
    parse_schedule_d,
    parse_schedule_e,
)
from extract_san_rafael_city_campaign_form460_schedules import (  # noqa: E402
    build_validation_check,
    build_validation_check_id,
)

# Canonical schedule emission order (also the coverage by_schedule key order).
SCHEDULE_ORDER: list[str] = ["A-1", "A-2", "B", "C", "D", "E"]

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
    [Middle] Last") and reconciled on FIRST and LAST name, case-insensitively —
    a middle name/initial that the cover prints but the index omits (real basket
    fact: index "Jones, Sarah" vs cover "Jones, Sarah B") is not a mismatch. A
    genuine mismatch is never resolved by guessing which identity is right
    (Predeclared 5).
    """
    a = normalize_name(metadata_filer).casefold().split()
    b = normalize_name(cover_filer).casefold().split()
    if not a or not b:
        return False
    return a[0] == b[0] and a[-1] == b[-1]


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


# ---------------------------------------------------------------------------
# Unit 5 — assembly + reconciliation
# ---------------------------------------------------------------------------

def parse_all_schedules(
    pdf_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], int]:
    """Run every schedule parser the PDF's pages call for.

    Returns (lines_by_schedule, unparsed_records, literal_none_skip_count).
    """
    pages = find_schedule_pages(pdf_path)
    by_schedule: dict[str, list[dict[str, Any]]] = {}
    unparsed: list[dict[str, Any]] = []
    skipped_none = 0
    for sched, page_list in pages.items():
        if sched == "A-1":
            by_schedule[sched] = parse_schedule_a1(pdf_path, page_list)
        elif sched == "A-2":
            lines, skips = parse_schedule_a2(pdf_path, page_list)
            by_schedule[sched] = lines
            skipped_none += skips
        elif sched == "B":
            by_schedule[sched] = parse_schedule_b(pdf_path, page_list)
        elif sched == "C":
            lines, unp = parse_schedule_c(pdf_path, page_list)
            by_schedule[sched] = lines
            unparsed.extend(unp)
        elif sched == "D":
            by_schedule[sched] = parse_schedule_d(pdf_path, page_list)
        elif sched == "E":
            by_schedule[sched] = parse_schedule_e(pdf_path, page_list)
    return by_schedule, unparsed, skipped_none


def _record_id(image_id: str) -> str:
    return f"record-form700-interior-{image_id}"


def build_record_node(metadata: dict[str, Any]) -> dict[str, Any]:
    """One Record node per captured PDF (provenance for EVIDENCED_BY)."""
    image_id = metadata["image_id"]
    return {
        "id": _record_id(image_id),
        "node_type": "Record",
        "labels": ["Record"],
        "display_label": (
            f"Form 700 interior — {normalize_name(metadata['filer_name'])} — "
            f"{metadata['filed_at']}"
        ),
        "properties": {
            "source_url": metadata["source_url"],
            "image_id": image_id,
            "filing_guid": metadata["filing_guid"],
            "record_type": "form700_interior_pdf",
        },
    }


def build_person_node(metadata: dict[str, Any]) -> dict[str, Any]:
    """Filer Person node — id byte-identical to the NetFile-index path."""
    return {
        "id": person_id_from_name(metadata["filer_name"]),
        "node_type": "Person",
        "labels": ["Person"],
        "display_label": normalize_name(metadata["filer_name"]),
        "properties": {
            "name": normalize_name(metadata["filer_name"]),
            "source_filer_name": metadata["filer_name"],
            "source": f"form700-{metadata['agency_id']}",
        },
    }


def _failure_validationcheck(
    *, filing_id: str, record_id: str, image_id: str, check_type: str, metric: str,
    measured_label: str, reference_label: str,
) -> dict[str, Any]:
    """A bundle-level validationcheck for a failed extraction (no_text_layer /
    filer_mismatch). Subject is the Filing id (derived from metadata via
    build_filing_node). Labels name the condition, never a raw field value."""
    return build_validation_check(
        check_id=build_validation_check_id([image_id, check_type]),
        check_type=check_type,
        subject_node_id=filing_id,
        subject_node_type="Filing",
        metric_name=metric,
        measured_value_number=None,
        measured_value_label=measured_label,
        reference_value_number=None,
        reference_value_label=reference_label,
        derived_from_record_id=record_id,
        evidence_record_ids=[record_id],
    )


def _reconcile_cover(
    cover: dict[str, Any],
    schedules_with_nodes: set[str],
    *,
    filing_id: str,
    record_id: str,
    image_id: str,
) -> list[dict[str, Any]]:
    """Cover §4 declared-attached vs schedules that actually yielded nodes. A
    schedule marked but empty, or nodes from an unmarked schedule, each emit one
    validationcheck candidate (fail-never-silent). Labels name the schedule tag
    only — never a counterparty value."""
    marked = set(cover["schedules_marked"])
    checks: list[dict[str, Any]] = []
    for sched in sorted(marked - schedules_with_nodes):
        checks.append(build_validation_check(
            check_id=build_validation_check_id([image_id, "declared-empty", sched]),
            check_type="form700_schedule_declared_but_empty",
            subject_node_id=filing_id,
            subject_node_type="Filing",
            metric_name="cover_schedule_reconciliation",
            measured_value_number=0,
            measured_value_label=f"schedule {sched} marked attached",
            reference_value_number=None,
            reference_value_label="zero parsed lines",
            derived_from_record_id=record_id,
            evidence_record_ids=[record_id],
        ))
    for sched in sorted(schedules_with_nodes - marked):
        checks.append(build_validation_check(
            check_id=build_validation_check_id([image_id, "parsed-unmarked", sched]),
            check_type="form700_schedule_parsed_but_unmarked",
            subject_node_id=filing_id,
            subject_node_type="Filing",
            metric_name="cover_schedule_reconciliation",
            measured_value_number=None,
            measured_value_label=f"schedule {sched} parsed",
            reference_value_number=0,
            reference_value_label="not marked on cover §4",
            derived_from_record_id=record_id,
            evidence_record_ids=[record_id],
        ))
    return checks


def _new_envelope(metadata: dict[str, Any], filing_id: str, status: str) -> dict[str, Any]:
    return {
        "image_id": metadata["image_id"],
        "filing_guid": metadata["filing_guid"],
        "filing_id": filing_id,
        "extraction_status": status,
        "schedules_declared": metadata["schedules"],
        "schedule_line_counts": {},
        "interests": [],
        "unparsed": [],
        "skipped_literal_none": 0,
        "validation_checks": [],
    }


def extract_filing(
    image_dir: Path,
    *,
    text_extractor: "Callable[[Path], str]" = extract_pdf_text,
) -> dict[str, Any]:
    """Extract one staged interior filing end to end (graph emission is
    parsed-only).

    Returns {envelope, nodes, edges, interests}. INTEREST_IN edges and Sch C
    Memberships are added later (Unit 6, resolution-gated) — this stage emits
    the EconomicInterest nodes and the DISCLOSED_AS / EVIDENCED_BY / FILED_BY
    spine for `parsed` filings only; a no_text_layer / filer_mismatch filing
    contributes envelope + validationcheck and ZERO graph rows.
    """
    reading = read_interior(image_dir, text_extractor=text_extractor)
    metadata = reading["metadata"]
    filing_id = reading["filing_id"]
    image_id = metadata["image_id"]
    record_id = _record_id(image_id)

    # Failure: no text layer → envelope + validationcheck only, zero graph rows.
    if reading["extraction_status"] == "no_text_layer":
        env = _new_envelope(metadata, filing_id, "no_text_layer")
        env["validation_checks"].append(_failure_validationcheck(
            filing_id=filing_id, record_id=record_id, image_id=image_id,
            check_type="form700_no_text_layer",
            metric="pdf_text_layer",
            measured_label="empty text layer (scanned filing)",
            reference_label="extractable text expected",
        ))
        return {"envelope": env, "nodes": [], "edges": [], "interests": []}

    pdf_path = image_dir / "document.pdf"
    cover = parse_cover(pdf_path)

    # Failure: cover filer does not reconcile with the index filer_name.
    if not filer_matches(metadata["filer_name"], cover["cover_filer"] or ""):
        env = _new_envelope(metadata, filing_id, "filer_mismatch")
        env["validation_checks"].append(_failure_validationcheck(
            filing_id=filing_id, record_id=record_id, image_id=image_id,
            check_type="form700_filer_mismatch",
            metric="cover_filer_reconciliation",
            measured_label="cover filer",
            reference_label="index filer_name",
        ))
        return {"envelope": env, "nodes": [], "edges": [], "interests": []}

    # Parsed: build the graph spine + EconomicInterest nodes.
    by_schedule, unparsed, skipped_none = parse_all_schedules(pdf_path)

    nodes: list[dict[str, Any]] = [
        reading["filing_node"],
        build_person_node(metadata),
        build_record_node(metadata),
    ]
    edges: list[dict[str, Any]] = [
        build_filed_by_edge(filing_id, person_id_from_name(metadata["filer_name"])),
    ]
    interests: list[dict[str, Any]] = []
    schedule_line_counts: dict[str, int] = {}
    filer_norm = normalize_name(metadata["filer_name"])

    for sched in SCHEDULE_ORDER:
        lines = by_schedule.get(sched, [])
        if not lines:
            continue
        schedule_line_counts[sched] = len(lines)
        for ordinal, line in enumerate(lines, start=1):
            node = build_economic_interest_node(
                filing_id=filing_id,
                schedule=sched,
                line_ordinal=ordinal,
                interest_type=line["interest_type"],
                counterparty_name_raw=line["counterparty_name_raw"],
                filer_normalized_name=filer_norm,
                filed_at=metadata["filed_at"],
                evidence_record_ids=[record_id],
                amount_band=line["amount_band"],
                amount=line["amount"],
                position=line["position"],
            )
            nodes.append(node)
            edges.append(build_disclosed_as_edge(filing_id, node["id"]))
            edges.append(build_evidenced_by_edge(node["id"], record_id))
            interests.append({
                "node_id": node["id"],
                "schedule": sched,
                "line_ordinal": ordinal,
                "interest_type": line["interest_type"],
                "counterparty_name_raw": line["counterparty_name_raw"],
                "amount_band": line["amount_band"],
                "amount": line["amount"],
                "position": line["position"],
                "is_spouse": line["is_spouse"],
                "envelope": line["envelope"],
            })

    validation_checks = _reconcile_cover(
        cover, set(schedule_line_counts),
        filing_id=filing_id, record_id=record_id, image_id=image_id,
    )

    env = _new_envelope(metadata, filing_id, "parsed")
    env["schedule_line_counts"] = schedule_line_counts
    env["interests"] = interests
    env["unparsed"] = unparsed
    env["skipped_literal_none"] = skipped_none
    env["validation_checks"] = validation_checks

    return {
        "envelope": env,
        "nodes": nodes,
        "edges": edges,
        "interests": interests,
        "cover": cover,
    }
