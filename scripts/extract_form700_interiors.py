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
    build_interest_in_edge,
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
        return {"envelope": env, "nodes": [], "edges": [], "interests": [], "metadata": metadata}

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
        return {"envelope": env, "nodes": [], "edges": [], "interests": [], "metadata": metadata}

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
                "evidence_record_ids": [record_id],
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
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# Unit 6 — resolution + Membership + coverage + CLI
# ---------------------------------------------------------------------------

from org_resolution import propose_org_resolutions  # noqa: E402
from membership_builders import (  # noqa: E402
    build_evidenced_by_edge as build_membership_evidenced_by_edge,
    build_member_edge,
    build_member_of_org_edge,
    build_membership_node,
)

# Real-property interest types never enter org resolution — their counterparty
# is a city/locality string, not an organization name (Predeclared 6).
_RESOLUTION_EXCLUDED_TYPES = {"real property"}


def resolution_refs(interests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One resolver ref per resolution-eligible EconomicInterest (every emitted
    node EXCEPT real-property rows). ref = {id, display_label, evidence_record_ids}."""
    refs: list[dict[str, Any]] = []
    for interest in interests:
        if interest["interest_type"] in _RESOLUTION_EXCLUDED_TYPES:
            continue
        refs.append({
            "id": interest["node_id"],
            "display_label": interest["counterparty_name_raw"],
            "evidence_record_ids": interest.get("evidence_record_ids", []),
        })
    return refs


def resolve_counterparties(
    refs: list[dict[str, Any]], existing_orgs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Run the shared org resolver over the eligible refs. Form 700 lines carry
    NO identity key, so the resolver's SAME_AS list MUST come back empty — assert
    it (fail loud otherwise). Returns the queued ResolutionCandidate rows."""
    same_as, candidates = propose_org_resolutions(refs, existing_orgs)
    if same_as:
        raise ValueError(
            f"resolver returned {len(same_as)} SAME_AS edge(s); Form 700 rows "
            f"carry no identity key, so M4 must auto-merge nothing"
        )
    return candidates


def _candidate_key(row: dict[str, Any]) -> tuple[str, str]:
    return (row["subject_ref"], row["candidate_ref"])


def write_resolution_sidecar(
    candidates: list[dict[str, Any]],
    path: Path,
    *,
    approved_keys: set[tuple[str, str]] = frozenset(),
) -> int:
    """Write queued ResolutionCandidate rows to the JSONL sidecar, deterministically
    (sorted; byte-identical duplicates deduped). An already-approved pair is not
    re-queued. Returns the number of rows written."""
    seen: set[str] = set()
    rows: list[str] = []
    for cand in candidates:
        if _candidate_key(cand) in approved_keys:
            continue
        line = json.dumps(cand, sort_keys=True)
        if line in seen:
            continue
        seen.add(line)
        rows.append(line)
    rows.sort()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(r + "\n" for r in rows), encoding="utf-8")
    return len(rows)


def load_approved_resolutions(
    path: Path,
    *,
    emitted_ei_ids: set[str],
    existing_org_ids: set[str],
) -> list[dict[str, Any]]:
    """Load operator-approved (EconomicInterest → Organization) resolutions.

    Re-implemented for M4's ref semantics — NOT imported from
    build_dual_role_candidates (its loader's known-id set is funding-lane-shaped).
    Every row must have status == "approved", a subject_ref that is an
    EconomicInterest id emitted THIS run, and a candidate_ref present in
    --existing-orgs. Anything else fails loud; byte-identical duplicates dedupe.
    """
    approved: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        row = json.loads(raw)
        if row.get("status") != "approved":
            raise ValueError(
                f"approved-resolutions line {lineno}: status is "
                f"{row.get('status')!r}, expected 'approved'"
            )
        subject, candidate = row.get("subject_ref"), row.get("candidate_ref")
        if subject not in emitted_ei_ids:
            raise ValueError(
                f"approved-resolutions line {lineno}: subject_ref is not an "
                f"EconomicInterest id emitted this run"
            )
        if candidate not in existing_org_ids:
            raise ValueError(
                f"approved-resolutions line {lineno}: candidate_ref is not an "
                f"id present in --existing-orgs"
            )
        key = (subject, candidate)
        if key in seen:
            continue
        seen.add(key)
        approved.append({"subject_ref": subject, "candidate_ref": candidate})
    return approved


def build_schedule_c_membership(
    *,
    person_id: str,
    person_name: str,
    organization_id: str,
    organization_name: str,
    role: str,
    record_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A Sch C business position → Membership, through membership_builders (the
    SAME builder the M2b 990-officer path uses, so the same (person, org, role,
    started_at) converges on one membership id — the P3 substrate)."""
    node = build_membership_node(
        person_id=person_id,
        person_name=person_name,
        organization_id=organization_id,
        organization_name=organization_name,
        role=role,
        confidence=1.0,
        source_basis="form_700_schedule_c",
        evidence_record_ids=[record_id],
    )
    edges = [
        build_member_edge(node["id"], person_id),
        build_member_of_org_edge(node["id"], organization_id),
        build_membership_evidenced_by_edge(node["id"], record_id),
    ]
    return node, edges


def apply_resolutions(
    filings: list[dict[str, Any]],
    approved: list[dict[str, Any]],
    *,
    metadata_by_node: dict[str, dict[str, Any]],
    interest_by_node: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Emit gated INTEREST_IN edges and Sch C Memberships for approved rows.

    Returns (interest_in_edges, membership_nodes, membership_edges). A Membership
    is emitted only when the org resolved (approved) AND the row is a Sch C
    business position (non-empty position, not literal None) that is the filer's
    OWN (not spouse). A-2 positions never emit a Membership.
    """
    interest_edges: list[dict[str, Any]] = []
    membership_nodes: list[dict[str, Any]] = []
    membership_edges: list[dict[str, Any]] = []

    for row in approved:
        ei_id, org_id = row["subject_ref"], row["candidate_ref"]
        interest_edges.append(build_interest_in_edge(ei_id, org_id))

        interest = interest_by_node[ei_id]
        meta = metadata_by_node[ei_id]
        eligible_membership = (
            interest["schedule"] == "C"
            and interest["interest_type"] == "income source"
            and interest["position"]
            and not interest["is_spouse"]
        )
        if eligible_membership:
            node, edges = build_schedule_c_membership(
                person_id=person_id_from_name(meta["filer_name"]),
                person_name=normalize_name(meta["filer_name"]),
                organization_id=org_id,
                organization_name=interest["counterparty_name_raw"],
                role=interest["position"],
                record_id=_record_id(meta["image_id"]),
            )
            membership_nodes.append(node)
            membership_edges.extend(edges)

    return interest_edges, membership_nodes, membership_edges


def build_coverage(
    *,
    filings: list[dict[str, Any]],
    eligible_ref_count: int,
    approved_edge_count: int,
    queued_candidate_count: int,
    membership_count: int,
) -> dict[str, Any]:
    """The pinned coverage object (Predeclared 7). Integers only; `resolution.*`
    counts resolution-eligible rows; `deterministic_edges` is structurally 0."""
    status_counts = {"captured": 0, "filer_mismatch": 0, "no_text_layer": 0, "parsed": 0}
    by_schedule = {s: 0 for s in SCHEDULE_ORDER}
    emitted = 0
    unparsed_lines = 0
    validation_checks = 0
    for filing in filings:
        env = filing["envelope"]
        status_counts["captured"] += 1
        status_counts[env["extraction_status"]] += 1
        for sched, n in env["schedule_line_counts"].items():
            by_schedule[sched] += n
            emitted += n
        unparsed_lines += len(env["unparsed"])
        validation_checks += len(env["validation_checks"])
    return {
        "filings": status_counts,
        "interests": {
            "by_schedule": by_schedule,
            "emitted": emitted,
            "unparsed_lines": unparsed_lines,
        },
        "memberships_emitted": membership_count,
        "resolution": {
            "approved_edges": approved_edge_count,
            "deterministic_edges": 0,
            "queued_candidates": queued_candidate_count,
            "unresolved_rows": eligible_ref_count - approved_edge_count,
        },
        "validation_checks": validation_checks,
    }


# ---------------------------------------------------------------------------
# Orchestration + CLI
# ---------------------------------------------------------------------------

_SIDECAR_NAME = "resolution-candidates-form700.jsonl"
_COVERAGE_NAME = "form700-interiors-coverage.json"


def _sorted_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(nodes, key=lambda n: n["id"])


def _sorted_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        edges,
        key=lambda e: (e["source_id"], e["relationship_type"], e["target_id"]),
    )


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )


def run(
    *,
    interiors_dirs: list[Path],
    out_dir: Path,
    review_dir: Path,
    existing_orgs: list[dict[str, Any]] | None = None,
    approved_path: Path | None = None,
    text_extractor: "Callable[[Path], str]" = extract_pdf_text,
    write_outputs: bool = True,
) -> dict[str, Any]:
    """Extract every staged interior, resolve counterparties (approved-only
    INTEREST_IN + Sch C Membership), and emit envelopes + nodes/edges + the
    pinned coverage object + the resolution sidecar. Pure: never fetches, never
    touches a DB (no_text_layer/filer_mismatch contribute envelope-only)."""
    existing_orgs = existing_orgs or []

    filings: list[dict[str, Any]] = []
    for parent in interiors_dirs:
        for image_dir in iter_image_dirs(parent):
            filings.append(extract_filing(image_dir, text_extractor=text_extractor))

    all_interests = [i for f in filings for i in f["interests"]]
    interest_by_node = {i["node_id"]: i for i in all_interests}
    metadata_by_node = {
        i["node_id"]: f["metadata"]
        for f in filings for i in f["interests"]
    }

    refs = resolution_refs(all_interests)
    candidates = resolve_counterparties(refs, existing_orgs)

    emitted_ei_ids = set(interest_by_node)
    existing_org_ids = {o["id"] for o in existing_orgs}
    approved: list[dict[str, Any]] = []
    if approved_path is not None:
        approved = load_approved_resolutions(
            approved_path,
            emitted_ei_ids=emitted_ei_ids,
            existing_org_ids=existing_org_ids,
        )
    approved_keys = {(a["subject_ref"], a["candidate_ref"]) for a in approved}

    sidecar_path = review_dir / _SIDECAR_NAME
    queued = write_resolution_sidecar(
        candidates, sidecar_path, approved_keys=approved_keys,
    ) if write_outputs else len(
        {json.dumps(c, sort_keys=True) for c in candidates
         if _candidate_key(c) not in approved_keys}
    )

    interest_edges, membership_nodes, membership_edges = apply_resolutions(
        filings, approved,
        metadata_by_node=metadata_by_node,
        interest_by_node=interest_by_node,
    )

    nodes = [n for f in filings for n in f["nodes"]] + membership_nodes
    edges = (
        [e for f in filings for e in f["edges"]]
        + interest_edges + membership_edges
    )

    coverage = build_coverage(
        filings=filings,
        eligible_ref_count=len(refs),
        approved_edge_count=len(approved),
        queued_candidate_count=queued,
        membership_count=len(membership_nodes),
    )

    if write_outputs:
        for filing in filings:
            env = filing["envelope"]
            env_path = out_dir / "extracted" / f"{env['image_id']}.json"
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.write_text(
                json.dumps(env, sort_keys=True, indent=2) + "\n", encoding="utf-8",
            )
        _write_jsonl(_sorted_nodes(nodes), out_dir / "nodes.jsonl")
        _write_jsonl(_sorted_edges(edges), out_dir / "edges.jsonl")
        (out_dir / _COVERAGE_NAME).write_text(
            json.dumps(coverage, sort_keys=True, indent=2) + "\n", encoding="utf-8",
        )

    return {
        "filings": filings,
        "nodes": nodes,
        "edges": edges,
        "coverage": coverage,
        "candidates": candidates,
        "queued": queued,
        "approved": approved,
        "membership_nodes": membership_nodes,
    }


def _load_existing_orgs(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    return data if isinstance(data, list) else data.get("organizations", [])


def _lazy_load_to_neo4j(out_dir: Path) -> None:  # pragma: no cover - operator-only
    """Operator-gated --load: lazy-import load_neo4j_v2 (NO top-level neo4j
    import; the loop never runs this)."""
    import importlib

    loader = importlib.import_module("load_neo4j_v2")
    loader.load_bundle(out_dir)  # type: ignore[attr-defined]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract Form 700 interiors → EconomicInterest (M4).",
    )
    parser.add_argument(
        "--interiors-dir", action="append", required=True, type=Path,
        help="parent dir whose children are <image-id>/ dirs (repeatable)",
    )
    parser.add_argument("--existing-orgs", type=Path, default=None)
    parser.add_argument("--approved-resolutions", type=Path, default=None)
    parser.add_argument("--review-dir", type=Path, default=Path("data/review"))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--load", action="store_true",
                        help="operator-gated: load the bundle into Neo4j")
    args = parser.parse_args(argv)

    result = run(
        interiors_dirs=args.interiors_dir,
        out_dir=args.out_dir,
        review_dir=args.review_dir,
        existing_orgs=_load_existing_orgs(args.existing_orgs),
        approved_path=args.approved_resolutions,
    )

    cov = result["coverage"]
    print(
        f"form700 interiors: {cov['filings']['parsed']} parsed / "
        f"{cov['filings']['captured']} captured; "
        f"{cov['interests']['emitted']} EconomicInterest; "
        f"{cov['memberships_emitted']} Membership; "
        f"resolution approved={cov['resolution']['approved_edges']} "
        f"queued={cov['resolution']['queued_candidates']} "
        f"unresolved={cov['resolution']['unresolved_rows']}; "
        f"validationchecks={cov['validation_checks']}"
    )

    if args.load:
        _lazy_load_to_neo4j(args.out_dir)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
