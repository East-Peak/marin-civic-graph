"""enrich_org_keys.py — IRS EO-BMF parser → keyed registry org refs (Lane 1, Unit 1).

Open Marin Identity Enrichment, Lane 1 (EIN). The operator stages a Marin-filtered
slice of the IRS Exempt-Organization Business Master File (a public bulk CSV of
every IRS-recognized exempt org: EIN, NAME, CITY, STATE, SUBSECTION, NTEE_CD).
This module parses that staged CSV into registry org refs the shared resolver
(`org_resolution.propose_org_resolutions`) consumes — a LIGHTER bulk-key source
than the full-990-XML path in `ingest_990.py`; the two coexist and feed the same
ledger. There is NO fetch code here: the download is the operator step (runbook
in the CLI module — Unit 4).

The teeth (Codex round 1):

- **EIN must be EXACTLY 9 digits** after stripping non-digits, or the row is
  skipped with a logged reason — never a fabricated key. The resolver keys on any
  surviving digits, so a `123` that slipped through would manufacture a false
  merge target; it is dropped to the coverage report instead.
- **The subsection subtype is a SEPARATE field.** Identity Control A's
  `entity_class` is entity KIND (`organization` vs `committee`) and the egress
  gate compares it for equality; a registry subtype placed there would fail
  class-equality against an existing `organization` node and silently demote the
  deterministic EIN merge. So every ref keeps `entity_class: "organization"` and
  the two-digit `SUBSECTION` lands in `irs_subsection_class` (the false-friend
  signal that separates a c6 trade association from its c3 scholarship fund, and
  feeds the later dedup milestone).
- **Same-EIN rows are conflict-safe.** Byte-identical duplicate rows for one EIN
  dedupe to a single ref; rows that share an EIN but disagree on name/subsection
  are NOT first-wins — they emit a `bmf_row_conflict` and that EIN is WITHHELD
  from deterministic resolution (a contradiction the operator must see, never a
  silent pick).

Pure module: CSV in, refs/skips/conflicts out. No network, no DB.

Operator runbook (the download is the OPERATOR step — this module never fetches):

  1. Download the IRS Exempt-Organization Business Master File. The full national
     file or the per-region extract is published at
     https://www.irs.gov/charities-non-profits/exempt-organizations-business-master-file-extract
     (region 4 = CA: `eo_ca.csv`).
  2. Filter to Marin (by CITY ∈ the Marin city list, or by ZIP prefix) and stage
     the slice at `data/raw/irs-bmf/eo_marin.csv` (gitignored).
  3. Run this module's CLI to parse + resolve + write the review queue + coverage:
       python scripts/enrich_org_keys.py \\
         --bmf data/raw/irs-bmf/eo_marin.csv \\
         --existing-orgs data/exports/existing-orgs.json \\
         --review-dir data/review
  4. Review the queued name candidates against the hard EIN + registry locale +
     subtype; an approval writes an `approved` ledger assertion + draws the
     audited SAME_AS (Identity Control A). The enriched live export
     (`export_existing_orgs.py`, operator-gated, needs NEO4J_* creds) then
     SURFACES the attached keys — this module never touches the database.

  (ProPublica's per-org Nonprofit Explorer API — https://projects.propublica.org/
  nonprofits/api/v2/organizations/<EIN>.json — is the documented alternate
  single-org lookup; same staged-CSV contract, also an operator step.)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

from identity_egress_gate import POLICY_VERSION, gate_ingestor_same_as  # noqa: E402
from identity_ledger import make_assertion  # noqa: E402
from identity_resolution_adapter import (  # noqa: E402
    normalize_resolution_candidate_for_artifact,
)
from org_resolution import propose_org_resolutions  # noqa: E402

# This lane's source-system stamp + the registry id key-prefix it mints.
SOURCE_SYSTEM = "irs_bmf"

# Two-digit IRS subsection code → subtype class (Predeclared 2). A SEPARATE
# signal from Identity Control A's `entity_class`; never feeds the class gate.
_SUBSECTION_CLASS: dict[str, str] = {
    "03": "charity",
    "04": "social_welfare",
    "05": "labor_ag",
    "06": "trade_association",
    "07": "social_club",
    "19": "veterans",
}

# The BMF columns this lane reads. Extra columns in the staged CSV are ignored,
# so the same parser works on the full operator file and the fixture slice.
_REQUIRED_COLUMNS = ("EIN", "NAME", "CITY", "STATE", "SUBSECTION")


def irs_subsection_class(code: Any) -> str:
    """Map a BMF subsection code to its subtype class.

    Codes are two-digit strings (`"03"`, `"06"`); a stray un-padded code is
    zero-padded first. An unmapped or blank/None code → `"nonprofit_other"`
    (never blank — Predeclared 2 / the no-fabrication guardrail)."""
    if code is None:
        return "nonprofit_other"
    digits = re.sub(r"\D", "", str(code))
    if not digits:
        return "nonprofit_other"
    return _SUBSECTION_CLASS.get(digits.zfill(2), "nonprofit_other")


def _strict_ein(value: Any) -> str | None:
    """Digits only; return ONLY when exactly 9 digits survive, else None.

    Stricter than the resolver's `_normalize_ein` (which keeps any digits) — a
    registry key MUST be a full EIN or nothing, never a partial that the resolver
    would treat as a real identity."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) == 9 else None


def _titlecase_allcaps(value: str) -> str:
    """Title-case an ALL-CAPS source string for operator display; pass through
    mixed case unchanged (matches `ingest_990.title_if_allcaps`)."""
    return value.title() if value.isupper() else value


def bmf_org_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build one keyed registry org ref from a row whose EIN is already validated.

    `entity_class` is the constant `"organization"` (the subtype rides in
    `irs_subsection_class`). `evidence_record_ids` points at the row's
    `record-bmf-<ein>` provenance id (the field name the resolver + ledger expect,
    NOT `evidence`/`evidence_refs`)."""
    ein = _strict_ein(row["EIN"])
    if ein is None:  # defensive: callers validate first
        raise ValueError(f"bmf_org_ref called with non-9-digit EIN: {row['EIN']!r}")
    name = (row.get("NAME") or "").strip()
    city = (row.get("CITY") or "").strip()
    return {
        "id": f"org-bmf-ein-{ein}",
        "display_label": _titlecase_allcaps(name),
        "ein": ein,
        "entity_class": "organization",
        "irs_subsection_class": irs_subsection_class(row.get("SUBSECTION")),
        "city": _titlecase_allcaps(city),
        "state": (row.get("STATE") or "").strip().upper(),
        "evidence_record_ids": [f"record-bmf-{ein}"],
    }


def parse_bmf_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate BMF rows into refs / skipped / conflicts.

    Returns ``{"refs": [...], "skipped": [...], "conflicts": [...]}``:
    - ``refs`` — one ref per distinct, valid, non-conflicting EIN (sorted by EIN).
    - ``skipped`` — rows whose EIN is not exactly 9 digits
      (``{"reason": "ein_not_9_digits", "ein_raw", "name"}``).
    - ``conflicts`` — EINs with disagreeing name/subsection rows
      (``{"ein", "reason": "bmf_row_conflict", "variants": [...]}``); the EIN is
      WITHHELD from refs.

    Byte-identical rows for one EIN collapse to a single ref; identity here is the
    (display_label, irs_subsection_class) pair — the name/subsection the resolver
    and the dedup false-friend guard care about."""
    skipped: list[dict[str, Any]] = []
    by_ein: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        ein = _strict_ein(row.get("EIN"))
        if ein is None:
            skipped.append({
                "reason": "ein_not_9_digits",
                "ein_raw": str(row.get("EIN") or "").strip(),
                "name": (row.get("NAME") or "").strip(),
            })
            continue
        by_ein.setdefault(ein, []).append(bmf_org_ref(row))

    refs: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for ein in sorted(by_ein):
        variants = by_ein[ein]
        # Identity for dedup/conflict = (display_label, irs_subsection_class).
        distinct = {(v["display_label"], v["irs_subsection_class"]): v for v in variants}
        if len(distinct) == 1:
            refs.append(next(iter(distinct.values())))
        else:
            conflicts.append({
                "ein": ein,
                "reason": "bmf_row_conflict",
                "variants": [
                    {"display_label": dl, "irs_subsection_class": sub}
                    for (dl, sub) in sorted(distinct)
                ],
            })

    return {"refs": refs, "skipped": skipped, "conflicts": conflicts}


def parse_bmf_csv(path: str | Path) -> dict[str, Any]:
    """Parse an operator-staged BMF CSV (or fixture slice) into the
    refs/skipped/conflicts result of :func:`parse_bmf_rows`.

    Requires the columns this lane reads; a missing required column fails loud
    (never a silent all-skip)."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in _REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"BMF CSV {path} missing required columns: {missing}")
        return parse_bmf_rows(list(reader))


# ---------------------------------------------------------------------------
# Unit 2 — resolution wiring (Predeclared 3)
# ---------------------------------------------------------------------------

# The BMF registry-evidence fields surfaced onto a review candidate (so the
# operator approves against the hard key + locale + subtype, never a bare name).
# City/state are CORROBORATION on the review packet, NEVER an auto-approver.
_REGISTRY_EVIDENCE_FIELDS = ("city", "state", "irs_subsection_class", "ein")


def enrich_review_candidate(
    candidate: Mapping[str, Any], registry_by_id: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    """A resolver candidate → a review artifact: `confidence` renamed to
    `signal_strength` (a signal, never a probability) plus the registry locale,
    subtype, and EIN attached as REVIEW EVIDENCE under `registry_*` keys.

    The registry ref is the resolver's `subject_ref` (the BMF org is the "new"
    side of `propose_org_resolutions`). A demoted relationship candidate (no
    `confidence`) passes through the rename untouched."""
    out = normalize_resolution_candidate_for_artifact(dict(candidate))
    registry = registry_by_id.get(candidate.get("subject_ref"))
    if registry is not None:
        for field in _REGISTRY_EVIDENCE_FIELDS:
            if registry.get(field) is not None:
                out[f"registry_{field}"] = registry[field]
    return out


def resolve_registry_refs(
    registry_refs: list[dict[str, Any]],
    existing_orgs: list[dict[str, Any]],
    *,
    policy_version: str = POLICY_VERSION,
    source_system: str = SOURCE_SYSTEM,
) -> dict[str, Any]:
    """Run staged registry refs through the shared resolver + Identity Control A.

    Returns ``{"same_as_edges", "assertions", "review_candidates"}``:
    - a matching EIN/UEI on BOTH sides → a `deterministic` ledger assertion and a
      gated SAME_AS edge stamped with its id (the ONE permitted auto-merge);
    - everything else (name signals, identity-conflict, demoted relationship
      semantics) → a queued review candidate enriched with the registry evidence.

    Name similarity alone NEVER merges (the resolver's contract); city is only
    corroboration on the review packet."""
    same_as, candidates = propose_org_resolutions(
        registry_refs, existing_orgs, identity_keys=("ein", "uei")
    )
    gated_same_as, assertions, demoted = gate_ingestor_same_as(
        same_as, registry_refs, existing_orgs,
        source_system=source_system, policy_version=policy_version,
    )
    registry_by_id = {r["id"]: r for r in registry_refs}
    review_candidates = [
        enrich_review_candidate(c, registry_by_id) for c in (*candidates, *demoted)
    ]
    return {
        "same_as_edges": gated_same_as,
        "assertions": assertions,
        "review_candidates": review_candidates,
    }


def assertion_for_approved_candidate(
    candidate: Mapping[str, Any],
    *,
    subject: dict[str, Any],
    target: dict[str, Any],
    basis: str,
    reviewer: str,
    decided_at: str,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    """Write the ledger assertion for an operator-APPROVED candidate.

    The pinned evidence mapping (Codex r2): the candidate carries
    `evidence_record_ids` (the resolver's field); the ledger API takes
    `evidence_refs` — map one to the other, never drop the evidence."""
    return make_assertion(
        subject_ref=candidate["subject_ref"],
        target_ref=candidate["candidate_ref"],
        status="approved",
        basis=basis,
        subject=subject,
        target=target,
        reviewer=reviewer,
        decided_at=decided_at,
        policy_version=policy_version,
        evidence_refs=list(candidate.get("evidence_record_ids", [])),
    )


# ---------------------------------------------------------------------------
# Unit 4 — coverage report + CLI (Predeclared 7, 9)
# ---------------------------------------------------------------------------

# The honest scope of the BMF key source (Codex r1 minor — never "every nonprofit").
SOURCE_LIMITATION = (
    "IRS-recognized exempt orgs in the staged CA/Marin-filtered BMF slice; "
    "address-based, not operations"
)


def build_coverage_report(
    parse_result: Mapping[str, Any],
    resolve_result: Mapping[str, Any],
    existing_orgs: list[dict[str, Any]],
    *,
    policy_version: str = POLICY_VERSION,
    enriched_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The coverage report — the keyless tail is PUBLISHED, never implied resolved.

    Counts BMF orgs keyed / rows skipped (bad EIN) / `bmf_row_conflict`,
    EIN-deterministic matches / name candidates queued, the existing-orgs total +
    keyless tail, and (when a live enrichment ran) the `identity_key_conflict`
    count — all stamped with `policy_version` and the source-limitation note."""
    same_as = resolve_result.get("same_as_edges", [])
    review = resolve_result.get("review_candidates", [])
    matched_existing = {e.get("target_id") for e in same_as}
    keyless = [
        o for o in existing_orgs
        if o.get("id") not in matched_existing and not o.get("ein") and not o.get("uei")
    ]
    enriched = enriched_refs or []
    return {
        "policy_version": policy_version,
        "source_limitation": SOURCE_LIMITATION,
        "bmf": {
            "registry_orgs_keyed": len(parse_result.get("refs", [])),
            "rows_skipped_ein_not_9_digits": len(parse_result.get("skipped", [])),
            "bmf_row_conflict": len(parse_result.get("conflicts", [])),
        },
        "resolution": {
            "ein_deterministic_matches": len(same_as),
            "name_candidates_queued": len(review),
        },
        "existing_orgs": {
            "total": len(existing_orgs),
            "keyless_tail": len(keyless),
        },
        "enrichment": {
            "identity_key_conflict": sum(1 for r in enriched if r.get("identity_key_conflict")),
            "orgs_with_surfaced_key": sum(1 for r in enriched if r.get("ein") or r.get("uei")),
        },
    }


def _load_existing_orgs(path: str | Path) -> list[dict[str, Any]]:
    """Operator-supplied existing-org export: a JSON array of resolver refs."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"existing-orgs file must be a JSON array: {path}")
    return data


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Parse a staged BMF CSV → resolve against an existing-orgs export → write the
    review sidecar + coverage report. Touches NO database — the enriched live
    export (`export_existing_orgs.py`) is the operator step, never run here."""
    parser = argparse.ArgumentParser(
        description=(
            "Identity Enrichment Lane 1 (EIN): parse a Marin-filtered IRS EO-BMF "
            "CSV into keyed registry refs, resolve them against an existing-orgs "
            "export, and write the review queue + coverage report. No network, no "
            "database (see the module docstring for the operator download runbook)."
        )
    )
    parser.add_argument("--bmf", required=True, help="Operator-staged Marin EO-BMF CSV.")
    parser.add_argument("--existing-orgs", required=True, help="JSON array of existing org refs.")
    parser.add_argument("--review-dir", required=True, type=Path, help="Output dir for review queue + coverage report.")
    args = parser.parse_args(argv)

    parse = parse_bmf_csv(args.bmf)
    existing = _load_existing_orgs(args.existing_orgs)
    resolve = resolve_registry_refs(parse["refs"], existing)
    report = build_coverage_report(parse, resolve, existing)

    review_dir: Path = args.review_dir
    review_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(review_dir / "resolution-candidates-bmf.jsonl", resolve["review_candidates"])
    (review_dir / "coverage-bmf.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        f"BMF: {report['bmf']['registry_orgs_keyed']} keyed, "
        f"{report['bmf']['rows_skipped_ein_not_9_digits']} skipped, "
        f"{report['bmf']['bmf_row_conflict']} conflicts | "
        f"resolution: {report['resolution']['ein_deterministic_matches']} EIN-deterministic, "
        f"{report['resolution']['name_candidates_queued']} name-queued | "
        f"existing: {report['existing_orgs']['keyless_tail']}/{report['existing_orgs']['total']} keyless"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
