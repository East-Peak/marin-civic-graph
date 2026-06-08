import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from materialization_manifest import load_manifest, validate_manifest


def _root(tmp_path):
    # paths in the manifest start with "normalized/...", resolved against the data root
    f = tmp_path / "normalized" / "x.jsonl"; f.parent.mkdir(parents=True); f.write_text("{}\n{}\n")
    return tmp_path, f


def test_sha256_mismatch_raises(tmp_path):
    root, _ = _root(tmp_path)
    m = {"inputs": [{"path": "normalized/x.jsonl", "sha256": "deadbeef", "bytes": 6, "lines": 2}]}
    with pytest.raises(ValueError, match="sha256"):
        validate_manifest(m, data_root=root)


def test_matching_input_passes(tmp_path):
    root, f = _root(tmp_path)
    raw = f.read_bytes()
    m = {"inputs": [{"path": "normalized/x.jsonl", "sha256": hashlib.sha256(raw).hexdigest(),
                     "bytes": len(raw), "lines": raw.count(b"\n")}]}
    validate_manifest(m, data_root=root)  # no raise


def test_lines_optional_for_json_bundles(tmp_path):
    # .json bundle inputs carry no `lines` key — validator must not require it
    f = tmp_path / "normalized" / "b.json"; f.parent.mkdir(parents=True); f.write_text('{"a":1}')
    raw = f.read_bytes()
    m = {"inputs": [{"path": "normalized/b.json", "sha256": hashlib.sha256(raw).hexdigest(),
                     "bytes": len(raw)}]}  # no "lines"
    validate_manifest(m, data_root=tmp_path)  # no raise


def test_bytes_mismatch_raises(tmp_path):
    root, f = _root(tmp_path)
    raw = f.read_bytes()
    m = {"inputs": [{"path": "normalized/x.jsonl", "sha256": hashlib.sha256(raw).hexdigest(),
                     "bytes": len(raw) + 1, "lines": raw.count(b"\n")}]}
    with pytest.raises(ValueError, match="bytes"):
        validate_manifest(m, data_root=root)


def test_lines_mismatch_raises_when_present(tmp_path):
    root, f = _root(tmp_path)
    raw = f.read_bytes()
    m = {"inputs": [{"path": "normalized/x.jsonl", "sha256": hashlib.sha256(raw).hexdigest(),
                     "bytes": len(raw), "lines": 99}]}
    with pytest.raises(ValueError, match="lines"):
        validate_manifest(m, data_root=root)


def test_missing_input_file_raises(tmp_path):
    (tmp_path / "normalized").mkdir(parents=True)
    m = {"inputs": [{"path": "normalized/nope.jsonl", "sha256": "00", "bytes": 0}]}
    with pytest.raises((FileNotFoundError, ValueError)):
        validate_manifest(m, data_root=tmp_path)
