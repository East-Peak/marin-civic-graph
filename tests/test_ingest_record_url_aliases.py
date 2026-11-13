"""The stage pins the reviewed Record-URL alias list (scripts/record_url_aliases.py) in a guarded source's capture.

A crosswalk-required or native-only source with entries gets `record_url_aliases: {path, sha256}` in its capture
and `record_url_aliases_sha256` in its ledger entry; the load re-checks both. A source without entries pins
nothing (so the list can change under it freely); an invalid list fails a guarded source closed before any
fetch, as an invalid crosswalk does. Fictional fixtures (Lakeport), reused from the crosswalk and native tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import record_url_aliases as rua  # noqa: E402
import test_crosswalk as xwt  # noqa: E402
import test_native_identity as nat  # noqa: E402
from test_crosswalk import adapter  # noqa: E402,F401  (fixture)

ENTRY = {"record_id": "record-lakeport-minutes", "art": "minutes",
         "established_url": "https://storage.example/old/m.pdf", "page_url": "https://storage.example/new/m.pdf",
         "evidence": {"kind": "identical_bytes", "sha256": "d" * 64}, "reviewed": "2026-11-12"}


def _write(root: Path, sid=xwt.SID, body=None) -> Path:
    path = root / rua.PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body is not None else yaml.safe_dump({"format": 1, "sources": {sid: [ENTRY]}}))
    return path


def _crosswalk_capture(root, adapter):
    return json.loads(adapter(xwt._config(), root).extracted_path().read_text())


def test_a_crosswalk_source_with_entries_pins_the_list(tmp_path, adapter):
    xwt._write_xw(tmp_path)
    _write(tmp_path)
    sha = rua.load(tmp_path).sha256
    _, verdict, ledger = xwt._run(tmp_path, adapter)
    assert verdict.ok
    assert _crosswalk_capture(tmp_path, adapter)["record_url_aliases"] == {"path": rua.PATH, "sha256": sha}
    assert ledger[-1]["record_url_aliases_sha256"] == sha


def test_a_source_without_entries_pins_nothing(tmp_path, adapter):
    xwt._write_xw(tmp_path)
    _write(tmp_path, sid="another-city-council")
    _, verdict, ledger = xwt._run(tmp_path, adapter)
    assert verdict.ok
    assert "record_url_aliases" not in _crosswalk_capture(tmp_path, adapter)
    assert "record_url_aliases_sha256" not in ledger[-1]


def test_no_list_at_all_pins_nothing(tmp_path, adapter):
    xwt._write_xw(tmp_path)
    assert xwt._run(tmp_path, adapter)[1].ok
    assert "record_url_aliases" not in _crosswalk_capture(tmp_path, adapter)


def test_an_invalid_list_fails_a_guarded_source_before_any_fetch(tmp_path, adapter):
    xwt._write_xw(tmp_path)
    _write(tmp_path, body="format: 1\nsources: {}\nsources: {}\n")
    _, verdict, ledger = xwt._run(tmp_path, adapter)
    assert not verdict.ok and adapter.captures == 0
    assert ledger[-1]["outcome"] == "record_url_aliases_invalid"
    assert not adapter(xwt._config(), tmp_path).extracted_path().exists()


def test_a_native_source_with_entries_pins_the_list_beside_its_load_policy(tmp_path):
    _write(tmp_path, sid=nat.SID)
    _, verdict, ledger = nat._run(tmp_path)
    assert verdict.ok, verdict.reasons
    capture = json.loads(nat._capture_file(tmp_path).read_text())
    assert capture["record_url_aliases"] == {"path": rua.PATH, "sha256": rua.load(tmp_path).sha256}
    assert capture["load_policy"] == nat.cw.load_policy(nat._config())  # the policy itself is unchanged
    assert ledger[-1]["record_url_aliases_sha256"] == rua.load(tmp_path).sha256


def test_a_native_source_without_entries_writes_the_capture_it_always_did(tmp_path):
    _, verdict, _ = nat._run(tmp_path)
    without = nat._capture_file(tmp_path).read_text()
    _write(tmp_path, sid="another-city-council")
    nat._capture_file(tmp_path).unlink()
    assert nat._run(tmp_path)[1].ok
    assert nat._capture_file(tmp_path).read_text() == without
