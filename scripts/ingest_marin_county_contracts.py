"""ingest_marin_county_contracts.py — County of Marin delegated-contracts → graph (M3 leg-1).

Turns the County of Marin "delegated contracts" open-data CSV (vendor-level
contracts signed under delegated authority, July 2016→present; a SLICE of County
spend, NOT the full checkbook) into funding-IN `MoneyFlow` facts. The funder side
(County + departments) is modeled as Government `Organization` source nodes; the
recipient side is raw-name-on-the-fact (`recipient_name_raw`) until an operator
reviews a resolution and draws the gated `TO_TARGET` edge — NO recipient node is
auto-created, and NEVER a `Person` node (the file mixes orgs and individual
contractors; an individual is a small private vendor, scrutiny stays up the power
gradient, and nothing about them is ever indexed/profiled/published).

Money is `Decimal`, never float. This module NEVER fetches and NEVER touches a
live database (lazy `--load`, no top-level neo4j import), mirroring ingest_990 /
ingest_usaspending / extract_form700_interiors.

Operator capture (the loop never fetches): the dataset is published open data —
no records request needed. Full CSV in one command:
    curl -L -o delegated-contracts.csv \
      "https://data.marincounty.gov/api/views/rp6f-b7dy/rows.csv?accessType=DOWNLOAD"
SODA API for incremental pulls: https://data.marincounty.gov/resource/rp6f-b7dy.json
(no auth; $limit/$offset/$order paging). The full County AP/warrant register —
the real checkbook — is a separate CPRA records request (see the M3 runbook); this
delegated-contract slice is corroboration, never represented as total County spend.

Design reviewed adversarially by Codex (2 rounds): recipient identity is
name-only and review-gated; row-stable ids; Decimal tie-out; machine-readable
coverage honesty on every flow.
"""
from __future__ import annotations

import csv
import hashlib
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

# The "Review Contract" cell is "<contract#> (<url>)" — pull the URL out.
_URL_RE = re.compile(r"https?://[^)\s]+")

HEURISTIC_VERSION = "v1"

# Org-ness tokens (advisory only). Calibrated against the staged file.
_ORG_TOKEN_RE = re.compile(
    r"\b(inc|llc|l\.l\.c|corp|co|company|ltd|llp|lp|associates|partners|group|"
    r"foundation|fund|trust|services|service|systems|solutions|center|centre|"
    r"school|district|university|college|institute|hospital|clinic|church|"
    r"department|county|city|state|agency|authority|commission|board|society|"
    r"association|council|coalition|alliance|network|consulting|engineering|"
    r"construction|enterprises|technologies|tech|holdings|capital|properties|"
    r"realty|bank|insurance|medical|health|works|club|league|union|pta|usa|"
    r"academy|productions|entertainment|music|dance|chorus|symphony)\b",
    re.I,
)


def _looks_org(name: str) -> bool:
    return bool(_ORG_TOKEN_RE.search(name)) or "," in name or "&" in name


def _looks_person(name: str) -> bool:
    # Exactly two alphabetic words, no org token — a weak "personal name" signal.
    return (
        not _looks_org(name)
        and bool(re.fullmatch(r"[A-Za-z][A-Za-z.'-]+ [A-Za-z][A-Za-z.'-]+", name.strip()))
    )


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _row_uid(data_portal_id: str) -> str:
    """Row-stable, collision-free key from the (unique) raw Data Portal ID.
    A hash, because the raw id embeds a truncated vendor name and slugs collide."""
    return hashlib.sha1(data_portal_id.encode("utf-8")).hexdigest()[:12]


def moneyflow_id(data_portal_id: str) -> str:
    return f"moneyflow-marincontract-{_row_uid(data_portal_id)}"


def record_id(data_portal_id: str) -> str:
    return f"record-marincontract-{_row_uid(data_portal_id)}"


COUNTY_ID = "org-marincounty"


def department_id(department: str) -> str:
    """Case-insensitive-stable department node id."""
    return f"org-marincounty-dept-{slugify(department)}"

# CSV display-header → normalized key. (The SODA API field names differ; the CSV
# export uses these human headers.)
_HEADER_MAP = {
    "Month and Year": "month_and_year",
    "Contract Number": "contract_number",
    "Review Contract": "review_contract",
    "Department": "department",
    "Vendor Name": "vendor_name_raw",
    "Amount ($)": "amount",
    "Data Portal ID": "data_portal_id",
}


def _parse_amount(raw: str) -> Decimal | None:
    """Parse a dollar amount as Decimal. Empty/blank → None (missing, distinct
    from a real $0). Never float."""
    raw = (raw or "").strip().replace(",", "").replace("$", "")
    if raw == "":
        return None
    return Decimal(raw)


def parse_contract_rows(csv_path: Path) -> list[dict[str, Any]]:
    """Read the delegated-contracts CSV into normalized row dicts.

    Each row: {month_and_year, contract_number, review_contract (url|None),
    department, vendor_name_raw, amount (Decimal|None), data_portal_id}.
    """
    rows: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            row = {key: (raw.get(header) or "").strip()
                   for header, key in _HEADER_MAP.items()}
            row["amount"] = _parse_amount(row["amount"])
            url = _URL_RE.search(row["review_contract"])
            row["review_contract"] = url.group(0) if url else None
            rows.append(row)
    return rows


def source_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Frozen source-profile metrics — pinned by tests so a silently changed CSV
    (different row count / total) fails loud instead of skewing the graph."""
    present = [r["amount"] for r in rows if r["amount"] is not None]
    return {
        "row_count": len(rows),
        "distinct_vendor_count": len({r["vendor_name_raw"] for r in rows}),
        "distinct_data_portal_ids": len({r["data_portal_id"] for r in rows}),
        "amount_total": sum(present, Decimal("0")),
        "amount_present_count": len(present),
        "amount_missing_count": len(rows) - len(present),
        "spaced_slash_count": sum(1 for r in rows if " / " in r["vendor_name_raw"]),
    }


# ---------------------------------------------------------------------------
# Recipient classification — advisory hint only, never proof (Codex round 1)
# ---------------------------------------------------------------------------

def classify_recipient(vendor_name_raw: str) -> dict[str, Any]:
    """Guarded vendor-name handling. Returns the resolution-facing name, an
    optional person side kept ONLY as provenance (never a node), and a GRADED
    `recipient_kind_hint` — advisory, used for review-priority/suppression, never
    as proof of org-ness. The raw name is always preserved upstream.

    Slash split is guarded: only a spaced ``person-like / org-like`` form is
    split; ``CSW/STUBER-STROEH`` (no spaces, org/org) is left whole.
    """
    name = vendor_name_raw.strip()
    if " / " in name:
        left, right = (s.strip() for s in name.split(" / ", 1))
        if _looks_person(left) and _looks_org(right):
            return {
                "recipient_name_resolved": right,
                "person_side": left,
                "recipient_kind_hint": "explicit_org_from_split",
                "classification_basis": "spaced_slash_person_org",
                "heuristic_version": HEURISTIC_VERSION,
            }

    if _looks_org(name):
        token = _ORG_TOKEN_RE.search(name)
        return {
            "recipient_name_resolved": name,
            "person_side": None,
            "recipient_kind_hint": "org_token_present",
            "classification_basis": f"org_token:{token.group(0).lower()}" if token else "org_punct",
            "heuristic_version": HEURISTIC_VERSION,
        }
    if _looks_person(name):
        return {
            "recipient_name_resolved": name,
            "person_side": None,
            "recipient_kind_hint": "person_name_pattern",
            "classification_basis": "two_word_alpha",
            "heuristic_version": HEURISTIC_VERSION,
        }
    return {
        "recipient_name_resolved": name,
        "person_side": None,
        "recipient_kind_hint": "ambiguous",
        "classification_basis": "no_signal",
        "heuristic_version": HEURISTIC_VERSION,
    }


# ---------------------------------------------------------------------------
# Source nodes — County + departments (Government; up the power gradient)
# ---------------------------------------------------------------------------

def build_county_node() -> dict[str, Any]:
    return {
        "id": COUNTY_ID,
        "node_type": "Organization",
        "labels": ["Organization", "Government"],
        "display_label": "County of Marin",
        "properties": {"org_subtype": "Government", "source": "marin_county_open_data"},
    }


def build_department_node(department: str) -> dict[str, Any]:
    # Deterministic display from the id slug (case variants collapse to one node).
    display = slugify(department).replace("-", " ").title()
    return {
        "id": department_id(department),
        "node_type": "Organization",
        "labels": ["Organization", "Government"],
        "display_label": f"{display}, County of Marin",
        "properties": {
            "org_subtype": "Government",
            "parent_org_id": COUNTY_ID,
            "source": "marin_county_open_data",
        },
    }


def build_source_nodes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """County root + one Government node per distinct department, sorted."""
    nodes = [build_county_node()]
    seen: set[str] = set()
    for dept in sorted({r["department"] for r in rows}, key=lambda d: department_id(d)):
        did = department_id(dept)
        if did in seen:
            continue
        seen.add(did)
        nodes.append(build_department_node(dept))
    return nodes


# ---------------------------------------------------------------------------
# MoneyFlow + Record builders
# ---------------------------------------------------------------------------

def build_moneyflow_node(row: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    """One funding-IN MoneyFlow per contract row. The recipient name lives ONLY
    in `recipient_name_raw` — never in any indexed/displayed field. The display
    label carries the amount, never the recipient (ethics: no individual is
    surfaced)."""
    amount = row["amount"]
    props: dict[str, Any] = {
        "flow_type": "delegated_contract",
        "coverage_scope": "marin_county_delegated_contracts",
        "amount_semantics": "delegated_contract_amount",
        "not_full_checkbook": True,
        "not_invoice_payment": True,
        "source": "marin_county_open_data",
        "dataset_id": "rp6f-b7dy",
        "data_portal_id": row["data_portal_id"],
        "department_raw": row["department"],
        "month_and_year": row["month_and_year"],
        "recipient_name_raw": row["vendor_name_raw"],
        "recipient_kind_hint": classification["recipient_kind_hint"],
        "classification_basis": classification["classification_basis"],
        "heuristic_version": classification["heuristic_version"],
    }
    if amount is None:
        props["amount"] = None
        props["amount_missing"] = True
        display_amount = "amount n/a"
    else:
        props["amount"] = str(amount)
        display_amount = f"${amount}"
    if row["contract_number"]:
        props["contract_number"] = row["contract_number"]
    if classification["person_side"]:
        # Provenance/contact text only — never a node, never an indexed field.
        props["contract_contact_person"] = classification["person_side"]
    return {
        "id": moneyflow_id(row["data_portal_id"]),
        "node_type": "MoneyFlow",
        "labels": ["MoneyFlow"],
        "display_label": f"delegated_contract {display_amount}",
        "properties": props,
    }


def build_record_node(row: dict[str, Any]) -> dict[str, Any]:
    """One Record per source row (Data Portal ID), independent of PDF presence.
    Display carries the opaque row uid, never the recipient name."""
    uid = _row_uid(row["data_portal_id"])
    props: dict[str, Any] = {
        "data_portal_id": row["data_portal_id"],
        "source_dataset": "rp6f-b7dy",
        "source": "marin_county_open_data",
    }
    if row["review_contract"]:
        props["review_contract_url"] = row["review_contract"]
    return {
        "id": record_id(row["data_portal_id"]),
        "node_type": "Record",
        "labels": ["Record"],
        "display_label": f"Marin County delegated-contract row {uid}",
        "properties": props,
    }


def build_flow_edges(row: dict[str, Any]) -> list[dict[str, Any]]:
    """FROM_SOURCE (department → MoneyFlow) + EVIDENCED_BY (MoneyFlow → Record).
    NO TO_TARGET — the recipient edge is approved-only (Unit 4)."""
    mid = moneyflow_id(row["data_portal_id"])
    return [
        {
            "source_id": department_id(row["department"]),
            "target_id": mid,
            "relationship_type": "FROM_SOURCE",
            "properties": {},
        },
        {
            "source_id": mid,
            "target_id": record_id(row["data_portal_id"]),
            "relationship_type": "EVIDENCED_BY",
            "properties": {},
        },
    ]


# ---------------------------------------------------------------------------
# Recipient resolution — name-only, review-gated; TO_TARGET is approved-only
# ---------------------------------------------------------------------------

import json  # noqa: E402

from org_resolution import propose_org_resolutions  # noqa: E402

_NAME_SUFFIXES = {"llc", "inc", "incorporated", "corp", "ltd", "co", "lp", "llp"}


def _normalize_recipient_name(name: str) -> str:
    """Group key normalizer: lowercase, punctuation→space, drop trailing
    org-suffix tokens, collapse whitespace. Moderate — variants collapse, and
    the collision report makes every multi-variant collapse auditable."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    tokens = cleaned.split()
    while tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens) or cleaned


def recipient_group_id(name: str) -> str:
    """Stable recipient-group key (NOT a node id — no recipient node exists)."""
    return f"marincontract-recipient-{slugify(_normalize_recipient_name(name))}"


def build_recipient_groups(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group rows by normalized recipient name. Each group tracks its MoneyFlow
    ids, Data Portal ids, raw vendor variants, departments, and hints — the
    evidence an operator needs to approve / split / fail closed. No node."""
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        cls = classify_recipient(row["vendor_name_raw"])
        resolved = cls["recipient_name_resolved"]
        gid = recipient_group_id(resolved)
        g = groups.setdefault(gid, {
            "group_id": gid,
            "resolved_names": set(),
            "raw_variants": set(),
            "moneyflow_ids": set(),
            "data_portal_ids": set(),
            "record_ids": set(),
            "departments": set(),
            "recipient_kind_hints": set(),
        })
        g["resolved_names"].add(resolved)
        g["raw_variants"].add(row["vendor_name_raw"])
        g["moneyflow_ids"].add(moneyflow_id(row["data_portal_id"]))
        g["data_portal_ids"].add(row["data_portal_id"])
        g["record_ids"].add(record_id(row["data_portal_id"]))
        g["departments"].add(row["department"])
        g["recipient_kind_hints"].add(cls["recipient_kind_hint"])
    # Freeze sets to sorted lists + pick a representative display label.
    for g in groups.values():
        g["display_label"] = max(sorted(g["resolved_names"]), key=len)
        for key in ("resolved_names", "raw_variants", "moneyflow_ids",
                    "data_portal_ids", "record_ids", "departments", "recipient_kind_hints"):
            g[key] = sorted(g[key])
    return groups


def collision_report(groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Groups whose rows carry more than one distinct raw vendor string — the
    auditable record of name collapse (Codex: never silent)."""
    return [
        {"group_id": g["group_id"], "raw_variants": g["raw_variants"],
         "data_portal_ids": g["data_portal_ids"]}
        for g in sorted(groups.values(), key=lambda g: g["group_id"])
        if len(g["raw_variants"]) > 1
    ]


def resolve_recipients(
    groups: dict[str, dict[str, Any]], existing_orgs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Run the shared resolver over recipient-group refs. These carry NO identity
    key (names only), so the resolver's SAME_AS list MUST come back empty — assert
    it. Returns the queued ResolutionCandidate rows (name-signal only)."""
    refs = [
        {"id": g["group_id"], "display_label": g["display_label"],
         "evidence_record_ids": g["record_ids"]}
        for g in sorted(groups.values(), key=lambda g: g["group_id"])
    ]
    same_as, candidates = propose_org_resolutions(refs, existing_orgs)
    if same_as:
        raise ValueError(
            f"resolver returned {len(same_as)} SAME_AS edge(s); County vendors "
            f"carry no identity key, so M3 must auto-merge nothing"
        )
    return candidates


def load_approved_resolutions(
    path: Path, *, emitted_group_ids: set[str], existing_org_ids: set[str]
) -> list[dict[str, Any]]:
    """Operator-approved (recipient-group → existing Organization) resolutions.

    Re-implemented for M3's FACT-ref semantics (NOT M2d's org-to-org loader):
    `subject_ref` must be a recipient group emitted THIS run, `candidate_ref` an
    id present in --existing-orgs. status != approved or a stale ref → fail loud;
    byte-identical duplicates dedupe."""
    approved: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        row = json.loads(raw)
        if row.get("status") != "approved":
            raise ValueError(f"approved line {lineno}: status is {row.get('status')!r}, "
                             f"expected 'approved'")
        subject, candidate = row.get("subject_ref"), row.get("candidate_ref")
        if subject not in emitted_group_ids:
            raise ValueError(f"approved line {lineno}: subject_ref is not a recipient "
                             f"group emitted this run")
        if candidate not in existing_org_ids:
            raise ValueError(f"approved line {lineno}: candidate_ref is not an id in "
                             f"--existing-orgs")
        key = (subject, candidate)
        if key in seen:
            continue
        seen.add(key)
        approved.append({"subject_ref": subject, "candidate_ref": candidate})
    return approved


def build_to_target_edges(
    approved: list[dict[str, Any]], groups: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Approved-only: every MoneyFlow in an approved recipient group gets a
    TO_TARGET edge to the operator-confirmed existing Organization."""
    edges: list[dict[str, Any]] = []
    for row in approved:
        group = groups[row["subject_ref"]]
        for mid in group["moneyflow_ids"]:
            edges.append({
                "source_id": mid,
                "target_id": row["candidate_ref"],
                "relationship_type": "TO_TARGET",
                "properties": {},
            })
    return edges


# ---------------------------------------------------------------------------
# Orchestration + coverage + CLI
# ---------------------------------------------------------------------------

_SIDECAR_NAME = "resolution-candidates-marincounty-contracts.jsonl"
_COVERAGE_NAME = "marincounty-contracts-coverage.json"
_COLLISION_NAME = "marincounty-contracts-name-collisions.json"
CAPTURE_DATE = "2026-06-10"  # the staging capture (no Date.now in pure code)


def build_coverage(
    rows: list[dict[str, Any]],
    groups: dict[str, dict[str, Any]],
    *,
    queued_candidate_count: int,
    approved_group_count: int,
) -> dict[str, Any]:
    """Coverage-honesty object — machine-readable that this is a SLICE of County
    spend, never the full checkbook. amount_total is an exact Decimal string."""
    prof = source_profile(rows)
    return {
        "dataset": {
            "dataset_id": "rp6f-b7dy",
            "coverage_scope": "marin_county_delegated_contracts",
            "amount_semantics": "delegated_contract_amount",
            "not_full_checkbook": True,
            "not_invoice_payment": True,
            "source": "marin_county_open_data",
            "capture_date": CAPTURE_DATE,
        },
        "rows": {
            "captured": prof["row_count"],
            "amount_present": prof["amount_present_count"],
            "amount_missing": prof["amount_missing_count"],
        },
        "amount_total": str(prof["amount_total"]),
        "departments": len({department_id(r["department"]) for r in rows}),
        "recipients": {
            "groups": len(groups),
            "with_name_variants": sum(1 for g in groups.values() if len(g["raw_variants"]) > 1),
        },
        "resolution": {
            "queued_candidates": queued_candidate_count,
            "approved_groups": approved_group_count,
            "unresolved_groups": len(groups) - approved_group_count,
        },
    }


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def run(
    *,
    input_csv: Path,
    out_dir: Path,
    review_dir: Path,
    existing_orgs: list[dict[str, Any]] | None = None,
    approved_path: Path | None = None,
    write_outputs: bool = True,
) -> dict[str, Any]:
    """Ingest the delegated-contracts CSV → source/MoneyFlow/Record nodes + the
    funding spine, recipient resolution candidates, and approved-only TO_TARGET.
    Pure: never fetches, never touches a DB. Ties out to the exact source total."""
    existing_orgs = existing_orgs or []
    rows = parse_contract_rows(input_csv)

    nodes: list[dict[str, Any]] = list(build_source_nodes(rows))
    edges: list[dict[str, Any]] = []
    for row in rows:
        cls = classify_recipient(row["vendor_name_raw"])
        nodes.append(build_moneyflow_node(row, cls))
        nodes.append(build_record_node(row))
        edges.extend(build_flow_edges(row))

    groups = build_recipient_groups(rows)
    candidates = resolve_recipients(groups, existing_orgs)

    existing_org_ids = {o["id"] for o in existing_orgs}
    approved: list[dict[str, Any]] = []
    if approved_path is not None:
        approved = load_approved_resolutions(
            approved_path, emitted_group_ids=set(groups), existing_org_ids=existing_org_ids)
    approved_keys = {(a["subject_ref"], a["candidate_ref"]) for a in approved}
    approved_group_ids = {a["subject_ref"] for a in approved}

    edges.extend(build_to_target_edges(approved, groups))

    queued = [c for c in candidates if (c["subject_ref"], c["candidate_ref"]) not in approved_keys]
    collisions = collision_report(groups)
    coverage = build_coverage(
        rows, groups,
        queued_candidate_count=len(queued),
        approved_group_count=len(approved_group_ids))

    if write_outputs:
        _write_jsonl(sorted(nodes, key=lambda n: n["id"]), out_dir / "nodes.jsonl")
        _write_jsonl(
            sorted(edges, key=lambda e: (e["source_id"], e["relationship_type"], e["target_id"])),
            out_dir / "edges.jsonl")
        (out_dir / _COVERAGE_NAME).write_text(
            json.dumps(coverage, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (out_dir / _COLLISION_NAME).write_text(
            json.dumps(collisions, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        review_dir.mkdir(parents=True, exist_ok=True)
        _write_jsonl(sorted(queued, key=lambda c: json.dumps(c, sort_keys=True)),
                     review_dir / _SIDECAR_NAME)

    return {
        "nodes": nodes, "edges": edges, "coverage": coverage,
        "candidates": candidates, "queued": queued, "groups": groups,
        "collisions": collisions,
    }


def _load_existing_orgs(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("organizations", [])


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ingest County of Marin delegated contracts (M3 leg-1).")
    parser.add_argument("--input", required=True, type=Path, help="delegated-contracts CSV")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--review-dir", type=Path, default=Path("data/review"))
    parser.add_argument("--existing-orgs", type=Path, default=None)
    parser.add_argument("--approved-resolutions", type=Path, default=None)
    parser.add_argument("--load", action="store_true", help="operator-gated: load into Neo4j")
    args = parser.parse_args(argv)

    result = run(
        input_csv=args.input, out_dir=args.out_dir, review_dir=args.review_dir,
        existing_orgs=_load_existing_orgs(args.existing_orgs),
        approved_path=args.approved_resolutions)

    cov = result["coverage"]
    print(
        f"marin county delegated contracts: {cov['rows']['captured']} rows / "
        f"${cov['amount_total']} ({cov['dataset']['coverage_scope']}, NOT full checkbook); "
        f"{cov['departments']} departments; {cov['recipients']['groups']} recipient groups; "
        f"resolution queued={cov['resolution']['queued_candidates']} "
        f"approved={cov['resolution']['approved_groups']} "
        f"unresolved={cov['resolution']['unresolved_groups']}")

    if args.load:  # pragma: no cover - operator-only
        import importlib
        importlib.import_module("load_neo4j_v2").load_bundle(args.out_dir)  # type: ignore
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
