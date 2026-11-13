"""The reviewed Record-URL alias list (scripts/record_url_aliases.py): registry data the no-overwrite load reads.

An entry says: this existing Record, established at this url, is the artifact the page now links at that url, and
here is the evidence (identical bytes, or a reviewed variant). Anything malformed, duplicated or ambiguous refuses
to load at all. Fixtures are fictional (Lakeport).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import record_url_aliases as rua  # noqa: E402

SID = "lakeport-city-council"
OLD = "https://storage.example/lakeport-old/{}.pdf"
NEW = "https://storage.example/lakeport-new/{}.pdf"
SHA = "a" * 64


def entry(rid="record-lakeport-minutes-1", art="minutes", name="minutes-1", **over):
    return {"record_id": rid, "art": art, "established_url": OLD.format(name), "page_url": NEW.format(name),
            "evidence": {"kind": "identical_bytes", "sha256": SHA}, "reviewed": "2026-11-12", **over}


def write(root: Path, body) -> Path:
    path = root / rua.PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else yaml.safe_dump(body, sort_keys=False))
    return path


def doc(*entries, sid=SID):
    return {"format": 1, "sources": {sid: list(entries)}}


def test_a_valid_list_loads_with_its_file_hash(tmp_path):
    path = write(tmp_path, doc(entry(), entry("record-lakeport-agenda-1", "agenda", "agenda-1")))
    aliases = rua.load(tmp_path)
    assert aliases.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert [e["record_id"] for e in aliases.entries(SID)] == ["record-lakeport-minutes-1", "record-lakeport-agenda-1"]
    assert aliases.entries("another-source") == []


def test_a_missing_file_is_no_aliases_and_binds_nothing(tmp_path):
    aliases = rua.load(tmp_path)
    assert aliases.sha256 is None and aliases.entries(SID) == []
    assert rua.binding(tmp_path, SID) is None


def test_binding_names_the_file_and_its_hash_only_for_a_source_with_entries(tmp_path):
    path = write(tmp_path, doc(entry()))
    assert rua.binding(tmp_path, SID) == {"path": rua.PATH, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert rua.binding(tmp_path, "another-source") is None


def test_a_reviewed_variant_carries_both_hashes_and_a_rationale(tmp_path):
    variant = {"kind": "reviewed_variant", "established_sha256": SHA, "page_sha256": "b" * 64,
               "rationale": "same text; the established copy is the signed one"}
    write(tmp_path, doc(entry(evidence=variant)))
    assert rua.load(tmp_path).entries(SID)[0]["evidence"] == variant


def test_several_reviewed_page_urls_for_one_record_are_each_their_own_entry(tmp_path):
    write(tmp_path, doc(entry(), entry(page_url=NEW.format("minutes-1-again"))))
    assert len(rua.load(tmp_path).entries(SID)) == 2


@pytest.mark.parametrize("body, why", [
    ("format: 1\nsources: {lakeport-city-council: [}\n", "unreadable"),
    ("format: 1\nformat: 1\nsources: {}\n", "duplicate"),
    ("format: 1\nsources:\n  lakeport-city-council:\n  - {record_id: r, record_id: r}\n", "duplicate"),
    ({"format": 2, "sources": {}}, "format"),
    ({"format": 1, "sources": {SID: []}}, "no entries"),
    ({"format": 1, "sources": {SID: [entry()]}, "extra": 1}, "keys"),
])
def test_a_malformed_file_refuses_to_load(tmp_path, body, why):
    write(tmp_path, body)
    with pytest.raises(rua.AliasError, match=why):
        rua.load(tmp_path)


@pytest.mark.parametrize("bad, why", [
    (entry(note="x"), "keys"),
    ({k: v for k, v in entry().items() if k != "reviewed"}, "keys"),
    (entry(record_id="meeting-lakeport-1"), "record_id"),
    (entry(art="slides"), "art"),
    (entry(established_url="http://storage.example/a.pdf"), "established_url"),
    (entry(page_url=OLD.format("minutes-1")), "same url"),
    (entry(reviewed="12 Nov 2026"), "reviewed"),
    (entry(evidence={"kind": "identical_bytes"}), "evidence"),
    (entry(evidence={"kind": "identical_bytes", "sha256": "xyz"}), "evidence"),
    (entry(evidence={"kind": "reviewed_variant", "established_sha256": SHA, "page_sha256": SHA,
                     "rationale": "same"}), "evidence"),
    (entry(evidence={"kind": "reviewed_variant", "established_sha256": SHA, "page_sha256": "b" * 64,
                     "rationale": ""}), "evidence"),
    (entry(evidence={"kind": "looks_fine", "sha256": SHA}), "evidence"),
])
def test_a_malformed_entry_refuses_to_load(tmp_path, bad, why):
    write(tmp_path, doc(bad))
    with pytest.raises(rua.AliasError, match=why):
        rua.load(tmp_path)


@pytest.mark.parametrize("pair, why", [
    ((entry(), entry()), "twice"),
    ((entry(), entry(rid="record-lakeport-minutes-2", established_url=OLD.format("minutes-2"))), "two Records"),
    ((entry(), entry(art="agenda", page_url=NEW.format("x"))), "one art and one established url"),
    ((entry(), entry(established_url=OLD.format("other"), page_url=NEW.format("x"))),
     "one art and one established url"),
    ((entry(), entry(rid="record-lakeport-minutes-2", name="minutes-2", page_url=OLD.format("minutes-1"))),
     "established url"),
])
def test_conflicting_entries_refuse_to_load(tmp_path, pair, why):
    write(tmp_path, doc(*pair))
    with pytest.raises(rua.AliasError, match=why):
        rua.load(tmp_path)


@pytest.mark.parametrize("bad", [{**entry(), 1: "x"}, entry(evidence={"kind": []}), entry(evidence=["identical_bytes"]),
                                 entry(record_id=["record-x"]), entry(art=["minutes"])])
def test_wrongly_typed_values_refuse_as_alias_errors(tmp_path, bad):
    write(tmp_path, doc(bad))
    with pytest.raises(rua.AliasError):
        rua.load(tmp_path)


def test_a_source_id_that_is_not_a_string_refuses(tmp_path):
    write(tmp_path, {"format": 1, "sources": {1: [entry()]}})
    with pytest.raises(rua.AliasError, match="source"):
        rua.load(tmp_path)


def test_the_committed_list_is_valid():
    rua.load(REPO)  # the registry's own file loads (or is absent)
