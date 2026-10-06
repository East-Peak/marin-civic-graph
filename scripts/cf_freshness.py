"""Campaign freshness fields, read from one preparation bundle (cf_prepare.py) and nothing else.

Per source: the latest report date observed in the bundle's filings, the export (download) date of each year's
file, the years with no export, and the years whose newer download was held (the bundle keeps the earlier one).
The bake publishes these only after verifying that the graph it bakes holds exactly this bundle (verified()).
"""
from __future__ import annotations

import json
from pathlib import Path


class FreshnessError(Exception):
    """The bundle cannot say how fresh it is."""


def _consistent(bundle: Path, selection: dict) -> None:
    """The selection says exactly what the bundle normalized: its id recomputes, and per source and year its
    files are the normalizer's own input manifest (workbooks and pinned pages, by sha256)."""
    from cf_prepare import bundle_id

    if bundle_id(selection["sources"]) != selection.get("bundle_id"):
        raise FreshnessError("selection.json's bundle_id does not match its contents")
    for sid, source in selection["sources"].items():
        claimed = {(y, e["sha256"], "workbook" if e["status"] == "export" else "unavailable")
                   for y, e in source["years"].items() if e.get("sha256")}
        manifest = bundle / sid / "manifest.json"
        inputs = json.loads(manifest.read_text())["inputs"] if manifest.is_file() else []
        normalized = {(i["year"], i["sha256"], i["coverage"]) for i in inputs}
        if claimed != normalized:
            raise FreshnessError(f"{sid}: selection.json does not match the normalizer's input manifest")


def freshness(bundle: Path) -> dict:
    bundle = Path(bundle)
    selection_path = bundle / "selection.json"
    if not selection_path.is_file():
        raise FreshnessError(f"{bundle} has no selection.json (not a preparation bundle)")
    selection = json.loads(selection_path.read_text())
    _consistent(bundle, selection)
    sources = []
    for sid, source in sorted(selection["sources"].items()):
        latest = None
        filings = bundle / sid / "filings.jsonl"
        if filings.is_file():
            with filings.open() as fh:
                for line in fh:
                    reported = json.loads(line).get("rpt_date")
                    if reported and (latest is None or reported > latest):
                        latest = reported
        years = sorted(source["years"].items())
        sources.append({
            "source_id": sid, "name": source["name"], "jurisdiction_id": source["jurisdiction_id"],
            "latest_report_date": latest,
            "exports": [{"year": y, "export_date": e["capture"]} for y, e in years if e["status"] == "export"],
            "unavailable_years": [y for y, e in years if e["status"] != "export"],
            "held_years": [y for y, e in years if e.get("held")],
        })
    return {"bundle_id": selection["bundle_id"], "sources": sources}


def verified(export_dir: Path, bundles: list[Path]) -> tuple[dict | None, dict]:
    """The freshness of the first bundle the export holds exactly (cf_migration_plan.check_live), and a report."""
    from cf_migration_plan import check_live

    report: dict = {"verified_bundle": None, "rejected": []}
    for bundle in bundles:
        bundle = Path(bundle)
        try:
            fields = freshness(bundle)
            problems = check_live(Path(export_dir), bundle)
        except (FreshnessError, OSError, ValueError, KeyError) as exc:
            report["rejected"].append({"bundle": str(bundle), "reason": f"{type(exc).__name__}: {exc}"})
            continue
        if problems:
            # A count only: the bake report is published, and a problem can quote a withheld value.
            report["rejected"].append({"bundle": str(bundle), "reason": "the graph does not hold this bundle",
                                       "problems": len(problems)})
            continue
        report["verified_bundle"] = str(bundle)
        return fields, report
    return None, report
