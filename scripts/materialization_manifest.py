"""Materialization manifest loader + integrity validator (Open Marin Phase 0, A2).

The manifest (``registry/v2-materialization-manifest.json``) is the committed
integrity ledger for every input that materializes the graph's facts. The data
itself lives in the private ``East-Peak/marin-civic-graph-data`` repo (the code
repo's ``data/normalized`` is a gitignored symlink into it), so validation means
"every input's sha256 + bytes (+ lines where present) match this committed
ledger" — NOT "git-tracked in the code repo".

Data-root resolution: ``$OPENMARIN_DATA_DIR`` (the data-repo root) if set, else
``<code-repo>/data``. Each manifest path is ``normalized/...`` so the file is
``data_root / path`` (resolves all 78 inputs under ``data/`` via the
``data/normalized`` symlink — do NOT root at ``data/normalized``).
"""
from __future__ import annotations
import json, hashlib, os, sys
from pathlib import Path


def load_manifest(path) -> dict:
    """Read the manifest JSON from disk."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_data_root(data_root=None) -> Path:
    """Resolve the data root: explicit arg > $OPENMARIN_DATA_DIR > <repo>/data."""
    if data_root is not None:
        return Path(data_root)
    env = os.environ.get("OPENMARIN_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def _digest_bytes_lines(path: Path) -> tuple[str, int, int]:
    """Stream a file once → (sha256 hexdigest, byte count, newline count)."""
    h = hashlib.sha256()
    nbytes = nlines = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            nbytes += len(chunk)
            nlines += chunk.count(b"\n")
    return h.hexdigest(), nbytes, nlines


def validate_manifest(manifest, data_root=None) -> int:
    """Validate every input against the committed ledger. Raises ValueError on
    the first mismatch; returns the number of inputs validated on success.

    For each input: recompute sha256 and assert it MATCHES the manifest; assert
    ``bytes`` matches; assert ``lines`` matches ONLY when the key is present
    (jsonl-only — the .json bundle inputs carry no ``lines``).
    """
    root = resolve_data_root(data_root)
    inputs = manifest["inputs"]
    for inp in inputs:
        rel = inp["path"]
        fp = root / rel
        if not fp.exists():
            raise ValueError(f"missing input file {fp} (manifest path {rel!r})")
        digest, nbytes, nlines = _digest_bytes_lines(fp)
        if digest != inp["sha256"]:
            raise ValueError(
                f"sha256 mismatch for {rel}: manifest {inp['sha256']} != actual {digest}")
        if nbytes != inp["bytes"]:
            raise ValueError(
                f"bytes mismatch for {rel}: manifest {inp['bytes']} != actual {nbytes}")
        if "lines" in inp and nlines != inp["lines"]:
            raise ValueError(
                f"lines mismatch for {rel}: manifest {inp['lines']} != actual {nlines}")
    return len(inputs)


def main(argv=None) -> int:
    """Validate the committed manifest against the resolved data root."""
    repo_root = Path(__file__).resolve().parent.parent
    manifest_path = repo_root / "registry" / "v2-materialization-manifest.json"
    manifest = load_manifest(manifest_path)
    root = resolve_data_root()
    print(f"manifest:   {manifest_path}")
    print(f"data_root:  {root}")
    print(f"inputs:     {manifest.get('input_count', len(manifest['inputs']))}")
    n = validate_manifest(manifest, data_root=root)
    print(f"VALIDATED:  all {n} inputs match sha256 + bytes (+ lines where present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
