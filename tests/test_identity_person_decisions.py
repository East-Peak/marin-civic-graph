"""The decision file: line grammar, staleness, the stale latch, `is` dependencies and contradictions.

Rows and fingerprints here are synthetic (valid shapes, no world needed); tests/test_identity_person_flow.py runs the
same rules end to end over the fictional world.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import identity_person_decisions as dec  # noqa: E402
import identity_person_evidence as ev  # noqa: E402
import identity_person_key as ik  # noqa: E402
from tests.identity_person_fixtures import build_world  # noqa: E402


def rid(n: int) -> str:
    return "r-" + hashlib.sha256(str(n).encode()).hexdigest()[:20]


def fp(n: int, salt: str = "", version: int = 1) -> str:
    digest = hashlib.sha256(f"{n}{salt}".encode()).hexdigest()
    fields = ".".join(hashlib.sha256(f"{n}{salt}{f}".encode()).hexdigest()[:8] for f in ev.FP_FIELDS)
    return f"fp1:k{version}:{digest}:{fields}"


def tf(name: str) -> str:
    return "tf1:k1:" + hashlib.sha256(name.encode()).hexdigest()


A, B, C, D = rid(1), rid(2), rid(3), rid(4)
ROWS = {r: fp(i) for i, r in enumerate((A, B, C, D), start=1)}
FLOWS = {A: "moneyflow-1", B: "moneyflow-2", C: "moneyflow-3", D: "moneyflow-4"}
TARGETS = {"person-gov-x": tf("x"), "person-gov-y": tf("y")}


def line(kind, groups, target=None, basis=None, note=None, rows=ROWS, targets=TARGETS, **extra) -> str:
    groups = sorted(sorted(g) for g in groups)
    obj = {"v": 1, "kind": kind, "groups": groups, "fp": {r: rows[r] for g in groups for r in g},
           "reviewer": "stuart", "date": "2026-10-12", **extra}
    if target:
        obj.update(target=target, target_fp=targets.get(target, tf("gone")))
    if basis:
        obj["basis"] = basis
    if note:
        obj["note"] = note
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def parse(*lines):
    return [dec.parse_line(text, n) for n, text in enumerate(lines, start=1)]


def state(*lines, rows=ROWS, flows=FLOWS, targets=TARGETS, latch=frozenset()):
    return dec.effective_state(parse(*lines), rows, flows, targets, latch)


# --- grammar ------------------------------------------------------------------------------------------------------

def test_a_canonical_same_line_parses_and_has_a_stable_digest():
    text = line("same", [[A, B]])
    d = dec.parse_line(text, 1)
    assert (d.kind, d.groups, d.rows) == ("same", ((A, B),), frozenset({A, B}))
    assert d.digest == "d-" + hashlib.sha256(text.encode()).hexdigest()[:16]
    spaced = json.dumps(json.loads(text), indent=1)
    assert dec.parse_line(spaced.replace("\n", " "), 1).digest == d.digest


@pytest.mark.parametrize("mutate, says", [
    (lambda o: o.update(kind="merge"), "kind"),
    (lambda o: o.update(v=2), "v"),
    (lambda o: o.update(extra=1), "unknown"),
    (lambda o: o.pop("reviewer"), "reviewer"),
    (lambda o: o.update(reviewer="Stuart Example"), "reviewer"),
    (lambda o: o.update(date="12/10/2026"), "date"),
    (lambda o: o.update(groups=[[B, A]]), "sorted"),
    (lambda o: o.update(groups=[[A], [A]]), "twice"),
    (lambda o: o.update(groups=[[]]), "empty"),
    (lambda o: o.update(groups=[["r-nothex"]]), "row id"),
    (lambda o: o.update(groups=sorted([[A, B], [C]])), "one group"),
    (lambda o: o["fp"].pop(B), "fp"),
    (lambda o: o["fp"].update({C: ROWS[C]}), "fp"),
    (lambda o: o["fp"].update({A: "fp1:k1:abc"}), "fp"),
    (lambda o: o.update(note="12 Sample Street"), "note"),
    (lambda o: o.update(note="One Sample Street"), "note"),
    (lambda o: o.update(target="person-gov-x"), "target"),
])
def test_malformed_lines_are_rejected_by_line_number(mutate, says):
    obj = json.loads(line("same", [[A, B]]))
    mutate(obj)
    with pytest.raises(dec.DecisionError, match=rf"line 7: .*{says}"):
        dec.parse_line(json.dumps(obj), 7)


def test_not_json_is_rejected_without_echoing_the_line():
    with pytest.raises(dec.DecisionError, match="line 3: not a JSON object") as info:
        dec.parse_line('{"note": "12 Sample Street"', 3)
    assert "Sample" not in str(info.value)


@pytest.mark.parametrize("kind, groups, target, basis, ok", [
    ("distinct", [[A], [B]], None, None, True),
    ("distinct", [[A, B]], None, None, False),
    ("is", [[A]], "person-gov-x", "d-" + "0" * 16, True),
    ("is", [[A]], "person-gov-x", None, False),
    ("is", [[A]], None, "d-" + "0" * 16, False),
    ("reject", [[A]], "person-gov-x", None, True),
    ("reject", [[A], [B]], "person-gov-x", None, False),
    ("defer", [[A], [B]], None, None, True),
    ("defer", [[A]], "person-gov-x", None, True),
    ("same", [[A]], None, "d-" + "0" * 16, False),
])
def test_kind_arity(kind, groups, target, basis, ok):
    text = line(kind, groups, target=target, basis=basis)
    if ok:
        assert dec.parse_line(text, 1).kind == kind
    else:
        with pytest.raises(dec.DecisionError):
            dec.parse_line(text, 1)


def test_note_codes_are_enumerated():
    assert dec.parse_line(line("same", [[A, B]], note="household_namesake"), 1).note == "household_namesake"


def test_a_file_with_a_duplicate_line_is_rejected(tmp_path):
    path = tmp_path / "decisions.jsonl"
    path.write_text(line("same", [[A, B]]) + "\n\n# comment\n" + line("same", [[A, B]]) + "\n")
    with pytest.raises(dec.DecisionError, match="line 4: duplicates line 1"):
        dec.load_decisions(path)


def test_an_empty_or_missing_file_holds_no_decisions(tmp_path):
    assert dec.load_decisions(tmp_path / "missing.jsonl") == []
    (tmp_path / "empty.jsonl").write_text("")
    assert dec.load_decisions(tmp_path / "empty.jsonl") == []


# --- staleness and the latch --------------------------------------------------------------------------------------

def test_a_current_same_is_effective_and_forms_a_person():
    s = state(line("same", [[A, B]]))
    [d] = s.decisions
    assert s.status[d.digest] == "effective"
    assert [sorted(p.rows) for p in s.persons] == [sorted([A, B])]


def changed(fingerprint: str, field: str) -> str:
    """The same row's fingerprint after only `field` changed: a new row HMAC and that field's new digest."""
    prefix, version, _, fields = fingerprint.split(":")
    digests = fields.split(".")
    digests[ev.FP_FIELDS.index(field)] = "ffffffff"
    return f"{prefix}:{version}:{'e' * 64}:{'.'.join(digests)}"


def test_a_changed_row_makes_the_decision_stale_with_its_field_diff():
    s = state(line("same", [[A, B]]), rows={**ROWS, B: changed(ROWS[B], "address")})
    [d] = s.decisions
    assert s.status[d.digest] == "stale"
    assert s.stale[d.digest] == {B: ["address"]}
    assert s.persons == []


def test_a_row_amended_away_makes_the_decision_stale():
    current = {r: f for r, f in ROWS.items() if r != B}
    s = state(line("same", [[A, B]]), rows=current)
    assert list(s.stale.values()) == [{B: ["row gone"]}]


def test_a_latched_decision_stays_stale_even_when_the_evidence_returns():
    text = line("same", [[A, B]])
    digest = dec.parse_line(text, 1).digest
    s = state(text, latch=frozenset({digest}))
    assert s.status[digest] == "stale" and s.stale[digest] == {"latched": ["evidence changed since review"]}


def test_the_new_latch_holds_every_stale_line_still_in_the_file_and_nothing_else():
    keep, gone = line("same", [[A, B]]), line("same", [[C, D]])
    current = {**ROWS, C: fp(3, "changed")}
    s = state(keep, gone, rows=current, latch=frozenset({"d-" + "1" * 16}))
    assert s.latch == frozenset({dec.parse_line(gone, 1).digest})


# --- `is` and its basis -------------------------------------------------------------------------------------------

def _same_and_is(rows=(A, B), target="person-gov-x"):
    same = line("same", [list(rows)])
    return same, line("is", [list(rows)], target=target, basis=dec.parse_line(same, 1).digest)


def test_an_is_on_its_basis_same_is_effective_and_labels_the_person():
    s = state(*_same_and_is())
    assert set(s.status.values()) == {"effective"}
    assert [(p.target, sorted(p.rows)) for p in s.persons] == [("person-gov-x", sorted([A, B]))]


def test_an_is_without_its_basis_is_suspended():
    _, is_line = _same_and_is()
    s = state(is_line)
    assert s.suspended == {dec.parse_line(is_line, 1).digest: "no_covering_same"}


def test_revoking_the_same_suspends_its_is_even_if_another_same_still_connects_the_rows():
    _, is_line = _same_and_is()
    s = state(is_line, line("same", [[A, B, C]]))
    assert s.suspended[dec.parse_line(is_line, 1).digest] == "no_covering_same"


def test_an_is_whose_basis_is_stale_is_suspended():
    same = line("same", [[A, B]])
    is_line = line("is", [[B]], target="person-gov-x", basis=dec.parse_line(same, 1).digest)
    s = state(same, is_line, rows={**ROWS, A: changed(ROWS[A], "employer")})
    assert s.status[dec.parse_line(same, 1).digest] == "stale"
    assert s.suspended == {dec.parse_line(is_line, 1).digest: "no_covering_same"}
    assert s.persons == []


def test_an_is_whose_basis_does_not_cover_its_rows_is_suspended():
    same = line("same", [[A, B]])
    is_line = line("is", [[A, B, C]], target="person-gov-x", basis=dec.parse_line(same, 1).digest)
    assert state(same, is_line).suspended == {dec.parse_line(is_line, 1).digest: "no_covering_same"}


def test_a_changed_or_removed_target_makes_the_is_stale():
    same, is_line = _same_and_is()
    changed = state(same, is_line, targets={"person-gov-x": tf("x renamed")})
    removed = state(same, is_line, targets={})
    for s in (changed, removed):
        assert s.status[dec.parse_line(is_line, 1).digest] == "stale"
        assert [p.target for p in s.persons] == [None]


# --- contradictions -----------------------------------------------------------------------------------------------

def test_same_and_distinct_over_the_same_rows_suspend_both_as_one_conflict():
    same, distinct = line("same", [[A, B]]), line("distinct", [[A], [B]])
    s = state(same, distinct)
    [conflict] = s.conflicts
    assert conflict.decisions == tuple(sorted(dec.parse_line(t, 1).digest for t in (same, distinct)))
    assert s.persons == [] and set(s.suspended.values()) == {conflict.id}


def test_a_flow_whose_rows_land_on_two_people_is_a_conflict_and_counts_for_nobody():
    flows = {**FLOWS, B: "moneyflow-1"}  # A and B are two physical rows of one flow
    s = state(line("same", [[A, C]]), line("same", [[B, D]]), flows=flows)
    [conflict] = s.conflicts
    assert "flow moneyflow-1" in conflict.reasons[0]
    assert s.persons == []


def test_one_person_with_two_targets_is_a_conflict():
    same = line("same", [[A, B]])
    basis = dec.parse_line(same, 1).digest
    s = state(same, line("is", [[A]], target="person-gov-x", basis=basis),
              line("is", [[B]], target="person-gov-y", basis=basis))
    assert len(s.conflicts) == 1 and s.persons == []


def test_reject_against_an_is_of_the_same_target_is_a_conflict():
    same, is_line = _same_and_is()
    s = state(same, is_line, line("reject", [[B]], target="person-gov-x"))
    assert len(s.conflicts) == 1 and s.persons == []


def test_overlapping_contradictions_merge_into_one_conflict_item():
    s = state(line("same", [[A, B]]), line("distinct", [[A], [B]]), line("distinct", [[A], [B, C]]))
    assert len(s.conflicts) == 1 and len(s.conflicts[0].decisions) == 3


def test_unrelated_decisions_stay_effective_beside_a_conflict():
    s = state(line("same", [[A, B]]), line("distinct", [[A], [B]]), line("same", [[C, D]]))
    assert [sorted(p.rows) for p in s.persons] == [sorted([C, D])]


def test_defer_never_conflicts_and_forms_no_person():
    s = state(line("defer", [[A], [B]]), line("same", [[A, B]]))
    assert s.conflicts == [] and len(s.persons) == 1


def test_a_flow_with_one_decided_row_counts_for_that_person_only():
    flows = {**FLOWS, B: "moneyflow-1"}
    s = state(line("same", [[A, C]]), flows=flows)
    [person] = s.persons
    assert s.flows_of(person) == ["moneyflow-1", "moneyflow-3"]


def test_the_state_is_deterministic_whatever_the_line_order():
    lines = [line("same", [[A, B]]), line("distinct", [[A], [B]]), line("same", [[C, D]])]
    one, two = state(*lines), state(*reversed(lines))
    assert (one.status, one.conflicts, one.persons) == (two.status, two.conflicts, two.persons)


# --- target fingerprints (over the fictional world's graph) -------------------------------------------------------

def test_target_fingerprints_cover_name_and_role_facts_but_not_new_filings(tmp_path):
    w = build_world(tmp_path)
    graph = ev.load_graph(w.export_dir)
    key = ik.Key(1, bytes(32))
    before = dec.target_fingerprint(key, graph, "person-robin-q-larkspur")
    assert before and before.startswith("tf1:k1:")
    graph.props["filing-form700-example-2025"] = {"filing_type": "form_700", "filer_name": "Larkspur, Robin Q"}
    graph.person_edges["person-robin-q-larkspur"].append(("in", "FILED_BY", "filing-form700-example-2025", {}))
    assert dec.target_fingerprint(key, graph, "person-robin-q-larkspur") == before
    graph.props["person-robin-q-larkspur"]["name"] = "Robin Larkspur-Quinn"
    assert dec.target_fingerprint(key, graph, "person-robin-q-larkspur") != before
    assert dec.target_fingerprint(key, graph, "person-printwright-taylor") is None  # a donor with no role
    assert dec.target_fingerprint(key, graph, "person-nobody") is None


# --- the line builder, the latch file and the build ---------------------------------------------------------------

def test_decision_line_builds_the_canonical_line_parse_line_accepts():
    text = dec.decision_line("distinct", [[B], [A]], {A: ROWS[A], B: ROWS[B]}, "stuart", "2026-10-12",
                             note="moved")
    d = dec.parse_line(text, 1)
    assert d.groups == tuple(sorted([(A,), (B,)])) and d.line == text


def test_the_latch_round_trips_sorted_and_private(tmp_path):
    private = tmp_path.resolve() / "private"
    private.mkdir(mode=0o700)
    assert dec.load_latch(private) == frozenset()
    dec.write_latch(private, frozenset({"d-" + "b" * 16, "d-" + "a" * 16}))
    path = private / "stale-latch.jsonl"
    assert path.read_text().splitlines() == ['"d-' + "a" * 16 + '"', '"d-' + "b" * 16 + '"']
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert dec.load_latch(private) == frozenset({"d-" + "a" * 16, "d-" + "b" * 16})


def _world_line(evidence, key, kind, tran_ids, filer=None, **extra):
    rows = [r for r in evidence.rows if r.tran_id in tran_ids and (filer is None or r.filer_id == filer)]
    return dec.decision_line(kind, [[r.row_id for r in rows]], {r.row_id: r.fp for r in rows}, "stuart",
                             "2026-10-12", **extra)


def test_build_reports_the_effective_state_and_latches_what_went_stale(tmp_path, monkeypatch, capsys):
    import identity_person as cli
    from tests.identity_person_fixtures import base_rows

    w = build_world(tmp_path / "w")
    monkeypatch.setenv(ik.ENV, str(w.private))
    cli.main(["init-key"])
    key = ik.load_key(w.private)
    evidence = ev.collect(ev.Inputs(w.ledger_dir, w.raw_root, w.export_dir, w.decisions), key)
    same = _world_line(evidence, key, "same", {"A-1", "A-2"})
    w.decisions.write_text(same + "\n")
    digest = dec.parse_line(same, 1).digest

    def build(world, out):
        assert cli.main(world.build_args(out=out)) == 0, capsys.readouterr()
        return json.loads((world.private / "builds" / out / "decisions-state.json").read_text())

    assert build(w, "one")["status"] == {digest: "effective"}
    rows = base_rows()
    rows["A-Contributions"][0]["Tran_Adr1"] = "400 Example Avenue"  # a re-download changes only the address
    moved = build_world(tmp_path / "moved", rows=rows, private=w.private)
    moved.decisions.write_text(same + "\n")
    state = build(moved, "two")
    assert state["status"] == {digest: "stale"}
    [changed] = state["stale"][digest].values()
    assert changed == ["address"]
    assert dec.load_latch(w.private) == frozenset({digest})
    assert build(w, "three")["status"] == {digest: "stale"}  # the evidence came back: still stale, latched
    manifest = json.loads((w.private / "builds" / "three" / "manifest.json").read_text())
    assert manifest["latch_sha256"] == __import__("hashlib").sha256(
        (json.dumps(digest) + "\n").encode()).hexdigest()
