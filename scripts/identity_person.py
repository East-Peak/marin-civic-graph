#!/usr/bin/env python3
"""Private person-identity review for campaign donors (operator-only; nothing here is public).

  init-key [--version N]          create the HMAC key in the private directory (never replaces one)
  build --export DIR --as-of DATE  evidence, queue, review files and report into <private>/builds/<as-of>/
  ingest --build NAME LINES        validate decision lines against that build's evidence; write all or nothing

The private directory is $OPEN_MARIN_IDENTITY_DIR (default ~/.open-marin-private/identity). See
docs/person-identity-runbook.md. Errors print one line naming rows, lines or paths; never a cell value.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import warnings
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import identity_person_decisions as dec  # noqa: E402
import identity_person_evidence as ev  # noqa: E402
import identity_person_key as ik  # noqa: E402
import identity_person_queue as iq  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _data_repo() -> Path | None:
    """The private data repo, through data/normalized of this checkout or of the main checkout."""
    for checkout in sorted(ik.protected_roots()):
        link = checkout / "data" / "normalized"
        if link.is_symlink() or link.exists():
            return link.resolve().parent
    return None


def _default(*parts: str) -> Path | None:
    repo = _data_repo()
    return repo.joinpath(*parts) if repo else None


def _main_checkout() -> Path:
    for checkout in sorted(ik.protected_roots()):
        if (checkout / "data" / "raw").is_dir():
            return checkout
    return ROOT


def _as_of(text: str) -> str:
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError("--as-of must be YYYY-MM-DD") from None


def key_versions_used(decisions: Path | None) -> int:
    """The highest key version any fingerprint in the decision file names (0 when none)."""
    if not decisions or not decisions.exists():
        return 0
    return max((int(v) for v in re.findall(r"\b(?:fp1|tf1):k([0-9]{1,6}):", decisions.read_text())), default=0)


# ---------------------------------------------------------------------------
# Output: written only inside the private directory, atomically
# ---------------------------------------------------------------------------

_BUILD_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _destination(private: Path, name: str) -> Path:
    """<private>/builds/<name>: a plain name, no symlink or git checkout on the way, replacing only a build."""
    if not _BUILD_NAME.fullmatch(name or "") or name in (".", ".."):
        raise ev.IdentityError(f"--out {name!r} must be a plain name (letters, digits, . _ -): "
                               "builds go to <private>/builds/<name>")
    builds = private / "builds"
    dest = builds / name
    for path in (builds, dest):
        if path.is_symlink():
            raise ev.IdentityError(f"{path} is a symlink")
        if (path / ".git").exists():
            raise ev.IdentityError(f"{path} is a git checkout; builds never go into one")
    if dest.exists() and not (dest.is_dir() and (dest / "manifest.json").is_file()):
        raise ev.IdentityError(f"{dest} exists and is not a previous build; move it aside first")
    return dest


def write_build(private: Path, name: str, files: dict[str, bytes]) -> Path:
    """Write files into a fresh 0700 temp dir in the private directory, then swap it in for the destination."""
    dest = _destination(private, name)
    if not dest.parent.exists():
        os.mkdir(dest.parent, 0o700)
    staging = Path(tempfile.mkdtemp(prefix=".build-", dir=private))
    try:
        for rel, data in sorted(files.items()):
            target = staging / rel
            for parent in reversed([p for p in target.parents if staging in p.parents and not p.exists()]):
                os.mkdir(parent, 0o700)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        _destination(private, name)  # re-checked just before the swap
        old = None
        if dest.exists():
            old = Path(tempfile.mkdtemp(prefix=".old-", dir=private))
            os.rename(dest, old / "previous")
        os.rename(staging, dest)
        if old is not None:
            shutil.rmtree(old)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return dest


def _dump(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _jsonl(rows) -> bytes:
    return "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows).encode()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init_key(args) -> int:
    private = ik.private_dir()
    used = key_versions_used(args.decisions)
    path = ik.init_key(private, version=args.version, min_version=used + 1)
    print(f"created identity key version {args.version}: {path}")
    return 0


def current_state(evidence: ev.Evidence, key: ik.Key, decisions: list, latch: frozenset) -> dec.State:
    return dec.effective_state(decisions, {r.row_id: r.fp for r in evidence.rows},
                               {r.row_id: r.moneyflow_id for r in evidence.rows},
                               iq.target_fingerprints(key, evidence.graph, decisions), latch)


def build_files(evidence: ev.Evidence, key: ik.Key, as_of: str, state: dec.State, args: dict) -> dict[str, bytes]:
    queue = iq.build_queue(evidence, state, key, as_of)
    manifest = {"as_of": as_of, "key_version": key.version, "args": args, "inputs": evidence.inputs,
                "counts": evidence.counts, "latch_sha256": hashlib.sha256(dec.latch_bytes(state.latch)).hexdigest()}
    address = [{"row_id": r.row_id, "bucket": r.bucket, "address_hash": r.address_hash,
                "reason": r.address_reason, "key_version": key.version} for r in evidence.rows]
    return {"manifest.json": _dump(manifest), "address-evidence.jsonl": _jsonl(address),
            "decisions-state.json": _dump(dec.state_json(state)), "queue.json": _dump(iq.queue_json(queue)),
            "review/batch-001.md": iq.render_batch(queue, evidence).encode()}


@contextlib.contextmanager
def _locked(private: Path):
    """One identity command at a time (build and ingest both read and write the latch)."""
    with open(private / "decisions.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ev.IdentityError("another identity command is running; nothing written") from None
        yield


def cmd_build(args) -> int:
    private = ik.private_dir()
    key = ik.load_key(private)
    inputs = ev.Inputs(args.ledger, args.raw_root, args.export, args.decisions)
    for label, path in (("--ledger", args.ledger), ("--raw-root", args.raw_root), ("--export", args.export),
                        ("--decisions", args.decisions)):
        if path is None:
            raise ev.IdentityError(f"{label} is required (no default found)")
    out = args.out if args.out is not None else args.as_of
    _destination(private, out)
    evidence = ev.collect(inputs, key)
    recorded = {name: str(Path(getattr(args, name)).resolve()) for name in ("ledger", "raw_root", "export", "decisions")}
    with _locked(private):
        decisions = dec.load_decisions(args.decisions)
        dec.check_dates(decisions, args.as_of)
        latch = dec.load_latch(private)
        state = current_state(evidence, key, decisions, latch)
        files = build_files(evidence, key, args.as_of, state, recorded)
        if state.latch != latch:  # persisted before the build is published
            dec.write_latch(private, state.latch)
        dest = write_build(private, out, files)
    print(f"built {dest}: {evidence.counts['in_scope']} rows in {evidence.counts['buckets']} buckets")
    return 0


# ---------------------------------------------------------------------------
# ingest: all or nothing, under a lock, compare-and-swap on the decision file
# ---------------------------------------------------------------------------

def _replace_decisions(path: Path, before: str, text: str) -> None:
    """Write `text` over the decision file unless it no longer holds `before` (temp file, fsync, os.replace)."""
    def current() -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    if current() != before:
        raise ev.IdentityError("the decision file changed during ingest; nothing written: run ingest again")
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(prefix=".decisions-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        if current() != before:
            raise ev.IdentityError("the decision file changed during ingest; nothing written: run ingest again")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _why(state: dec.State, d) -> str:
    status = state.status[d.digest]
    if status == "stale":
        changes = "; ".join(f"{where}: {', '.join(what)}" for where, what in state.stale[d.digest].items())
        return f"stale ({changes})"
    reason = state.suspended[d.digest]
    if reason.startswith("c-"):
        c = next(c for c in state.conflicts if c.id == reason)
        return f"conflict {reason} ({'; '.join(c.reasons)})"
    return f"suspended ({reason})"


def cmd_ingest(args) -> int:
    private = ik.private_dir()
    key = ik.load_key(private)
    build = _destination(private, args.build)
    try:
        manifest = json.loads((build / "manifest.json").read_text())
        recorded = manifest["args"]
    except (OSError, ValueError, KeyError):
        raise ev.IdentityError(f"build {args.build} has no readable manifest; run build first") from None
    if manifest["key_version"] != key.version:
        raise ev.IdentityError(f"build {args.build} used key version {manifest['key_version']}; rebuild")
    decisions_path = Path(recorded["decisions"])
    evidence = ev.collect(ev.Inputs(Path(recorded["ledger"]), Path(recorded["raw_root"]), Path(recorded["export"]),
                                    decisions_path), key)

    def pinned(inputs):
        return sorted((i["role"], i["path"], i["sha256"]) for i in inputs if i["role"] != "decisions")
    if pinned(evidence.inputs) != pinned(manifest["inputs"]):
        raise ev.IdentityError(f"the evidence inputs changed since build {args.build}; rebuild and review again")
    try:
        offered = dec.parse_lines(Path(args.lines).read_text(encoding="utf-8"))
    except dec.DecisionError as exc:
        raise ev.IdentityError(f"batch rejected, nothing written: {exc}") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ev.IdentityError(f"{args.lines}: unreadable ({type(exc).__name__})") from None
    late = [d.number for d in offered if d.date > manifest["as_of"]]
    if late:
        raise ev.IdentityError(f"batch rejected, nothing written: line {late[0]}: dated after the build's as-of")
    with _locked(private):
        before = decisions_path.read_text(encoding="utf-8") if decisions_path.exists() else ""
        existing = dec.parse_lines(before)
        known = {d.digest for d in existing}
        latch = dec.load_latch(private)
        added = [d for d in offered if d.digest not in known]
        revalidated = {d.digest for d in offered if d.digest in latch}  # re-ingested after review
        state = current_state(evidence, key, existing + added, latch - revalidated)
        bad = [f"line {d.number}: {_why(state, d)}" for d in offered if state.status[d.digest] != "effective"]
        if bad:
            raise ev.IdentityError("batch rejected, nothing written: " + " | ".join(bad))
        if not added and not revalidated:
            print("no change: every line is already in the decision file and effective")
            return 0
        if added:
            text = before + ("\n" if before and not before.endswith("\n") else "")
            _replace_decisions(decisions_path, before, text + "".join(d.line + "\n" for d in added))
        if revalidated:
            dec.write_latch(private, latch - revalidated)
    print(f"ingested {len(added)} decision(s); revalidated {len(revalidated)}; "
          f"{sum(1 for d in offered if d.digest in known and d.digest not in revalidated)} already present")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-key", help="create the identity HMAC key (refuses to replace one)")
    init.add_argument("--version", type=int, default=1)
    init.add_argument("--decisions", type=Path, default=_default("identity", "person", "decisions.jsonl"))
    init.set_defaults(func=cmd_init_key)
    build = sub.add_parser("build", help="evidence, queue, review files and report, from pinned inputs")
    build.add_argument("--ledger", type=Path, default=_default("normalized", "campaign-ledger"))
    build.add_argument("--raw-root", type=Path, default=_main_checkout() / "data" / "raw")
    build.add_argument("--export", type=Path, required=True, help="frozen export_live_graph.py --backup dir")
    build.add_argument("--decisions", type=Path, default=_default("identity", "person", "decisions.jsonl"))
    build.add_argument("--as-of", type=_as_of, required=True, help="the frozen clock (YYYY-MM-DD)")
    build.add_argument("--out", help="build name: <private>/builds/<name> (default: the --as-of date)")
    build.set_defaults(func=cmd_build)
    ingest = sub.add_parser("ingest", help="validate decision lines against a build and write them, or nothing")
    ingest.add_argument("--build", required=True, help="the build the lines were copied from (its name)")
    ingest.add_argument("lines", type=Path, help="a file of decision lines, one per line")
    ingest.set_defaults(func=cmd_ingest)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with warnings.catch_warnings(record=True) as caught:  # a library warning may quote a cell: never shown
        warnings.simplefilter("always")
        try:
            code = args.func(args)
        except (ev.IdentityError, ik.IdentityKeyError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            code = 1
        except Exception as exc:  # anything unforeseen may carry a cell value: print only its type
            print(f"internal error: {type(exc).__name__} (details suppressed)", file=sys.stderr)
            code = 2
    if caught:
        print(f"{len(caught)} library warning(s) suppressed (they may quote private cells)", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
