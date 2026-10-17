#!/usr/bin/env python3
"""Crosswalk-required meeting identity: a reviewed, exact listing-slug -> existing Meeting id map.

Some sources' Meetings were built by hand before the weekly adapters existed (San Rafael's wave-01
scripts: `meeting-{date}-san-rafael-city-council[-suffix]`), while the adapter emits
`meeting-{source_id}-{slug}`. The date/title identity map (meeting_identity.py) cannot bridge them
safely: it would duplicate every meeting, or link two distinct meetings sharing a date and title. A
source marked `identity: crosswalk-required` takes its ids from this crosswalk or keeps the adapter's
own, nothing else; anything missing, malformed or conflicting fails the source closed.

    crosswalk.py generate --source <id> --export <dir> --listing <html> [--write] [--report <json>]

`generate` matches the listing's slugs to existing Meetings by their exact `meeting_page_url` slug and
reports everything else. Entries are append-only: an established entry survives every regeneration
(including meetings that left the listing); deleting or reassigning one is a conflict, never a rewrite.
The file carries no provenance (that is the report's), so its sha256 changes only when entries do: that
hash is the crosswalk version a run pins.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

FORMAT = 1
REQUIRED = "crosswalk-required"
SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~%-]*")  # one URL path segment (real slugs end in "_")
ROOT = Path(__file__).resolve().parent.parent


class CrosswalkError(ValueError):
    """The crosswalk is missing, malformed, or contradicts the pull: the source fails closed."""


@dataclass(frozen=True)
class Crosswalk:
    source_id: str
    entries: dict[str, str]
    sha256: str
    path: Path


def required(config: dict) -> bool:
    return config.get("identity") == REQUIRED


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def adapter_id(source_id: str, slug: str) -> str:
    return f"meeting-{source_id}-{slug}"


def page_slug(url: str | None) -> str | None:
    """The last path segment of a meeting page url (`.../meetings/<slug>/`)."""
    return url.rstrip("/").rsplit("/", 1)[-1] if url else None


def slug_of(source_id: str, meeting_id) -> str:
    prefix = adapter_id(source_id, "")
    slug = meeting_id.removeprefix(prefix) if isinstance(meeting_id, str) else ""
    if not (isinstance(meeting_id, str) and meeting_id.startswith(prefix) and SLUG_RE.fullmatch(slug)):
        raise CrosswalkError(f"{meeting_id!r} is not an adapter id of the form {prefix}<slug>")
    return slug


def load(path: Path, source_id: str) -> Crosswalk:
    path = Path(path)
    try:
        raw = path.read_bytes()
        body = json.loads(raw, object_pairs_hook=_unique_keys)
    except (OSError, ValueError) as exc:
        raise CrosswalkError(f"crosswalk {path} is missing or unreadable: {exc}") from None
    if not isinstance(body, dict) or body.get("format") != FORMAT:
        raise CrosswalkError(f"crosswalk {path} is not format {FORMAT}")
    if body.get("source_id") != source_id:
        raise CrosswalkError(f"crosswalk {path} is for {body.get('source_id')!r}, not {source_id!r}")
    entries = body.get("entries")
    _validate(path, source_id, entries)
    return Crosswalk(source_id, dict(entries), hashlib.sha256(raw).hexdigest(), path)


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    """json.loads keeps only the last of two equal keys; a crosswalk with two must not load at all."""
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError(f"duplicate keys {sorted({k for k in keys if keys.count(k) > 1})}")
    return dict(pairs)


def _validate(path: Path, source_id: str, entries) -> None:
    if not isinstance(entries, dict) or not entries:
        raise CrosswalkError(f"crosswalk {path} has no entries")
    native = adapter_id(source_id, "")
    for slug, target in entries.items():
        if not (isinstance(slug, str) and SLUG_RE.fullmatch(slug)):
            raise CrosswalkError(f"crosswalk {path}: {slug!r} is not a listing slug")
        if not (isinstance(target, str) and target.startswith("meeting-")) or target.startswith(native):
            raise CrosswalkError(f"crosswalk {path}: {slug} -> {target!r} is not an existing (non-adapter) Meeting id")
    if len(set(entries.values())) != len(entries):
        raise CrosswalkError(f"crosswalk {path} maps two slugs to one Meeting")


def apply(crosswalk: Crosswalk, meetings: list[dict]) -> dict[str, int]:
    """Rewrite each meeting's id to its crosswalk target or keep the adapter's, in place.

    The adapter id stays on the meeting as `adapter_meeting_id`. Two meetings resolving to one id are a
    conflict (CrosswalkError), never a merge. Returns {"mapped": n, "native": n}.
    """
    resolved = []
    for meeting in meetings:
        own = meeting.get("meeting_id")
        slug = slug_of(crosswalk.source_id, own)
        resolved.append((meeting, own, crosswalk.entries.get(slug, own)))
    claimed: dict[str, str] = {}
    for _, own, canonical in resolved:
        if canonical in claimed:
            raise CrosswalkError(f"{claimed[canonical]} and {own} both claim {canonical}")
        claimed[canonical] = own
    for meeting, own, canonical in resolved:
        meeting["adapter_meeting_id"] = own
        meeting["meeting_id"] = canonical
    mapped = sum(own != canonical for _, own, canonical in resolved)
    return {"mapped": mapped, "native": len(resolved) - mapped}


def write(path: Path, source_id: str, entries: dict[str, str]) -> None:
    path = Path(path)
    _validate(path, source_id, entries)  # never write what load would refuse
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"format": FORMAT, "source_id": source_id, "entries": dict(sorted(entries.items()))},
                      indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


# --- the generator ------------------------------------------------------------------------------------


def _graph_meetings(export_dir: Path, institution_id: str) -> dict[str, dict]:
    """The source's Meetings in an export (`{id, labels, properties}` rows): id -> properties."""
    found = {}
    with open(Path(export_dir) / "nodes.jsonl", encoding="utf-8") as fh:
        for line in fh:
            if '"Meeting"' not in line:
                continue
            node = json.loads(line)
            props = node.get("properties") or {}
            if "Meeting" in node.get("labels", []) and props.get("institution_id") == institution_id:
                found[node["id"]] = props
    return found


def generate(source_id: str, institution_id: str, export_dir: Path, listing_html: str, *, base_url: str,
             backfill_from: str, previous: dict[str, str] | None = None) -> tuple[dict[str, str], dict]:
    """(entries, report). Entries = previous ∪ exact new matches; a conflict leaves the entry as it was."""
    from adapters.proudcity import extract_meeting_urls

    previous = dict(previous or {})
    graph = _graph_meetings(export_dir, institution_id)
    native_prefix = adapter_id(source_id, "")
    native = sorted(mid for mid in graph if mid.startswith(native_prefix))
    carried: dict[str, list[str]] = {}  # slug -> every source Meeting whose page carries it, native or not
    for mid, props in graph.items():
        slug = page_slug(props.get("meeting_page_url"))
        if slug:
            carried.setdefault(slug, []).append(mid)
    by_slug = {slug: [m for m in mids if not m.startswith(native_prefix)] for slug, mids in carried.items()}
    listing = [m["slug"] for m in extract_meeting_urls(listing_html, base_url)
               if not m["date"] or m["date"] >= backfill_from]
    conflicts = [f"{slug}: carried by {len(mids)} Meetings {sorted(mids)}"
                 for slug, mids in sorted(carried.items()) if len(mids) > 1]
    entries = dict(previous)
    for slug, target in sorted(previous.items()):
        carriers = by_slug.get(slug, [])
        if target not in graph:
            conflicts.append(f"{slug}: established target {target} is not a Meeting of {institution_id}")
        elif target.startswith(native_prefix) or carriers != [target]:
            conflicts.append(f"{slug}: established target {target} but the slug is carried by {sorted(carriers)}")
    for slug in listing:
        carriers = sorted(by_slug.get(slug, []))
        if len(carried.get(slug, [])) == 1 and carriers and slug not in entries:
            if carriers[0] in entries.values():
                conflicts.append(f"{slug}: {carriers[0]} is already the target of another entry")
            else:
                entries[slug] = carriers[0]
    for slug in sorted(entries):
        if adapter_id(source_id, slug) in graph:
            conflicts.append(f"{slug}: maps to {entries[slug]} but its adapter id {adapter_id(source_id, slug)} "
                             "also exists in the graph")
    targets = set(entries.values())
    graph_only = []
    for mid, props in sorted(graph.items()):
        if mid in targets or mid.startswith(native_prefix):
            continue
        dated = props.get("meeting_date") or ""
        reason = ("no_meeting_page_url" if not props.get("meeting_page_url")
                  else "before_backfill_from" if dated and dated < backfill_from else "not_in_listing")
        if reason == "no_meeting_page_url" and dated and dated < backfill_from:
            reason = "before_backfill_from"
        graph_only.append({"id": mid, "reason": reason})
    native_slugs = {mid.removeprefix(native_prefix) for mid in native}
    report = {
        "source_id": source_id,
        "matched": sorted(s for s in listing if s in entries),
        "kept": sorted(s for s in entries if s not in set(listing)),
        "listing_only": sorted(s for s in listing if s not in entries and s not in native_slugs),
        "native": native,
        "graph_only": graph_only,
        "conflicts": conflicts,
        "counts": {"listing": len(listing), "graph_meetings": len(graph), "entries": len(entries)},
    }
    return entries, report


def _report_markdown(report: dict) -> str:
    c = report["counts"]
    lines = [f"# Crosswalk report: {report['source_id']}", "",
             f"- listing slugs (after backfill_from): {c['listing']}; graph Meetings: {c['graph_meetings']}; "
             f"entries: {c['entries']}",
             f"- matched (exact meeting_page_url slug): {len(report['matched'])}",
             f"- kept (established, absent from this listing): {len(report['kept'])}",
             f"- listing-only (load as new Meetings): {len(report['listing_only'])}",
             f"- native (created by an earlier weekly load): {len(report['native'])}",
             f"- graph-only: {len(report['graph_only'])}",
             f"- conflicts: {len(report['conflicts'])}", ""]
    for title, items in (("Listing-only", report["listing_only"]), ("Kept", report["kept"]),
                         ("Graph-only", [f"{g['id']} ({g['reason']})" for g in report["graph_only"]]),
                         ("Conflicts", report["conflicts"])):
        if items:
            lines += [f"## {title}", "", *(f"- {item}" for item in items), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import yaml

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate", help="match a listing to an export; dry run unless --write")
    gen.add_argument("--source", required=True)
    gen.add_argument("--export", type=Path, required=True, help="export dir with nodes.jsonl (read only)")
    gen.add_argument("--listing", type=Path, required=True, help="the source's captured listing page")
    gen.add_argument("--registry", type=Path, default=ROOT / "registry" / "proudcity-sources.yaml")
    gen.add_argument("--write", action="store_true", help="write the registry crosswalk file (no conflicts only)")
    gen.add_argument("--report", type=Path, help="write the JSON report here (and <report>.md)")
    args = parser.parse_args(argv)

    config = next((s for s in yaml.safe_load(args.registry.read_text())["sources"] if s["id"] == args.source), None)
    if config is None or not required(config) or not config.get("crosswalk"):
        print(f"Error: {args.source} is not `identity: {REQUIRED}` with a `crosswalk` path in {args.registry}",
              file=sys.stderr)
        return 2
    path = ROOT / config["crosswalk"]
    previous = load(path, args.source).entries if path.exists() else {}
    base = config["url"].split("/", 3)
    entries, report = generate(args.source, config["institution_id"], args.export,
                               args.listing.read_text(encoding="utf-8"), base_url="/".join(base[:3]),
                               backfill_from=str(config.get("backfill_from", "")), previous=previous)
    report["inputs"] = {"export_nodes_sha256": sha256_file(args.export / "nodes.jsonl"),
                        "listing_sha256": sha256_file(args.listing)}
    markdown = _report_markdown(report)
    if args.report:
        args.report.write_text(json.dumps(report, indent=1) + "\n")
        args.report.with_suffix(".md").write_text(markdown + "\n")
    print(markdown)
    if report["conflicts"]:
        print("Refusing: conflicts must be resolved by a reviewed migration.", file=sys.stderr)
        return 1
    if args.write:
        write(path, args.source, entries)
        print(f"wrote {path} (sha256 {sha256_file(path)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
