"""The alias evidence tool (scripts/record_url_alias_evidence.py): from the real planner's holds to reviewed entries.

It runs the real no-overwrite planner on a fake graph seeded from an export, takes every `artifact_url_changed`
hold on a single established Record, fetches both urls (through the robots gate in production; a fake here), keeps
both files, their text and response metadata, and writes a hash-bound manifest. Only identical bytes, or a
reviewed variant whose verdict names exactly the bytes fetched now, become entries; an unavailable url or changed
bytes get none. Fictional fixtures (Lakeport), reused from test_guarded_load.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import record_url_alias_evidence as ev  # noqa: E402
import record_url_aliases as rua  # noqa: E402
from test_guarded_load import (  # noqa: E402,F401  (fixtures)
    CONFIG, PDF, REG_MIN, SID, SPECIAL_MIN, _capture, _m, graph_dir, root)

NEW = "https://storage.example/lakeport-rehosted/{}.pdf"
REG_OLD, REG_NEW = PDF.format("minutes-2020-03-02"), NEW.format("minutes-2020-03-02")
SPECIAL_OLD, SPECIAL_NEW = PDF.format("minutes-2020-03-09"), NEW.format("minutes-2020-03-09")
SIGNED, UNSIGNED = b"%PDF-1.7 minutes, approved and signed", b"%PDF-1.7 minutes, approval line blank"


class Fetcher:
    def __init__(self, bodies: dict[str, bytes | None]):
        self.bodies, self.calls = bodies, []

    def __call__(self, url):
        self.calls.append(url)
        body = self.bodies.get(url)
        if body is None:
            return None, {"url": url, "error": "HTTPError 404"}
        return body, {"url": url, "status": 200, "content_type": "application/pdf"}


def _extract(data: bytes) -> str:
    return data.decode().removeprefix("%PDF-1.7 ")


@pytest.fixture
def world(root, graph_dir, tmp_path):
    capture = _capture(root, [_m("city-council-march-2-2020", "2020-03-02", minutes=REG_NEW),
                              _m("city-council-march-9-2020-special", "2020-03-09", minutes=SPECIAL_NEW)])
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(capture))
    return {"root": root, "capture": path, "export": graph_dir / "seed", "out": tmp_path / "evidence"}


def _build(world, bodies, verdicts=None):
    fetch = Fetcher(bodies)
    manifest = ev.build(CONFIG, world["capture"], world["export"], world["out"], root=world["root"], fetch=fetch,
                        extract=_extract, verdicts=verdicts or [], reviewed="2026-11-12", now=lambda: "T")
    return manifest, fetch


def _row(manifest, rid):
    return next(r for r in manifest["rows"] if r["record_id"] == rid)


def test_identical_bytes_become_entries_with_both_files_and_texts_kept(world):
    manifest, fetch = _build(world, {REG_OLD: SIGNED, REG_NEW: SIGNED, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s"})
    sha = hashlib.sha256(SIGNED).hexdigest()
    row = _row(manifest, REG_MIN)
    assert row["comparison"] == "identical_bytes" and row["entry"] == {
        "record_id": REG_MIN, "art": "minutes", "established_url": REG_OLD, "page_url": REG_NEW,
        "evidence": {"kind": "identical_bytes", "sha256": sha}, "reviewed": "2026-11-12"}
    for side in ("established", "page"):
        assert (world["out"] / row[side]["file"]).read_bytes() == SIGNED
        assert (world["out"] / row[side]["text"]).read_text() == "minutes, approved and signed"
        assert row[side]["sha256"] == sha and row[side]["response"]["status"] == 200
    assert sorted(fetch.calls) == sorted([REG_OLD, REG_NEW, SPECIAL_OLD, SPECIAL_NEW])
    entries = yaml.safe_load((world["out"] / "entries.yaml").read_text())
    assert entries == {"format": 1, "sources": {SID: [r["entry"] for r in manifest["rows"]]}}


def test_the_manifest_binds_its_inputs_and_files(world):
    manifest, _ = _build(world, {REG_OLD: SIGNED, REG_NEW: SIGNED, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s"})
    assert manifest["baseline_export"]["nodes.jsonl"] == ev.sha256_file(world["export"] / "nodes.jsonl")
    assert manifest["capture"]["sha256"] == ev.sha256_file(world["capture"])
    assert manifest["entries_sha256"] == ev.sha256_file(world["out"] / "entries.yaml")
    assert manifest["planner"]["holds"] == {"artifact_url_changed": 2}
    on_disk = json.loads((world["out"] / "manifest.json").read_text())
    assert on_disk == manifest
    assert (world["out"] / "manifest.json.sha256").read_text().split()[0] == ev.sha256_file(world["out"] / "manifest.json")
    for rel, sha in manifest["files"].items():
        assert ev.sha256_file(world["out"] / rel) == sha


def test_different_bytes_without_a_review_get_no_entry(world):
    manifest, _ = _build(world, {REG_OLD: SIGNED, REG_NEW: UNSIGNED, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s"})
    row = _row(manifest, REG_MIN)
    assert row["comparison"] == "differs" and row["entry"] is None and row["review"] is None
    assert [r["record_id"] for r in manifest["for_review"]] == [REG_MIN]


def _verdict(**over):
    return {"record_id": REG_MIN, "page_url": REG_NEW, "established_sha256": hashlib.sha256(SIGNED).hexdigest(),
            "page_sha256": hashlib.sha256(UNSIGNED).hexdigest(), "verdict": "same_document",
            "rationale": "same minutes; the established copy is the signed one", "reviewer": "a reviewer", **over}


def test_a_reviewed_variant_whose_verdict_names_these_bytes_becomes_an_entry(world):
    manifest, _ = _build(world, {REG_OLD: SIGNED, REG_NEW: UNSIGNED, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s"},
                         verdicts=[_verdict()])
    row = _row(manifest, REG_MIN)
    assert row["comparison"] == "differs" and row["review"] == _verdict()
    assert row["entry"]["evidence"] == {"kind": "reviewed_variant", "established_sha256": _verdict()["established_sha256"],
                                        "page_sha256": _verdict()["page_sha256"], "rationale": _verdict()["rationale"]}


@pytest.mark.parametrize("over", [{"verdict": "different_documents"}, {"page_sha256": "e" * 64},
                                  {"established_sha256": "e" * 64}, {"page_url": NEW.format("other")}])
def test_a_verdict_that_rejects_or_names_other_bytes_gives_no_entry(world, over):
    manifest, _ = _build(world, {REG_OLD: SIGNED, REG_NEW: UNSIGNED, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s"},
                         verdicts=[_verdict(**over)])
    assert _row(manifest, REG_MIN)["entry"] is None


@pytest.mark.parametrize("missing", [REG_OLD, REG_NEW])
def test_an_unavailable_url_gets_no_entry(world, missing):
    bodies = {REG_OLD: SIGNED, REG_NEW: SIGNED, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s", missing: None}
    manifest, _ = _build(world, bodies)
    row = _row(manifest, REG_MIN)
    assert row["comparison"] == "unavailable" and row["entry"] is None
    assert "404" in (row["established"] if missing == REG_OLD else row["page"])["response"]["error"]


@pytest.mark.parametrize("body", [b"<html>maintenance</html>", b"", b"%PDF-1.7 broken"],
                         ids=["identical-html", "empty", "unreadable-pdf"])
def test_identical_bodies_that_are_not_a_readable_pdf_are_unusable_never_entries(world, body):
    fetch = Fetcher({REG_OLD: body, REG_NEW: body, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s"})

    def extract(data):
        if data == b"%PDF-1.7 broken":
            raise RuntimeError("pdftotext exited 1")
        return _extract(data)

    manifest = ev.build(CONFIG, world["capture"], world["export"], world["out"], root=world["root"], fetch=fetch,
                        extract=extract, verdicts=[], reviewed="2026-11-12", now=lambda: "T")
    row = _row(manifest, REG_MIN)
    assert row["comparison"] == "unusable" and row["entry"] is None
    assert _row(manifest, SPECIAL_MIN)["entry"] is not None


@pytest.mark.parametrize("status", [203, None, "missing"])
def test_a_response_not_confirmed_200_is_unusable(world, status):
    class Status(Fetcher):
        def __call__(self, url):
            data, meta = super().__call__(url)
            if url != REG_NEW:
                return data, meta
            return data, ({k: v for k, v in meta.items() if k != "status"} if status == "missing"
                          else {**meta, "status": status})

    fetch = Status({REG_OLD: SIGNED, REG_NEW: SIGNED, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s"})
    manifest = ev.build(CONFIG, world["capture"], world["export"], world["out"], root=world["root"], fetch=fetch,
                        extract=_extract, verdicts=[], reviewed="2026-11-12", now=lambda: "T")
    assert _row(manifest, REG_MIN)["comparison"] == "unusable"


def test_holds_it_cannot_alias_are_reported_not_entered(world, root):
    capture = json.loads(world["capture"].read_text())
    capture["meetings"].append(_m("city-council-march-2-2020-closed-session", "2020-03-02", minutes=REG_OLD))
    world["capture"].write_text(json.dumps(capture))
    manifest, _ = _build(world, {REG_OLD: SIGNED, REG_NEW: SIGNED, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s"})
    assert [h["reason"] for h in manifest["planner"]["not_aliasable"]] == ["artifact_url_on_other_record"]


def test_the_planner_ignores_any_alias_binding_the_capture_carries(world):
    capture = json.loads(world["capture"].read_text())
    capture["record_url_aliases"] = {"path": rua.PATH, "sha256": "f" * 64}
    world["capture"].write_text(json.dumps(capture))
    manifest, _ = _build(world, {REG_OLD: SIGNED, REG_NEW: SIGNED, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s"})
    assert manifest["planner"]["holds"] == {"artifact_url_changed": 2}


def test_it_works_only_in_a_new_staging_dir(world):
    world["out"].mkdir()
    with pytest.raises(ValueError, match="exists"):
        _build(world, {})
    with pytest.raises(ValueError, match="repo"):
        ev.build(CONFIG, world["capture"], world["export"], REPO / "data" / "x", root=world["root"],
                 fetch=Fetcher({}), extract=_extract, verdicts=[], reviewed="2026-11-12")


# --- adding the entries to the registry list ----------------------------------------------------------------


def _entry(rid=REG_MIN, new=REG_NEW, sha="1" * 64):
    return {"record_id": rid, "art": "minutes", "established_url": REG_OLD if rid == REG_MIN else SPECIAL_OLD,
            "page_url": new, "evidence": {"kind": "identical_bytes", "sha256": sha}, "reviewed": "2026-11-12"}


def test_merge_adds_entries_keeps_the_rest_and_writes_a_valid_list(tmp_path):
    ev.merge(tmp_path, "another-city-council", [_entry()])
    ev.merge(tmp_path, SID, [_entry(), _entry(SPECIAL_MIN, SPECIAL_NEW)])
    ev.merge(tmp_path, SID, [_entry()])  # already there: nothing changes
    aliases = rua.load(tmp_path)
    assert [e["record_id"] for e in aliases.entries(SID)] == [REG_MIN, SPECIAL_MIN]
    assert aliases.entries("another-city-council") == [_entry()]


def test_merge_never_rewrites_an_entry(tmp_path):
    ev.merge(tmp_path, SID, [_entry()])
    before = (tmp_path / rua.PATH).read_bytes()
    with pytest.raises(rua.AliasError, match="already"):
        ev.merge(tmp_path, SID, [_entry(sha="2" * 64)])
    assert (tmp_path / rua.PATH).read_bytes() == before


def test_merge_refuses_what_load_would_refuse(tmp_path):
    with pytest.raises(rua.AliasError):
        ev.merge(tmp_path, SID, [_entry(), _entry(SPECIAL_MIN, REG_NEW)])
    assert not (tmp_path / rua.PATH).exists()


# --- the production fetch and the evidence-bound merge --------------------------------------------------------


class _Resp:
    status = 200
    headers = {"Content-Type": "application/pdf", "Content-Length": "6", "Last-Modified": "x", "ETag": "e"}

    def __init__(self, url):
        self.url = url

    def read(self, n):
        return b"%PDF-1"

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Gate:
    def __init__(self, refuse=()):
        self.opened, self.refuse = [], set(refuse)

    def open(self, request, *, timeout, handlers=(), hosts=None):
        import robots_gate

        self.opened.append((request.full_url, hosts))
        if request.full_url in self.refuse:
            raise robots_gate.RobotsDisallowed(request.full_url, {"rule": "Disallow: /"})
        return _Resp(request.full_url)


def test_the_gated_fetch_keeps_to_the_urls_host_spaces_requests_and_records_refusals():
    gate, slept, clock = _Gate(refuse=[REG_NEW]), [], iter([0.0, 1.0, 6.0])
    fetch = ev.gated_fetch(gate, sleep=slept.append, monotonic=lambda: next(clock), now=lambda: "T")
    data, meta = fetch(REG_OLD)
    assert data == b"%PDF-1" and meta["status"] == 200 and meta["content_type"] == "application/pdf"
    assert gate.opened[0] == (REG_OLD, frozenset({"storage.example"}))
    data, meta = fetch(REG_NEW)
    assert data is None and meta["error"].startswith("robots_disallowed")
    assert slept == [4.0]  # the agenda stage's 5 s between requests to one host


def test_merge_takes_only_entries_the_manifest_still_binds(world, tmp_path):
    _build(world, {REG_OLD: SIGNED, REG_NEW: SIGNED, SPECIAL_OLD: b"%PDF-1.7 s", SPECIAL_NEW: b"%PDF-1.7 s"})
    assert [e["record_id"] for e in ev._verified_entries(world["out"], SID)] == [REG_MIN, SPECIAL_MIN]
    with pytest.raises(ValueError, match="another source"):
        ev._verified_entries(world["out"], "another-city-council")
    text = next((world["out"] / "texts").glob("*.txt"))
    text.write_text("edited")
    with pytest.raises(ValueError, match="changed since the build"):
        ev._verified_entries(world["out"], SID)
    (world["out"] / "entries.yaml").write_text("format: 1\n")
    with pytest.raises(ValueError, match="entries.yaml"):
        ev._verified_entries(world["out"], SID)
