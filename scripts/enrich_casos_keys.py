"""enrich_casos_keys.py — CA Secretary-of-State entity-number enrichment (Lane 2).

Open Marin Identity Enrichment, Lane 2 (`sos_id`). Attaches the California SOS
business entity number to existing FOR-PROFIT vendor `Organization` nodes — the
for-profit analog of Lane 1's EIN (there is no public for-profit EIN source). The
operator stages the CA SOS "BE Master Unload" (`data/raw/ca-sos/Filings.csv`,
9.44M entities, `*|*`-delimited); this module STREAMS it (never materializes the
3.6 GB file) into keyed registry org refs for the shared resolver.

Reuses Lane 1's resolver/ledger/gate/export. THREE things are new:
  1. `sos_id` — a new identity key, validated against the shared resolver's
     immutable `KEY_NORMALIZERS` via the idempotent, non-clobbering
     `register_sos_id_normalizer()` shim (so `org_resolution.py` stays
     byte-identical and import-order coverage remains explicit).
  2. Scale + recall — a streaming significant-token pre-block (see
     `block_casos_against_existing`, a later unit) reduces 9.44M rows to a tiny
     candidate pool before any resolution.
  3. A redaction gate — for-profit registry records carry natural-person data
     (registered-agent / officer names + home addresses) that is NEVER published.
     This parser already reads ONLY the entity-level whitelist into refs.

Operator runbook (the download is the OPERATOR step — this module never fetches):
  1. Sign in at https://bizfileonline.sos.ca.gov/ → Data Requests → New Data
     Request → "BE Bulk Order - Master Unload of Data" ($100, full snapshot).
  2. Accept the in-workflow Terms; download `Data.zip`; unzip.
  3. Stage `Filings.csv` (+ optional `Agents.csv` for the redaction signal) under
     `data/raw/ca-sos/` (gitignored). The file is `*|*`-delimited (NOT comma).
  4. Run this lane's CLI (a later unit) to parse → block → resolve → coverage.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

from org_resolution import KEY_NORMALIZERS, _normalize_name, propose_org_resolutions  # noqa: E402
from identity_key_normalizers import _normalize_sos_id  # noqa: E402  (shared; Goal 0 re-export)
from identity_egress_gate import POLICY_VERSION, gate_ingestor_same_as  # noqa: E402
from identity_ledger import make_assertion  # noqa: E402
from identity_resolution_adapter import (  # noqa: E402
    normalize_resolution_candidate_for_artifact,
)

# This lane's source-system stamp + the registry id key-prefix it mints.
SOURCE_SYSTEM = "ca_sos"

# The ONLY columns the parser reads into a ref — the entity-level whitelist. The
# street/ZIP/mailing columns the staged file carries are NEVER read (redaction at
# source); the natural-person Agents/Principals files are never read here at all.
_WHITELIST_COLUMNS = {
    "ENTITY_NAME": "display_label",
    "ENTITY_NUM": "_entity_num",
    "INITIAL_FILING_DATE": "formation_date",
    "ENTITY_STATUS": "entity_status",
    "ENTITY_TYPE": "entity_type",
    "PRINCIPAL_CITY": "principal_city",
    "PRINCIPAL_STATE": "principal_state",
}

DELIMITER = "*|*"


# _normalize_sos_id is re-exported from identity_key_normalizers (Goal 0 — the
# single shared home for the key normalizers; imported above). register_sos_id_normalizer
# validates that shared callable against KEY_NORMALIZERS.


def register_sos_id_normalizer() -> None:
    """Validate `_normalize_sos_id` under `"sos_id"` in the shared immutable
    `KEY_NORMALIZERS`. This is a no-op shim that preserves the old clobber-
    refusal contract: missing or foreign registrations fail loud rather than
    silently changing resolver behavior."""
    existing = KEY_NORMALIZERS.get("sos_id")
    if existing is not _normalize_sos_id:
        raise RuntimeError(
            "KEY_NORMALIZERS['sos_id'] is not registered to the expected "
            f"callable ({existing!r}); refusing to clobber it"
        )


def entity_num_prefix_shape(normalized: str) -> str:
    """Coverage-honesty classifier for a normalized entity number."""
    if normalized.isdigit():
        return "digits"
    if normalized[:1] == "B" and normalized[1:].isdigit():
        return "b_prefixed"
    return "alpha_other"


def _clean_name(raw: str) -> str:
    """Strip the leading `' ` quote artifact + surrounding quotes/space the SOS
    Master Unload puts on ENTITY_NAME; title-case the all-caps source for display."""
    name = raw.strip().lstrip("'").strip().strip("'").strip()
    return name.title() if name.isupper() else name


def parse_casos_filings(
    lines: Iterable[str],
) -> Iterator[tuple[dict[str, Any] | None, str | None]]:
    """STREAM the `*|*`-delimited Filings export → `(ref, skip_reason)` per row.

    Lazy by contract — consumes an iterable of lines and never materializes the
    file (no `.read()`/`list(reader)`). Reads ONLY the entity-level whitelist
    columns into each ref (the street/ZIP columns are never touched). A row with a
    missing/non-normalizable ENTITY_NUM yields `(None, "entity_num_missing")`."""
    header: dict[str, int] | None = None
    for line in lines:
        fields = line.rstrip("\n").split(DELIMITER)
        if header is None:
            header = {name: i for i, name in enumerate(fields)}
            continue

        def cell(col: str) -> str:
            idx = header.get(col)
            return fields[idx].strip() if idx is not None and idx < len(fields) else ""

        sos_id = _normalize_sos_id(cell("ENTITY_NUM"))
        if sos_id is None:
            yield None, "entity_num_missing"
            continue
        ref = {
            "id": f"org-casos-{sos_id}",
            "display_label": _clean_name(cell("ENTITY_NAME")),
            "sos_id": sos_id,
            "entity_class": "organization",
            "entity_status": cell("ENTITY_STATUS"),
            "entity_type": cell("ENTITY_TYPE"),
            "formation_date": cell("INITIAL_FILING_DATE"),
            "principal_city": _clean_name(cell("PRINCIPAL_CITY")),
            "principal_state": cell("PRINCIPAL_STATE").upper(),
            "evidence_record_ids": [f"record-casos-{sos_id}"],
        }
        yield ref, None


# Fields whose disagreement across rows of the same ENTITY_NUM is a conflict.
_CONFLICT_FIELDS = ("display_label", "entity_type")


def dedupe_casos_refs(
    refs: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collapse byte-identical duplicate-ENTITY_NUM refs to one; withhold numbers
    whose rows disagree on name/type (→ `casos_row_conflict`).

    Operates on the BOUNDED matched set (the blocking pool), never the full file —
    so it is memory-safe despite holding by-number groups."""
    by_num: dict[str, list[dict[str, Any]]] = {}
    for ref in refs:
        by_num.setdefault(ref["sos_id"], []).append(ref)

    deduped: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for sos_id in sorted(by_num):
        group = by_num[sos_id]
        variants = {tuple(r.get(f) for f in _CONFLICT_FIELDS): r for r in group}
        if len(variants) == 1:
            deduped.append(next(iter(variants.values())))
        else:
            conflicts.append({
                "sos_id": sos_id,
                "reason": "casos_row_conflict",
                "variants": [
                    {"display_label": dl, "entity_type": et}
                    for (dl, et) in sorted(variants)
                ],
            })
    return deduped, conflicts


# ---------------------------------------------------------------------------
# Unit 2 — significant-token pre-block + union candidate generation (Predeclared 3)
# ---------------------------------------------------------------------------

# Corporate stopwords dropped before significant-token blocking — generic tokens
# that carry no disambiguating signal (so the block keys on "ghilotti"/"miller",
# not "company"/"group").
_CORPORATE_STOPWORDS = frozenset({
    "inc", "incorporated", "llc", "corp", "corporation", "company", "co",
    "group", "lp", "llp", "the", "and", "of", "jv", "fund",
})

# token-overlap candidate strength (review-only; ranks below the resolver's
# normalized-name-exact 0.9 / difflib>=0.85 candidates). Never an auto-approver.
_TOKEN_OVERLAP_STRENGTH = 0.5

# entity-status rank for the deterministic cap sort (Active first).
_STATUS_RANK = {"active": 0}


def significant_tokens(name: str) -> set[str]:
    """`_normalize_name` tokens minus the corporate stopwords — the blocking key."""
    return {t for t in _normalize_name(name).split() if t not in _CORPORATE_STOPWORDS}


def _status_rank(status: str) -> int:
    s = (status or "").strip().lower()
    if s in _STATUS_RANK:
        return _STATUS_RANK[s]
    if s.startswith("suspended"):
        return 1
    if s.startswith("terminated") or s.startswith("converted"):
        return 2
    return 3


def _resolver_candidates(refs, existing):
    """Resolver path: normalized-name-exact / difflib>=0.85 → signal_strength
    candidates (the resolver emits `confidence`; the adapter renames it)."""
    _edges, raw = propose_org_resolutions(refs, [existing], identity_keys=("sos_id",))
    out = []
    for cand in raw:
        c = normalize_resolution_candidate_for_artifact(cand)  # confidence → signal_strength
        out.append(c)
    return out


def _token_overlap(a: set[str], b: set[str]) -> bool:
    """A review-worthy overlap: >=2 shared significant tokens.

    A single shared token — even via a subset — FLOODS on common tokens
    (`construction` 225k rows, `management` 373k) and burns the per-existing cap
    with junk (empirically confirmed against the real file), so it is excluded;
    a single-significant-token existing org relies on the resolver's exact/0.85
    path. All real for-profit cases share >=2 tokens or are resolver matches."""
    return len(a & b) >= 2


def block_casos_against_existing(
    filings_lines: Iterable[str],
    existing_orgs: list[dict[str, Any]],
    *,
    cap: int = 25,
) -> dict[str, Any]:
    """Stream the Filings export, pre-block on significant tokens, and generate the
    UNION of resolver + token-overlap queued candidates per existing org (capped).

    Memory-safe: only SOS refs that share a significant token with some existing
    org are held (the matched buckets), never the full file."""
    existing_tokens = {e["id"]: significant_tokens(e["display_label"]) for e in existing_orgs}
    existing_by_id = {e["id"]: e for e in existing_orgs}
    token_index: dict[str, list[str]] = {}
    for eid, toks in existing_tokens.items():
        for t in toks:
            token_index.setdefault(t, []).append(eid)

    # Stream → per-existing buckets of matched SOS rows (a LIST per existing: each
    # matched row is added once, so a same-number CONFLICT pair lands as two refs
    # and `dedupe_casos_refs` can see/flag it — keying by sos_id here would drop
    # the second conflict row before detection).
    buckets: dict[str, list[dict[str, Any]]] = {e["id"]: [] for e in existing_orgs}
    stats: dict[str, Any] = {
        "filings_rows_scanned": 0,
        "prefix_shapes": {},
        "skipped": {},
    }
    for ref, skip in parse_casos_filings(filings_lines):
        stats["filings_rows_scanned"] += 1
        if ref is None:
            stats["skipped"][skip] = stats["skipped"].get(skip, 0) + 1
            continue
        shape = entity_num_prefix_shape(ref["sos_id"])
        stats["prefix_shapes"][shape] = stats["prefix_shapes"].get(shape, 0) + 1
        sos_toks = significant_tokens(ref["display_label"])
        matched: set[str] = set()
        for t in sos_toks:
            matched.update(token_index.get(t, ()))
        for eid in matched:
            buckets[eid].append(ref)

    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    capped: list[dict[str, Any]] = []
    pool_pairs = 0

    for eid, bucket in buckets.items():
        if not bucket:
            continue
        existing = existing_by_id[eid]
        refs, bucket_conflicts = dedupe_casos_refs(bucket)
        conflicts.extend(bucket_conflicts)
        pool_pairs += len(refs)

        # (a) resolver path
        resolver_cands = _resolver_candidates(refs, existing)
        resolved_sos = set()
        merged: list[dict[str, Any]] = []
        ref_by_id = {r["id"]: r for r in refs}
        for c in resolver_cands:
            ref = ref_by_id.get(c["subject_ref"])
            if ref is None:
                continue
            resolved_sos.add(ref["sos_id"])
            merged.append({
                **c,
                "sos_id": ref["sos_id"],
                "status": "queued",
                "entity_status": ref["entity_status"],
            })
        # (b) token-overlap path — only for refs the resolver did not already pick
        e_toks = existing_tokens[eid]
        for ref in refs:
            if ref["sos_id"] in resolved_sos:
                continue
            if _token_overlap(significant_tokens(ref["display_label"]), e_toks):
                merged.append({
                    "subject_ref": ref["id"],
                    "candidate_ref": eid,
                    "sos_id": ref["sos_id"],
                    "signals": ["significant_token_overlap"],
                    "signal_strength": _TOKEN_OVERLAP_STRENGTH,
                    "status": "queued",
                    "entity_status": ref["entity_status"],
                    "evidence_record_ids": list(ref["evidence_record_ids"]),
                })

        # attach the SOS review evidence (status/type/city) onto each candidate
        merged = [enrich_casos_candidate(c, ref_by_id.get(c["subject_ref"], {})) for c in merged]
        # deterministic cap sort: exact-name matches FIRST (the resolver gives a flat
        # 0.9 to normalized_name_exact, which a false friend's difflib can exceed —
        # e.g. "X Construction Company" at 0.91 outranking the true exact match), then
        # (-signal_strength, status_rank, sos_id).
        def _sort_key(c):
            is_exact = "normalized_name_exact" in c.get("signals", [])
            return (not is_exact, -c["signal_strength"], _status_rank(c["entity_status"]), c["sos_id"])
        merged.sort(key=_sort_key)
        if len(merged) > cap:
            capped.append({"candidate_ref": eid, "dropped": len(merged) - cap})
            merged = merged[:cap]
        candidates.extend(merged)

    return {
        "candidates": candidates,
        "pool_size": pool_pairs,
        "conflicts": conflicts,
        "capped": capped,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Unit 3 — resolution wiring: deterministic gate + review wrapper + approval
# ---------------------------------------------------------------------------

# SOS review-evidence fields attached to a candidate (so the operator approves
# against the hard entity number + status/type/locale — Novato vs Stockton — not
# a bare name). All entity-level; NEVER a street address / ZIP / person field.
_REVIEW_EVIDENCE = ("entity_status", "entity_type", "formation_date", "principal_city", "principal_state")


def enrich_casos_candidate(
    candidate: dict[str, Any], ref: dict[str, Any]
) -> dict[str, Any]:
    """Attach the SOS entity-level review evidence (`registry_*`) onto a candidate.

    The candidate already carries `signal_strength` (the adapter renamed
    `confidence`). Only whitelist fields are copied — never a raw SOS row."""
    out = normalize_resolution_candidate_for_artifact(dict(candidate))
    for field in _REVIEW_EVIDENCE:
        if ref.get(field) is not None:
            out[f"registry_{field}"] = ref[field]
    return out


def resolve_casos_deterministic(
    sos_refs: list[dict[str, Any]],
    existing_orgs: list[dict[str, Any]],
    *,
    policy_version: str = POLICY_VERSION,
    source_system: str = SOURCE_SYSTEM,
) -> dict[str, Any]:
    """Run SOS refs through the shared resolver + Identity Control A's egress gate.

    A matching `sos_id` on BOTH sides → an egress-gated `deterministic` ledger
    assertion + a SAME_AS stamped with its id (the ONE permitted auto-merge — used
    on constructed keyed fixtures; the real export carries no `sos_id`). A name
    match → a `queued` candidate. Name similarity alone NEVER merges."""
    same_as, candidates = propose_org_resolutions(
        sos_refs, existing_orgs, identity_keys=("sos_id",)
    )
    gated, assertions, demoted = gate_ingestor_same_as(
        same_as, sos_refs, existing_orgs,
        source_system=source_system, policy_version=policy_version,
    )
    return {
        "same_as_edges": gated,
        "assertions": assertions,
        "candidates": candidates,
        "demoted": demoted,
    }


def assertion_for_approved_casos_candidate(
    candidate: dict[str, Any],
    *,
    subject: dict[str, Any],
    target: dict[str, Any],
    reviewer: str,
    decided_at: str,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    """Write the ledger assertion for an operator-APPROVED `sos_id` candidate.

    The pinned evidence mapping: the candidate carries `evidence_record_ids` (the
    resolver's field); the ledger takes `evidence_refs` — map one to the other."""
    return make_assertion(
        subject_ref=candidate["subject_ref"],
        target_ref=candidate["candidate_ref"],
        status="approved",
        basis="operator_approved_sos_id",
        subject=subject,
        target=target,
        reviewer=reviewer,
        decided_at=decided_at,
        policy_version=policy_version,
        evidence_refs=list(candidate.get("evidence_record_ids", [])),
    )


# ---------------------------------------------------------------------------
# Unit 4 — the redaction gate (Predeclared 6; the load-bearing new invariant)
# ---------------------------------------------------------------------------

# The ONLY fields a published / egress artifact may carry. Everything else (street
# addresses, ZIPs, person names, agents, principals) is dropped.
PUBLISHABLE_FIELDS = (
    "sos_id", "display_label", "entity_type", "entity_status",
    "formation_date", "principal_city", "principal_state",
)

# Forbidden KEY-name substrings — a structural guard that catches a person/address
# field leaking by name even if its value isn't a known sentinel (Codex r2 #4).
# `principal_city`/`principal_state` are whitelisted and contain none of these.
_FORBIDDEN_KEY_SUBSTRINGS = (
    "address", "postal", "zip", "first_name", "middle_name", "last_name",
    "agent_name", "physical", "position_type", "mailing", "street",
)
_DEFAULT_SENTINELS = ("REDACT_ME",)


def publishable_casos_fields(ref: dict[str, Any]) -> dict[str, Any]:
    """The whitelist projection — ONLY entity-level fields, never a street address,
    ZIP, person name, agent, or principal."""
    return {k: ref[k] for k in PUBLISHABLE_FIELDS if ref.get(k) not in (None, "")}


def scan_for_forbidden(
    obj: Any,
    *,
    sentinels: tuple[str, ...] = _DEFAULT_SENTINELS,
    forbidden_keys: tuple[str, ...] = _FORBIDDEN_KEY_SUBSTRINGS,
    _path: str = "",
) -> list[str]:
    """Recursive structural + value leak scan → a list of violations (empty = clean).

    Flags any dict KEY whose name contains a forbidden substring, and any string
    VALUE (anywhere) containing a sentinel. Used by the redaction tests, the e2e,
    and the final pre-completion sweep over every artifact + log + the evidence."""
    violations: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            kl = str(key).lower()
            if any(fk in kl for fk in forbidden_keys):
                violations.append(f"{_path}.{key}: forbidden key name")
            violations.extend(scan_for_forbidden(
                value, sentinels=sentinels, forbidden_keys=forbidden_keys, _path=f"{_path}.{key}"
            ))
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            violations.extend(scan_for_forbidden(
                value, sentinels=sentinels, forbidden_keys=forbidden_keys, _path=f"{_path}[{i}]"
            ))
    else:
        text = str(obj)
        for sentinel in sentinels:
            if sentinel in text:
                violations.append(f"{_path}: sentinel {sentinel!r}")
    return violations


def parse_casos_agents(
    lines: Iterable[str],
) -> Iterator[tuple[str | None, bool]]:
    """STREAM `Agents.csv` → `(entity_num, individual_agent)` per row, reading ONLY
    `ENTITY_NUM` + `AGENT_TYPE`. The natural-person columns (FIRST/LAST_NAME,
    PHYSICAL_ADDRESS…) are NEVER read — so the output carries no person data."""
    header: dict[str, int] | None = None
    for line in lines:
        fields = line.rstrip("\n").split(DELIMITER)
        if header is None:
            header = {name: i for i, name in enumerate(fields)}
            continue

        def cell(col: str) -> str:
            idx = header.get(col)
            return fields[idx].strip() if idx is not None and idx < len(fields) else ""

        num = _normalize_sos_id(cell("ENTITY_NUM"))
        is_individual = cell("AGENT_TYPE").strip().lower() == "individual agent"
        yield num, is_individual


def individual_agent_flags(lines: Iterable[str]) -> dict[str, bool]:
    """`{entity_num -> has-an-individual-(natural-person)-registered-agent}` — the
    only thing this lane derives from the agent file; the agent's name/address is
    never read or published."""
    flags: dict[str, bool] = {}
    for num, is_individual in parse_casos_agents(lines):
        if num is not None:
            flags[num] = flags.get(num, False) or is_individual
    return flags


# ---------------------------------------------------------------------------
# Unit 6 — coverage report + DB-free CLI (Predeclared 8, 10)
# ---------------------------------------------------------------------------

# Honest scope of the SOS key source (Codex r1-analog minor).
SOURCE_LIMITATION = (
    "CA SOS registered business entities, statewide; an entity may be "
    "Marin-active under an out-of-area registered/agent address"
)


def build_casos_coverage_report(
    block_result: dict[str, Any],
    existing_orgs: list[dict[str, Any]],
    *,
    policy_version: str = POLICY_VERSION,
    enriched_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The coverage report — the keyless tail is PUBLISHED, never implied resolved.

    Carries only counts + ids + entity-level metadata; never a person/address
    field (redaction-clean by construction)."""
    candidates = block_result["candidates"]
    stats = block_result.get("stats", {})
    with_candidates = {c["candidate_ref"] for c in candidates}
    keyless_ids = sorted(e["id"] for e in existing_orgs if e["id"] not in with_candidates)
    enriched = enriched_refs or []
    return {
        "policy_version": policy_version,
        "source_limitation": SOURCE_LIMITATION,
        "filings": {
            "rows_scanned": stats.get("filings_rows_scanned", 0),
            "prefix_shapes": stats.get("prefix_shapes", {}),
            "entity_num_missing": stats.get("skipped", {}).get("entity_num_missing", 0),
        },
        "resolution": {
            "candidate_pool_size": block_result.get("pool_size", 0),
            "name_candidates_queued": len(candidates),
            "casos_row_conflict": len(block_result.get("conflicts", [])),
            "capped_existing_orgs": len(block_result.get("capped", [])),
        },
        "existing_orgs": {
            "total": len(existing_orgs),
            "with_candidates": len(with_candidates),
            "keyless_tail": len(keyless_ids),
            "keyless_ids": keyless_ids,
        },
        "enrichment": {
            "identity_key_conflict": sum(1 for r in enriched if r.get("identity_key_conflict")),
            "orgs_with_surfaced_sos_id": sum(1 for r in enriched if r.get("sos_id")),
        },
        "redaction": {
            # The lane publishes only the entity-level whitelist; no person/address
            # field is ever emitted (proven by the redaction leak scan).
            "person_fields_published": 0,
        },
    }


def _load_existing_orgs(path: str | Path) -> list[dict[str, Any]]:
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
    """Stream the staged Filings CSV → token-block → write the review sidecar +
    coverage report. Touches NO database (the enriched live export is the operator
    step in `export_existing_orgs.py`). Streams the 3.6 GB file line by line."""
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Identity Enrichment Lane 2 (CA-SOS): stream a staged CA SOS Filings "
            "export, block it against an existing-orgs export, and write the review "
            "queue + coverage report. No network, no database (see the module "
            "docstring for the operator download runbook)."
        )
    )
    parser.add_argument("--filings", required=True, type=Path, help="Operator-staged CA SOS Filings.csv (*|*-delimited).")
    parser.add_argument("--existing-orgs", required=True, help="JSON array of existing org refs.")
    parser.add_argument("--review-dir", required=True, type=Path, help="Output dir for review queue + coverage report.")
    args = parser.parse_args(argv)

    existing = _load_existing_orgs(args.existing_orgs)
    with open(args.filings, encoding="utf-8") as fh:  # streamed line by line
        result = block_casos_against_existing(fh, existing)
    report = build_casos_coverage_report(result, existing)

    review_dir: Path = args.review_dir
    review_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(review_dir / "resolution-candidates-casos.jsonl", result["candidates"])
    (review_dir / "coverage-casos.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        f"Filings: {report['filings']['rows_scanned']} scanned, "
        f"{report['filings']['entity_num_missing']} missing-num | "
        f"candidates: {report['resolution']['name_candidates_queued']} queued "
        f"({report['resolution']['candidate_pool_size']} pool) | "
        f"existing: {report['existing_orgs']['keyless_tail']}/{report['existing_orgs']['total']} keyless"
    )
    return 0


# Register at import so any importer of this module can use the `sos_id` key.
register_sos_id_normalizer()


if __name__ == "__main__":
    raise SystemExit(main())
