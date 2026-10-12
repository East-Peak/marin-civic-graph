#!/usr/bin/env python3
"""Private person-identity review for campaign donors (operator-only; nothing here is public).

  init-key [--version N]          create the HMAC key in the private directory (never replaces one)
  build --export DIR --as-of DATE  evidence, queue, review files and report into <private>/builds/<as-of>/

The private directory is $OPEN_MARIN_IDENTITY_DIR (default ~/.open-marin-private/identity). See
docs/person-identity-runbook.md. Errors print one line naming rows, lines or paths; never a cell value.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import identity_person_evidence as ev  # noqa: E402
import identity_person_key as ik  # noqa: E402

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

def _destination(private: Path, name: str) -> Path:
    rel = Path(name)
    real_private = private.resolve()
    dest = (private / rel)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ev.IdentityError(f"--out {name} must name a directory inside the private directory")
    real = dest.resolve()
    if real_private not in real.parents:
        raise ev.IdentityError(f"--out {name} must name a directory inside the private directory")
    current = private
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ev.IdentityError(f"--out {name}: {current} is a symlink")
    return dest


def write_build(private: Path, name: str, files: dict[str, bytes]) -> Path:
    """Write files into a fresh 0700 temp dir in the private directory, then swap it in for <private>/<name>."""
    dest = _destination(private, name)
    for parent in reversed([p for p in dest.parents if private in p.parents and not p.exists()]):
        os.mkdir(parent, 0o700)
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


def build_files(evidence: ev.Evidence, key: ik.Key, as_of: str) -> dict[str, bytes]:
    manifest = {"as_of": as_of, "key_version": key.version, "inputs": evidence.inputs, "counts": evidence.counts}
    address = [{"row_id": r.row_id, "bucket": r.bucket, "address_hash": r.address_hash,
                "reason": r.address_reason, "key_version": key.version} for r in evidence.rows]
    return {"manifest.json": _dump(manifest), "address-evidence.jsonl": _jsonl(address)}


def cmd_build(args) -> int:
    private = ik.private_dir()
    key = ik.load_key(private)
    inputs = ev.Inputs(args.ledger, args.raw_root, args.export, args.decisions)
    for label, path in (("--ledger", args.ledger), ("--raw-root", args.raw_root), ("--export", args.export),
                        ("--decisions", args.decisions)):
        if path is None:
            raise ev.IdentityError(f"{label} is required (no default found)")
    _destination(private, args.out or f"builds/{args.as_of}")
    evidence = ev.collect(inputs, key)
    dest = write_build(private, args.out or f"builds/{args.as_of}", build_files(evidence, key, args.as_of))
    print(f"built {dest}: {evidence.counts['in_scope']} rows in {evidence.counts['buckets']} buckets")
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
    build.add_argument("--out", help="output dir inside the private dir (default builds/<as-of>)")
    build.set_defaults(func=cmd_build)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except (ev.IdentityError, ik.IdentityKeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # anything unforeseen may carry a cell value: print only its type
        print(f"internal error: {type(exc).__name__} (details suppressed)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
