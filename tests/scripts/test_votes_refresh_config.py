"""Votes refresh, increment c: `init` verifies the reviewed roster once, offline, against its pinned evidence, and
authenticates the B2 apply record; every later load re-checks the pinned bytes only. Fictional world."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import votes_refresh_ledger as rl  # noqa: E402
from votes_inventory import build_inventory, write_inventory  # noqa: E402

BOS, NOV = "marin-county-bos", "novato-city-council"


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _term(body, key, source, quote):
    return {"draft_id": f"{body[:3]}-{key.lower()}", "member": f"Pat {key.title()}", "key": key,
            "seat": "District 1", "start": "2019-01-01", "end": None, "start_kind": "window", "basis": "x",
            "confidence": "high", "notes": "",
            "evidence": [{"source": source, "quote": quote, "supports": ["start", "seat"]}]}


@pytest.fixture
def world(tmp_path):
    raw = tmp_path / "raw"
    nodes, edges, terms = [], [], {}
    for body, n in ((BOS, "1"), (NOV, "2")):
        mid = f"meeting-{body}-{n}"
        (raw / body / "minutes").mkdir(parents=True)
        (raw / body / "minutes" / f"{mid}.html").write_bytes(
            f"<html><body><p>Supervisor Alder of District 1 was sworn in on that day ({body}).</p></body></html>"
            .encode())
        nodes.append({"id": mid, "labels": ["Meeting"], "properties": {"id": mid, "meeting_date": "2020-01-07",
                                                                        "title": "Council"}})
        terms[body] = [_term(body, "ALDER", f"minutes:{mid}", "Supervisor Alder of District 1 was sworn in")]
    export = tmp_path / "export"
    export.mkdir()
    (export / "nodes.jsonl").write_text("".join(json.dumps(x) + "\n" for x in nodes))
    (export / "edges.jsonl").write_text("")
    part_a = tmp_path / "votes"
    inv = build_inventory(export, raw, tmp_path / "fetched", {BOS: ("2019-01-01", "2026-03-20"),
                                                              NOV: ("2019-01-01", "2026-03-10")})
    write_inventory(inv, part_a / "inventory")
    roster = part_a / "roster"
    roster.mkdir()
    drafts = {b: {"body": b, "terms": t} for b, t in terms.items()}
    (roster / "drafts.json").write_text(json.dumps(drafts))
    items = [{"item": str(i + 1), "draft_id": t["draft_id"], "body": b}
             for i, (b, t) in enumerate((b, t) for b in sorted(drafts) for t in drafts[b]["terms"])]
    (roster / "batch-001.json").write_text(json.dumps({"batch": "roster-001", "items": items}))
    (roster / "answers-001.txt").write_text("batch roster-001\n" + "".join(f"{i['item']} confirm\n" for i in items))
    (part_a / "ledger").mkdir()
    (part_a / "ledger" / "build.json").write_text(json.dumps({"roster_drafts_sha256": _sha(roster / "drafts.json"),
                                                              "inventory": str(part_a / "inventory")}))
    # B2: mapping + the applied plan that created one Person
    vb = tmp_path / "votes-b"
    (vb / "mapping").mkdir(parents=True)
    rows = [{"item": i["item"], "draft_id": i["draft_id"], "body": i["body"], "key": "ALDER", "member": "Pat Alder",
             "term_start": "2019-01-01", "term_end": None, "status": "mapped", "person_id": "person-pat-alder",
             "provenance": [], "alternates": [], "reviewer_basis": "fixture", "notes": ""} for i in items]
    (vb / "mapping" / "mapping.json").write_text(json.dumps({"batch": "map-001", "rows": rows}))
    hashes = {"mapping.json": _sha(vb / "mapping/mapping.json"), "drafts.json": _sha(roster / "drafts.json"),
              "batch-001.json": _sha(roster / "batch-001.json"), "answers-001.txt": _sha(roster / "answers-001.txt")}
    (vb / "mapping" / "batch-map-001.json").write_text(json.dumps({
        "batch": "map-001", "inputs": hashes,
        "items": [{"item": r["item"], "draft_id": r["draft_id"], "options": ["confirm"]} for r in rows]}))
    (vb / "mapping" / "answers-map-001.txt").write_text("batch map-001\n" + "".join(f"{r['item']} confirm\n"
                                                                                     for r in rows))
    (vb / "plan").mkdir()
    (vb / "plan" / "ops.json").write_text(json.dumps({"add_nodes": [
        {"id": "person-pat-new", "labels": ["Person"], "properties": {"id": "person-pat-new", "name": "Pat New"}},
        {"id": "vev-x", "labels": ["Decision"], "properties": {}}]}))
    (vb / "plan" / "approval-inputs.json").write_text(json.dumps({"files": {"plan/ops.json": {
        "path": str(vb / "plan/ops.json"), "sha256": _sha(vb / "plan/ops.json")}}}))
    (vb / "state.json").write_text(json.dumps({"state": "APPLIED",
                                               "approval_sha256": _sha(vb / "plan/approval-inputs.json")}))
    return tmp_path / "refresh", part_a, vb


class TestInit:
    def test_init_verifies_and_pins(self, world):
        refresh, part_a, vb = world
        cfg = rl.init_config(refresh, part_a=part_a, votes_b=vb)
        assert cfg["verification"] == {BOS: [], NOV: []}
        assert cfg["applied_persons"] == ["person-pat-new"]
        loaded = rl.load_config(refresh)
        assert set(loaded["drafts"]) == {BOS, NOV} and loaded["applied_persons"] == ["person-pat-new"]
        assert len(loaded["mapping_answers"]) == 2

    def test_changed_evidence_refuses_init(self, world):
        refresh, part_a, vb = world
        f = next((part_a.parent / "raw" / BOS / "minutes").iterdir())
        f.write_bytes(b"<html><body><p>Something else entirely.</p></body></html>")
        with pytest.raises(rl.AdapterError, match="sha256|quote"):
            rl.init_config(refresh, part_a=part_a, votes_b=vb)

    def test_a_missing_evidence_reference_refuses_init(self, world):
        refresh, part_a, vb = world
        d = json.loads((part_a / "roster/drafts.json").read_text())
        d[NOV]["terms"][0]["evidence"][0]["source"] = "minutes:meeting-novato-city-council-999"
        (part_a / "roster/drafts.json").write_text(json.dumps(d))
        (part_a / "ledger/build.json").write_text(json.dumps({"roster_drafts_sha256": _sha(part_a / "roster/drafts.json")}))
        with pytest.raises(rl.AdapterError, match="does not resolve"):
            rl.init_config(refresh, part_a=part_a, votes_b=vb)

    def test_drafts_not_the_ones_part_a_built_with(self, world):
        refresh, part_a, vb = world
        (part_a / "ledger/build.json").write_text(json.dumps({"roster_drafts_sha256": "0" * 64}))
        with pytest.raises(rl.AdapterError, match="build.json"):
            rl.init_config(refresh, part_a=part_a, votes_b=vb)

    def test_an_unapplied_or_unauthenticated_b2_record_refuses(self, world):
        refresh, part_a, vb = world
        (vb / "state.json").write_text(json.dumps({"state": "AWAITING_APPLY", "approval_sha256": "x"}))
        with pytest.raises(rl.AdapterError, match="B2"):
            rl.init_config(refresh, part_a=part_a, votes_b=vb)
        (vb / "state.json").write_text(json.dumps({"state": "APPLIED", "approval_sha256": "0" * 64}))
        with pytest.raises(rl.AdapterError, match="B2"):
            rl.init_config(refresh, part_a=part_a, votes_b=vb)

    def test_a_pinned_file_changed_after_init_refuses_load(self, world):
        refresh, part_a, vb = world
        rl.init_config(refresh, part_a=part_a, votes_b=vb)
        with open(vb / "mapping/answers-map-001.txt", "a") as fh:
            fh.write("# edited\n")
        with pytest.raises(rl.AdapterError, match="answers-map-001.txt"):
            rl.load_config(refresh)


def test_agenda_and_web_evidence_are_pinned_and_rechecked(world):
    refresh, part_a, vb = world
    web = part_a / "roster" / "sources" / "web" / "page.html"
    web.parent.mkdir(parents=True)
    web.write_text("<html><body><p>Pat Alder took office in District 1 that year.</p></body></html>")
    d = json.loads((part_a / "roster/drafts.json").read_text())
    d[NOV]["terms"][0]["evidence"].append({"source": "web:web/page.html", "quote": "Pat Alder took office in District 1",
                                           "supports": ["seat"]})
    (part_a / "roster/drafts.json").write_text(json.dumps(d))
    _rebind(part_a, vb)
    cfg = rl.init_config(refresh, part_a=part_a, votes_b=vb)
    assert "source/web:web/page.html" in cfg["files"]
    web.write_text("<html><body><p>changed</p></body></html>")
    with pytest.raises(rl.AdapterError, match="web:web/page.html"):
        rl.load_config(refresh)
    web.unlink()
    with pytest.raises(rl.AdapterError, match="web:web/page.html"):
        rl.load_config(refresh)


def _rebind(part_a, vb):
    """Re-point Part A's build record and the mapping batch at edited drafts (a fixture shortcut)."""
    (part_a / "ledger/build.json").write_text(json.dumps({"roster_drafts_sha256": _sha(part_a / "roster/drafts.json")}))
    batch = json.loads((vb / "mapping/batch-map-001.json").read_text())
    batch["inputs"]["drafts.json"] = _sha(part_a / "roster/drafts.json")
    (vb / "mapping/batch-map-001.json").write_text(json.dumps(batch))
