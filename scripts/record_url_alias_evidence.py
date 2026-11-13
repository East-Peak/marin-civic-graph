#!/usr/bin/env python3
"""Evidence for reviewed Record-URL aliases (scripts/record_url_aliases.py), built in staging, never in the repo.

    record_url_alias_evidence.py build --source <id> --capture <capture.json> --export <dir> --out <new staging dir>
                                       [--verdicts <json>] [--reviewed YYYY-MM-DD]
    record_url_alias_evidence.py merge --source <id> --evidence <that dir>

`build` runs the real no-overwrite planner (guarded_load.load_capture) on a fake graph seeded from a read-only
export, ignoring any alias list the capture pinned, and takes every `artifact_url_changed` hold on a single
established Record. For each, it fetches the Record's url and the page's url now, through the robots gate at the
agenda stage's spacing, and keeps both files, their text (pdftotext) and the response metadata. Identical bytes
become an `identical_bytes` entry, when both are a served (200) PDF with readable text: an error page, an empty body or an
unreadable file is `unusable`, never evidence. Different bytes become a `reviewed_variant` entry only when `--verdicts` holds a
reviewer's `same_document` verdict naming exactly this Record, page url and both hashes (the reviewer is given only
the two texts, listed under `for_review`). An unavailable url, or different bytes without such a verdict, gets no
entry. Everything is bound in manifest.json (baseline export, capture, rows, file hashes) and its sha256.

`merge` adds a build's entries to the registry list after re-checking the manifest's hashes. It is append-only:
an entry already there is kept as is; one that would change is refused, as is anything load would refuse.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import guarded_load  # noqa: E402
import record_url_aliases as rua  # noqa: E402

MAX_BYTES = 50 * 1024 * 1024


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def gated_fetch(gate, *, sleep=time.sleep, monotonic=time.monotonic, now=_now):
    """fetch(url) -> (bytes | None, response metadata): one host per request, the agenda stage's spacing."""
    import agenda_items
    import robots_gate

    pacer = agenda_items._Pacer(sleep, monotonic)

    def fetch(url: str):
        pacer.wait(url)
        meta = {"url": url, "fetched_at": now()}
        request = urllib.request.Request(url, headers={"User-Agent": robots_gate.USER_AGENT})
        try:
            with gate.open(request, timeout=agenda_items.FETCH_TIMEOUT, hosts=frozenset({urlsplit(url).hostname})) as r:
                data = r.read(MAX_BYTES + 1)
                meta.update(final_url=r.geturl(), status=getattr(r, "status", None),
                            **{k.lower().replace("-", "_"): r.headers.get(k)
                               for k in ("Content-Type", "Content-Length", "Last-Modified", "ETag")})
        except robots_gate.RobotsRefused as exc:
            return None, {**meta, "error": f"{exc.outcome}: {exc}"}
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            return None, {**meta, "error": f"{type(exc).__name__}: {exc}"}
        if len(data) > MAX_BYTES:
            return None, {**meta, "error": f"over {MAX_BYTES} bytes"}
        return data, meta

    return fetch


def plan(config: dict, capture: dict, export: Path, work: Path, *, root: Path) -> dict:
    """The real planner's report for `capture` without any alias list: what the load holds today."""
    capture = {k: v for k, v in capture.items() if k != "record_url_aliases"}
    graph = guarded_load.FakeGraphPort.create(work, seed=export)
    with guarded_load.open_port(f"fakegraph://{graph.resolve()}") as port:
        report = guarded_load.load_capture(port, capture, config, root=root)
    report.pop("normalized", None)
    return report


def _side(out: Path, data: bytes | None, meta: dict, extract) -> dict:
    side = {"response": meta}
    if data is None:
        return side
    sha = hashlib.sha256(data).hexdigest()
    path = out / "files" / f"{sha}{'.pdf' if data[:4] == b'%PDF' else '.bin'}"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    side.update(sha256=sha, bytes=len(data), file=path.relative_to(out).as_posix())
    try:
        text = extract(data)
    except Exception as exc:  # noqa: BLE001  (kept as evidence, never fatal)
        side["text_error"] = f"{type(exc).__name__}: {exc}"
        return side
    tpath = out / "texts" / f"{sha}.txt"
    tpath.parent.mkdir(exist_ok=True)
    tpath.write_text(text, encoding="utf-8")
    side["text"] = tpath.relative_to(out).as_posix()
    side["text_chars"] = len(text.strip())
    return side


def _usable(side: dict) -> bool:
    """Identity evidence only from a PDF served with status 200, with readable text: never an error page, an empty body or a
    file pdftotext cannot read, however equal two of them are."""
    return side["response"].get("status") == 200 and side.get("file", "").endswith(".pdf") \
        and bool(side.get("text")) and side.get("bytes", 0) > 0 and side.get("text_chars", 0) > 0


def _entry(row: dict, verdicts: list[dict], reviewed: str) -> tuple[dict | None, dict | None]:
    """(the entry, the review it rests on) for one compared row."""
    base = {k: row[k] for k in ("record_id", "art", "established_url", "page_url")}
    if row["comparison"] == "identical_bytes":
        return {**base, "evidence": {"kind": "identical_bytes", "sha256": row["page"]["sha256"]},
                "reviewed": reviewed}, None
    if row["comparison"] != "differs":
        return None, None
    want = (row["record_id"], row["page_url"], row["established"]["sha256"], row["page"]["sha256"])
    review = next((v for v in verdicts if (v.get("record_id"), v.get("page_url"), v.get("established_sha256"),
                                           v.get("page_sha256")) == want), None)
    if review is None or review.get("verdict") != "same_document":
        return None, review
    return {**base, "evidence": {"kind": "reviewed_variant", "established_sha256": want[2], "page_sha256": want[3],
                                 "rationale": review["rationale"]}, "reviewed": reviewed}, review


def build(config: dict, capture_path: Path, export: Path, out: Path, *, root: Path = REPO, fetch, extract,
          verdicts: list[dict], reviewed: str, now=_now) -> dict:
    out, export = Path(out).resolve(), Path(export).resolve()
    if out.is_relative_to(REPO.resolve()):
        raise ValueError(f"evidence goes in staging, never inside the repo ({out})")
    if out.exists():
        raise ValueError(f"{out} exists: each build gets a new dir")
    out.mkdir(parents=True)
    capture = json.loads(Path(capture_path).read_text(encoding="utf-8"))
    report = plan(config, capture, export, out / "planner-graph", root=root)
    rows, other = [], []
    for hold in report["holds"]:
        established = hold.get("established") or {}
        if hold["reason"] != "artifact_url_changed" or len(established) != 1:
            other.append(hold)
            continue
        (rid, old), = established.items()
        rows.append({"meeting": hold["meeting"], "record_id": rid, "art": hold["art"], "established_url": old,
                     "page_url": hold["url"]})
    for row in sorted(rows, key=lambda r: (r["meeting"], r["art"])):
        row["established"] = _side(out, *fetch(row["established_url"]), extract)
        row["page"] = _side(out, *fetch(row["page_url"]), extract)
        shas = (row["established"].get("sha256"), row["page"].get("sha256"))
        row["comparison"] = ("unavailable" if None in shas
                             else "unusable" if not (_usable(row["established"]) and _usable(row["page"]))
                             else "identical_bytes" if shas[0] == shas[1] else "differs")
        row["entry"], row["review"] = _entry(row, verdicts, reviewed)
    rows.sort(key=lambda r: (r["meeting"], r["art"]))
    entries = [r["entry"] for r in rows if r["entry"]]
    (out / "entries.yaml").write_text(_dump({config["id"]: entries}) if entries else "")
    manifest = {
        "source_id": config["id"], "made_at": now(), "reviewed": reviewed,
        "baseline_export": {"path": str(export), **{f: sha256_file(export / f) for f in ("nodes.jsonl", "edges.jsonl")}},
        "capture": {"path": str(Path(capture_path).resolve()), "sha256": sha256_file(capture_path),
                    "crosswalk_sha256": (capture.get("crosswalk") or {}).get("sha256")},
        "planner": {"outcome": report["outcome"], "holds": dict(Counter(h["reason"] for h in report["holds"])),
                    "not_aliasable": other},
        "counts": dict(Counter(r["comparison"] for r in rows)), "entries": len(entries),
        "rows": rows,
        "for_review": [{k: r[k] for k in ("record_id", "page_url")} | {
            "established_text": r["established"].get("text"), "page_text": r["page"].get("text")}
            for r in rows if r["comparison"] == "differs"],
        "entries_sha256": sha256_file(out / "entries.yaml"),
        "files": {p.relative_to(out).as_posix(): sha256_file(p) for d in ("files", "texts")
                  for p in sorted((out / d).glob("*")) if (out / d).is_dir()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    (out / "manifest.json.sha256").write_text(f"{sha256_file(out / 'manifest.json')}  manifest.json\n")
    return json.loads((out / "manifest.json").read_text())


def _dump(sources: dict[str, list[dict]]) -> str:
    ordered = {s: [{k: e[k] for k in rua.KEYS} for e in entries] for s, entries in sources.items()}
    return yaml.safe_dump({"format": rua.FORMAT, "sources": ordered}, sort_keys=False, default_flow_style=None,
                          width=1000, allow_unicode=True)


def merge(root: Path, source_id: str, entries: list[dict]) -> int:
    """Add `entries` for `source_id` to the registry list; returns how many were new. Append-only, validated."""
    path = Path(root) / rua.PATH
    sources = {s: rua.load(root).entries(s) for s in rua.load(root).by_source}
    have = {(e["record_id"], e["page_url"]): e for e in sources.get(source_id, [])}
    added = []
    for e in entries:
        old = have.get((e["record_id"], e["page_url"]))
        if old is not None and old != e:
            raise rua.AliasError(f"{e['record_id']} -> {e['page_url']} is already listed differently; "
                                 "entries are never rewritten")
        if old is None:
            added.append(e)
    if not added:
        return 0
    sources[source_id] = sources.get(source_id, []) + added
    text = _dump(sources)
    rua.parse(text.encode())  # never write what load would refuse
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return len(added)


def _verified_entries(evidence: Path, source_id: str) -> list[dict]:
    manifest_path = evidence / "manifest.json"
    pinned = (evidence / "manifest.json.sha256").read_text().split()[0]
    if sha256_file(manifest_path) != pinned:
        raise ValueError("manifest.json changed since it was written")
    manifest = json.loads(manifest_path.read_text())
    if manifest["source_id"] != source_id or sha256_file(evidence / "entries.yaml") != manifest["entries_sha256"]:
        raise ValueError("entries.yaml is not the one the manifest binds, or is for another source")
    changed = [rel for rel, sha in manifest["files"].items() if sha256_file(evidence / rel) != sha]
    if changed:
        raise ValueError(f"evidence files changed since the build: {changed[:5]}")
    return [r["entry"] for r in manifest["rows"] if r["entry"]]


def main(argv: list[str] | None = None) -> int:
    from crosswalk_rehearsal import source_registry
    from agenda_parsers import extract_text
    from robots_gate import RobotsGate

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source", required=True)
    b.add_argument("--capture", type=Path, required=True)
    b.add_argument("--export", type=Path, required=True, help="a read-only export dir (nodes.jsonl, edges.jsonl)")
    b.add_argument("--out", type=Path, required=True, help="a new staging dir, outside the repo")
    b.add_argument("--verdicts", type=Path, help="reviewers' verdicts on differing pairs (JSON list)")
    b.add_argument("--reviewed", default=date.today().isoformat())
    m = sub.add_parser("merge")
    m.add_argument("--source", required=True)
    m.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.cmd == "merge":
        added = merge(REPO, args.source, _verified_entries(args.evidence, args.source))
        print(f"{rua.PATH}: {added} new entries for {args.source} (sha256 {rua.load(REPO).sha256})")
        return 0
    _, config = source_registry(REPO, args.source)
    out = args.out.resolve()
    if out.exists():
        print(f"Error: {out} exists", file=sys.stderr)
        return 2
    gate = RobotsGate(cache_path=out.parent / f"{out.name}.robots.json",
                      request_log=out.parent / f"{out.name}.requests.jsonl")
    verdicts = json.loads(args.verdicts.read_text()) if args.verdicts else []
    manifest = build(config, args.capture, args.export, out, fetch=gated_fetch(gate), extract=extract_text,
                     verdicts=verdicts, reviewed=args.reviewed)
    print(json.dumps({k: manifest[k] for k in ("planner", "counts", "entries", "entries_sha256")}, indent=1))
    print(f"manifest {out / 'manifest.json'} sha256 {sha256_file(out / 'manifest.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
