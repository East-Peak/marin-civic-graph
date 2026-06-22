"""Build an "org-stubs" funding envelope dir for the M2d dual-role join.

The dual-role read model (build_dual_role_candidates.py) extracts funding-in
legs PER INPUT CLASS from the funding envelope's OWN nodes, and its loader fails
loud on a same-id node re-emitted with a divergent payload (Decision 1). The
County contracts ingestor, run with --approved-resolutions, points its
TO_TARGET edges at canonical org-* recipient ids but does NOT re-emit those
Organization nodes (they live in the live graph), so the funding extractor sees
no recipient org and emits no leg. This helper supplies the missing recipient
Organization nodes as a second funding dir, WITHOUT colliding with the influence
side:

  * Organization nodes already present in the influence inputs are copied
    VERBATIM — guaranteeing byte-identity across the two input classes, so the
    cross-class merge never fails loud.
  * Funding recipients absent from influence are synthesized from the canonical
    org export (a minimal, stable Organization node). A recipient absent from
    BOTH is a stale approval and fails loud.

Repeatable dual-role run (no manual steps):

  python scripts/ingest_marin_county_contracts.py --input <contracts.csv> \
      --out-dir data/projected/dual-role/county-funding-in \
      --existing-orgs data/exports/existing-orgs-enriched.json \
      --approved-resolutions data/review/county/approved-resolutions.jsonl
  python scripts/build_dual_role_org_stubs.py \
      --influence-out data/normalized/marin-county-campaign-finance-campaign-finance \
      --approved-resolutions data/review/county/approved-resolutions.jsonl \
      --org-export data/exports/existing-orgs-enriched.json \
      --out-dir data/projected/dual-role/org-stubs
  python scripts/build_dual_role_candidates.py \
      --funding-in data/projected/dual-role/county-funding-in \
                   data/projected/dual-role/org-stubs \
      --influence-out data/normalized/marin-county-campaign-finance-campaign-finance \
      --review-dir data/review/dual-role

No database, no fetching. Pure transform over envelope dirs + the org export.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# Canonical org-stub property keys, copied from the org export when present. Kept
# small and stable so a synthesized stub stays deterministic and never carries
# unrelated export fields. The dual-role extractor uses org nodes only for the
# Organization type check, so these props are informational.
_STUB_PROP_KEYS = ("ein", "uei", "sos_id", "irs_subsection_class", "entity_status", "degree")


def _synth_org_node(record: dict[str, Any]) -> dict[str, Any]:
    """A minimal, deterministic Organization node from an org-export record."""
    props = {k: record[k] for k in _STUB_PROP_KEYS if k in record}
    return {
        "id": record["id"],
        "node_type": "Organization",
        "labels": ["Organization"],
        "display_label": record.get("display_label", record["id"]),
        "properties": props,
    }


def build_org_stub_nodes(
    influence_nodes: list[dict[str, Any]],
    recipient_org_ids: set[str],
    org_export_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Org-stub nodes for the funding side, sorted by id.

    Every Organization node in `influence_nodes` is carried verbatim (byte
    identity across classes). Each id in `recipient_org_ids` absent from
    influence is synthesized from `org_export_by_id`; one absent from both
    raises (stale approval — never silently dropped)."""
    influence_orgs: dict[str, dict[str, Any]] = {
        n["id"]: n for n in influence_nodes if n.get("node_type") == "Organization"
    }
    out: dict[str, dict[str, Any]] = dict(influence_orgs)
    for org_id in sorted(recipient_org_ids):
        if org_id in influence_orgs:
            continue
        record = org_export_by_id.get(org_id)
        if record is None:
            raise ValueError(
                f"recipient org {org_id!r} is absent from the influence inputs "
                "and the org export (stale approval)"
            )
        out[org_id] = _synth_org_node(record)
    return [out[k] for k in sorted(out)]


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_influence_nodes(dirs: list[Path]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for directory in dirs:
        nodes.extend(_read_jsonl(Path(directory) / "nodes.jsonl"))
    return nodes


def read_recipient_org_ids(approved_path: Path | None) -> set[str]:
    """The candidate_ref (canonical org-*) of every approved resolution."""
    if approved_path is None:
        return set()
    return {
        row["candidate_ref"]
        for row in _read_jsonl(approved_path)
        if row.get("status") == "approved" and row.get("candidate_ref")
    }


def read_org_export(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else next(
        v for v in data.values() if isinstance(v, list)
    )
    return {r["id"]: r for r in rows}


def write_org_stubs(out_dir: Path, nodes: list[dict[str, Any]]) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "nodes.jsonl").write_text(
        "".join(json.dumps(n, sort_keys=True) + "\n" for n in nodes),
        encoding="utf-8",
    )
    (out_dir / "edges.jsonl").write_text("", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build the org-stubs funding dir for the M2d dual-role join."
    )
    parser.add_argument("--influence-out", nargs="+", required=True, type=Path,
                        help="Influence envelope dirs; their Organization nodes are copied verbatim.")
    parser.add_argument("--approved-resolutions", type=Path, default=None,
                        help="Approved-only resolution extract; its candidate_refs are the funding recipients.")
    parser.add_argument("--org-export", type=Path, default=None,
                        help="Canonical org export (e.g. existing-orgs-enriched.json) for synthesizing funding-only recipients.")
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    influence_nodes = read_influence_nodes(args.influence_out)
    recipient_org_ids = read_recipient_org_ids(args.approved_resolutions)
    org_export_by_id = read_org_export(args.org_export)
    nodes = build_org_stub_nodes(influence_nodes, recipient_org_ids, org_export_by_id)
    write_org_stubs(args.out_dir, nodes)
    print(f"Wrote {len(nodes)} org-stub nodes to {args.out_dir}")


if __name__ == "__main__":
    main()
