"""The review queue: government roles, name matching, classes B/A/C, ranking, resolution and review files.

Built over the fictional world (tests/identity_person_fixtures.py): Avery Quill controls a committee on the bucket
node itself (B); Robin Larkspur and Sam Osprey match government Persons on other nodes (A); Casey Thornbury has two
address clusters (C); Taylor Printwright is a payee who also gives.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import identity_person_decisions as dec  # noqa: E402
import identity_person_evidence as ev  # noqa: E402
import identity_person_key as ik  # noqa: E402
import identity_person_queue as iq  # noqa: E402
from tests.identity_person_fixtures import base_rows, build_world  # noqa: E402

KEY = ik.Key(1, bytes(range(32)))


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path)


def _evidence(w):
    return ev.collect(ev.Inputs(w.ledger_dir, w.raw_root, w.export_dir, w.decisions), KEY)


def _queue(evidence, *lines, latch=frozenset()):
    decisions = [dec.parse_line(t, n) for n, t in enumerate(lines, start=1)]
    targets = iq.target_fingerprints(KEY, evidence.graph, decisions)
    state = dec.effective_state(decisions, {r.row_id: r.fp for r in evidence.rows},
                                {r.row_id: r.moneyflow_id for r in evidence.rows}, targets, latch)
    return iq.build_queue(evidence, state, KEY, as_of="2026-10-12")


# --- names --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("donor, government, matches", [
    (("Larkspur", "Robin", None), "Robin Q. Larkspur", True),
    (("Larkspur", "Robin", None), "Larkspur, Robin Q", True),
    (("Larkspur", "R", None), "Robin Larkspur", True),  # an initial is compatible
    (("Larkspur", "Robin", None), "R. Larkspur", True),
    (("Larkspur", "Robin", None), "Robert Larkspur", False),
    (("Larkspur", "", None), "Robin Larkspur", False),  # no last-name-only matching
    (("Larkspur", "Robin", "Jr"), "Robin Larkspur Sr.", False),  # suffixes disagree
    (("Larkspur", "Robin", "Jr"), "Robin Larkspur", True),  # one side has no suffix
    (("Larkspur Jr", "Robin", None), "Robin Larkspur Jr.", True),  # a suffix inside the last name
    (("De La Cruz", "Maria", None), "Maria Elena De La Cruz", True),  # multi-token surname
    (("Cruz", "Maria", None), "Maria De La Cruz", True),  # still a token-suffix match: listed, Stuart decides
    (("De La Cruz", "Maria", None), "Maria Cruz", False),
    (("Larkspur", "Robin", None), "Larkspur Robin", False),  # no reordering without a comma
    (("Éclair", "José", None), "Jose Eclair", True),  # diacritics fold
    (("Larkspur", "Dr. Robin", None), "Robin Larkspur", True),  # titles drop
    (("Larkspur", "Robin", "VI"), "Robin Larkspur Jr.", False),  # an explicit suffix is kept, whatever it is
])
def test_name_matching(donor, government, matches):
    last, first, suffix = donor
    d = iq.donor_name({"last": last, "first": first, "suffix": suffix, "title": None})
    assert any(iq.name_matches(d, g) for g in iq.government_names({"name": government})) is matches


def test_aliases_are_matched_too():
    d = iq.donor_name({"last": "Osprey", "first": "Samuel", "suffix": None, "title": None})
    assert any(iq.name_matches(d, g) for g in iq.government_names({"name": "Sam Osprey",
                                                                    "aliases": ["Samuel Osprey"]}))


# --- classes and ranking ------------------------------------------------------------------------------------------

def test_classes_inclusive_and_assigned(world):
    q = _queue(_evidence(world))
    buckets = q.buckets
    assert buckets["person-quill-avery"].classes == ["B", "C"]
    assert buckets["person-quill-avery"].assigned == "B"
    assert buckets["person-larkspur-robin"].matches == ["person-robin-q-larkspur"]
    assert buckets["person-larkspur-robin"].assigned == "A"
    assert buckets["person-osprey-sam"].assigned == "A"
    assert buckets["person-thornbury-casey"].assigned == "C"
    assert buckets["person-fable-jordan"].assigned is None  # no usable address, no match
    assert buckets["person-printwright-taylor"].payee and buckets["person-printwright-taylor"].payee_only
    assert q.counts["inclusive"] == {"B": 1, "A": 2, "C": 3, "payee": 1, "payee_only": 1}
    assert q.counts["assigned"] == {"B": 1, "A": 2, "C": 1}


def test_payee_only_buckets_are_never_queued_even_when_they_qualify(world):
    q = _queue(_evidence(world))
    assert "C" in q.buckets["person-printwright-taylor"].classes  # two clusters: would be C
    assert not [i for i in q.items if i.bucket == "person-printwright-taylor"]
    assert q.counts["payee_only_would_be"] == {"C": 1}


def test_items_are_ordered_by_class_then_single_cluster_first_then_total(world):
    q = _queue(_evidence(world))
    assert [(i.cls, i.bucket, i.target) for i in q.items] == [
        ("B", "person-quill-avery", "person-quill-avery"),
        ("A", "person-larkspur-robin", "person-robin-q-larkspur"),  # one cluster, $1,300
        ("A", "person-osprey-sam", "person-sam-osprey"),  # one cluster, $150
        ("C", "person-thornbury-casey", None),
    ]
    assert q.items[1].total_cents == 130000


def test_clusters_are_labelled_by_first_appearance_and_rows_without_one_say_why(world):
    q = _queue(_evidence(world))
    quill = q.buckets["person-quill-avery"]
    assert [c.label for c in quill.clusters] == ["A", "B"] and [len(c.rows) for c in quill.clusters] == [2, 1]
    fable = {r.row_id: r for r in _evidence(world).rows if r.bucket == "person-fable-jordan"}
    labels = {rid: q.cluster_of(rid) for rid in fable}
    assert sorted(labels.values()) == ["— invalid_zip", "— placeholder_street"]


def test_c_takes_the_top_25_by_total(tmp_path):
    rows = base_rows()
    from tests.identity_person_fixtures import COUNCIL, MEASURE, _c
    for n in range(30):
        last = f"Donorson{chr(65 + n // 26)}{chr(65 + n % 26)}"
        rows["A-Contributions"] += [_c(COUNCIL, f"X-{n}", 100 + n, last, "Kim", "31\x20Invented Road"),
                                    _c(MEASURE, f"Y-{n}", 100, last, "Kim", "88\x20Madeup Drive")]
    q = _queue(_evidence(build_world(tmp_path, rows=rows)))
    c_items = [i for i in q.items if i.cls == "C"]
    assert len(c_items) == 25
    assert [i.total_cents for i in c_items] == sorted((i.total_cents for i in c_items), reverse=True)
    assert q.counts["inclusive"]["C"] == 33


def test_the_first_batch_holds_at_most_60_items(world):
    q = _queue(_evidence(world))
    assert q.batch == q.items[:60]


def test_queue_item_ids_are_stable_and_not_decision_digests(world):
    one, two = _queue(_evidence(world)), _queue(_evidence(world))
    assert [i.id for i in one.items] == [i.id for i in two.items]
    assert all(i.id.startswith("q-") for i in one.items)


# --- resolution ---------------------------------------------------------------------------------------------------

def _rows(evidence, bucket):
    return sorted((r for r in evidence.rows if r.bucket == bucket), key=lambda r: r.row_id)


def _line(kind, rows, **extra):
    return dec.decision_line(kind, [[r.row_id for r in rows]], {r.row_id: r.fp for r in rows}, "stuart",
                             "2026-10-12", **extra)


def test_an_is_over_every_row_resolves_its_item(world):
    e = _evidence(world)
    rows = _rows(e, "person-larkspur-robin")
    same = _line("same", rows)
    target_fp = dec.target_fingerprint(KEY, e.graph, "person-robin-q-larkspur")
    is_line = _line("is", rows, target="person-robin-q-larkspur", target_fp=target_fp,
                    basis=dec.parse_line(same, 1).digest)
    q = _queue(e, same, is_line)
    assert not [i for i in q.items if i.bucket == "person-larkspur-robin"]


def test_a_partial_is_leaves_the_item_open(world):
    e = _evidence(world)
    rows = _rows(e, "person-larkspur-robin")[:1]
    same = _line("same", rows)
    target_fp = dec.target_fingerprint(KEY, e.graph, "person-robin-q-larkspur")
    is_line = _line("is", rows, target="person-robin-q-larkspur", target_fp=target_fp,
                    basis=dec.parse_line(same, 1).digest)
    assert [i.bucket for i in _queue(e, same, is_line).items if i.cls == "A"][0] == "person-larkspur-robin"


def test_c_resolves_by_one_same_or_a_full_partition_but_not_by_covering_every_row(world):
    e = _evidence(world)
    rows = _rows(e, "person-thornbury-casey")
    a, b = [r for r in rows if r.tran_id == "A-4"], [r for r in rows if r.tran_id == "M-4"]
    open_c = lambda q: [i for i in q.items if i.cls == "C"]  # noqa: E731
    assert open_c(_queue(e, _line("same", a), _line("same", b)))  # every row covered, relation unanswered
    assert not open_c(_queue(e, _line("same", rows)))
    distinct = dec.decision_line("distinct", [[a[0].row_id], [b[0].row_id]],
                                 {r.row_id: r.fp for r in rows}, "stuart", "2026-10-12")
    assert not open_c(_queue(e, distinct))
    assert not open_c(_queue(e, dec.decision_line("defer", [[r.row_id for r in rows]],
                                                  {r.row_id: r.fp for r in rows}, "stuart", "2026-10-12")))


def test_stale_and_conflicting_decisions_come_back_first(world):
    e = _evidence(world)
    rows = _rows(e, "person-thornbury-casey")
    same = _line("same", rows)
    distinct = dec.decision_line("distinct", [[rows[0].row_id], [rows[1].row_id]],
                                 {r.row_id: r.fp for r in rows}, "stuart", "2026-10-12")
    q = _queue(e, same, distinct)
    assert q.items[0].cls == "conflict" and set(q.items[0].decisions) == {
        dec.parse_line(same, 1).digest, dec.parse_line(distinct, 1).digest}
    latched = _queue(e, same, latch=frozenset({dec.parse_line(same, 1).digest}))
    assert latched.items[0].cls == "stale"


# --- review files -------------------------------------------------------------------------------------------------

def test_the_review_shows_every_required_field_and_lines_that_ingest_as_written(world):
    e = _evidence(world)
    q = _queue(e)
    text = iq.render_batch(q, e)
    item = q.items[1]  # Larkspur -> the Form 700 filer
    assert item.id in text and "person-robin-q-larkspur" in text
    for needed in ("Larkspur, Robin Q", "form700_filer", "filing-form700-example-2024-larkspur", "2024-03-01",
                   "may themselves be name-joined", "no government-side address source",
                   "multiple address clusters do not show different people", "Exampleton", "94901"):
        assert needed.lower() in text.lower(), needed
    lines = iq.template_lines(q, e, item)
    decisions = [dec.parse_line(t, n) for n, t in enumerate(lines, start=1)]
    assert {d.kind for d in decisions} >= {"same", "is", "reject", "defer"}
    assert q.completeness["missing_without_reason"] == 0


def test_generic_employers_are_tagged_as_not_evidence(tmp_path):
    rows = base_rows()
    for row in rows["A-Contributions"]:
        if row["Tran_NamL"] == "Larkspur":
            row["Tran_Emp"], row["Tran_Occ"] = "Retired", "Self-Employed"
    e = _evidence(build_world(tmp_path, rows=rows))
    text = iq.render_batch(_queue(e), e)
    assert "Retired (generic — not evidence)" in text and "Self-Employed (generic — not evidence)" in text


def test_the_review_never_shows_a_street_or_hash(world):
    from tests.identity_person_fixtures import assert_no_street
    e = _evidence(world)
    q = _queue(e)
    text = iq.render_batch(q, e) + json.dumps(iq.queue_json(q))
    assert_no_street(text)
    assert not any(r.address_hash and r.address_hash in text for r in e.rows)


def test_c_resolution_follows_same_chains_through_rows_outside_the_bucket(world):
    e = _evidence(world)
    rows = _rows(e, "person-thornbury-casey")
    other = _rows(e, "person-fable-jordan")[0]
    fps = {r.row_id: r.fp for r in [*rows, other]}
    chain = [dec.decision_line("same", [[rows[0].row_id, other.row_id]], fps, "stuart", "2026-10-12"),
             dec.decision_line("same", [[other.row_id, rows[1].row_id]], fps, "stuart", "2026-10-12")]
    assert not [i for i in _queue(e, *chain).items if i.cls == "C"]


def test_the_each_cluster_option_makes_every_cluster_a_person(world):
    e = _evidence(world)
    q = _queue(e)
    item = next(i for i in q.items if i.cls == "C")
    lines = dict(iq.template_options(q, e, item))["Each address cluster is a different person"]
    kinds = [json.loads(t)["kind"] for t in lines]
    assert kinds == ["same", "same", "distinct"]  # two singleton clusters: each still gets its same
    q2 = _queue(e, *lines)
    assert len(q2.state.persons) == 2


def test_the_only_cluster_option_records_the_partition_too(world):
    e = _evidence(world)
    q = _queue(e)
    item = q.items[0]  # Quill (B), clusters A and B
    lines = dict(iq.template_options(q, e, item))[
        "Only cluster A (2 rows) is person-quill-avery; the other rows are not"]
    assert [json.loads(t)["kind"] for t in lines] == ["same", "is", "distinct", "reject"]
    assert not [i for i in _queue(e, *lines).items if i.bucket == "person-quill-avery"]


def test_government_facts_render_allowlisted_provenance_only(tmp_path):
    w = build_world(tmp_path)
    nodes = [json.loads(t) for t in (w.export_dir / "nodes.jsonl").read_text().splitlines()]
    for n in nodes:
        if n["id"] == "person-robin-q-larkspur":
            n["properties"].update(source_bundle_ids=["example-bundle"], home_address="12\x20Sample Street")
    (w.export_dir / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    edges = [json.loads(t) for t in (w.export_dir / "edges.jsonl").read_text().splitlines()]
    for edge in edges:
        if edge["type"] == "CONTROLLED_BY":
            edge["properties"].update(mailing_address="400\x20Example Avenue", resolved_by="12\x20Sample Street")
        if edge["type"] == "FILED_BY" and edge["end_id"] == "person-robin-q-larkspur":
            edge["properties"].update(source="form700-index")
    (w.export_dir / "edges.jsonl").write_text("".join(json.dumps(x) + "\n" for x in edges))
    e = _evidence(w)
    text = iq.render_batch(_queue(e), e)
    from tests.identity_person_fixtures import assert_no_street
    assert_no_street(text)
    assert "source bundles: 1" in text and "form700-index" not in text
    assert "resolved_by: withheld (not a code identifier)" in text


@pytest.mark.parametrize("props, shown", [
    ({"resolved_by": "resolve_committee_candidates"}, "resolved_by: resolve_committee_candidates"),
    ({"resolved_by": "Twelve Sample Ridge"}, "resolved_by: withheld (not a code identifier)"),
    ({"resolved_by": "twelve_b_sample"}, "resolved_by: twelve_b_sample"),  # an identifier is shown as code
    ({"resolved_by": "12b-sample-ridge"}, "resolved_by: withheld (not a code identifier)"),
    ({"vote": "aye"}, "vote: aye"),
    ({"vote": "Sample Ridge"}, "vote: withheld (not a vote)"),
    ({"vote": ["aye"]}, "vote: withheld (not a vote)"),
    ({"source_bundle_ids": [12, "Sample Ridge"]}, "source bundles: 2"),
    ({"candidate_name": "Twelve Sample Ridge", "mailing": "12 Sample Ridge"}, "no provenance recorded"),
    ({"promotion_state": ""}, "no provenance recorded"),  # an empty value is no value
])
def test_provenance_renders_only_closed_form_fields(props, shown):
    assert iq._provenance(props) == shown


def test_every_government_fact_is_listed(tmp_path):
    w = build_world(tmp_path)
    with open(w.export_dir / "nodes.jsonl", "a") as f:
        for n in range(8):
            f.write(json.dumps({"id": f"decision-extra-{n}", "labels": ["Decision"], "properties": {}}) + "\n")
    with open(w.export_dir / "edges.jsonl", "a") as f:
        for n in range(8):
            f.write(json.dumps({"start_id": "person-sam-osprey", "end_id": f"decision-extra-{n}",
                                "type": "CAST_VOTE", "properties": {"vote": "aye"}}) + "\n")
    e = _evidence(w)
    text = iq.render_batch(_queue(e), e)
    assert all(f"decision-extra-{n}" in text for n in range(8))


def test_c_resolution_checks_distinct_against_whole_components(world):
    e = _evidence(world)
    a, b = _rows(e, "person-thornbury-casey")
    x, y = _rows(e, "person-fable-jordan")
    fps = {r.row_id: r.fp for r in (a, b, x, y)}
    lines = [dec.decision_line("same", [[a.row_id, x.row_id]], fps, "stuart", "2026-10-12"),
             dec.decision_line("same", [[b.row_id, y.row_id]], fps, "stuart", "2026-10-12"),
             dec.decision_line("distinct", [[x.row_id], [y.row_id]], fps, "stuart", "2026-10-12")]
    assert not [i for i in _queue(e, *lines).items if i.cls == "C"]


@pytest.mark.parametrize("value", ["12 Sample Ridge", "Unit 3", {"street": "Example"}, ["ok", "12 Sample Ridge"],
                                   "#4", "PO Box 12", " 12 Sample Ridge", "address: 12 Sample Ridge", 4155550100,
                                   "Sample Ridge 12", "address: 12B Sample Ridge", "Sample Ridge Apt 12B",
                                   "12½ Sample Ridge"])
def test_address_like_or_structured_names_are_withheld(value):
    assert iq._safe(value).startswith("withheld")


@pytest.mark.parametrize("value", ["Avery Quill", "Larkspur, Robin Q", ["Samuel Osprey", "Sam Osprey"],
                                   "Friends of Example for Council"])
def test_plain_names_are_shown(value):
    assert not iq._safe(value).startswith("withheld")


@pytest.mark.parametrize("value, shown", [("2026-10-12", True), ("2026-10-12T09:30:00Z", True),
                                          ("2026-10-12 2025550100", False), ("12 Sample Ridge", False), (20261012, False)])
def test_dates_are_parsed_strictly(value, shown):
    assert (iq._date(value) == value) is shown


def test_overlap_audit_keys_come_from_a_fixed_vocabulary(tmp_path):
    w = build_world(tmp_path)
    with open(w.export_dir / "nodes.jsonl", "a") as f:
        f.write(json.dumps({"id": "moneyflow-odd", "labels": ["MoneyFlow"],
                            "properties": {"flow_type": "12 Sample Ridge"}}) + "\n")
    with open(w.export_dir / "edges.jsonl", "a") as f:
        f.write(json.dumps({"start_id": "moneyflow-odd", "end_id": "person-larkspur-robin", "type": "WEIRD 12 Sample",
                            "properties": {}}) + "\n")
    e = _evidence(w)
    keys = json.dumps(_queue(e).counts["overlap"])
    assert "Sample" not in keys and "in:other:MoneyFlow:other" in keys


def test_a_filed_at_that_is_not_a_date_is_withheld(tmp_path):
    w = build_world(tmp_path)
    nodes = [json.loads(t) for t in (w.export_dir / "nodes.jsonl").read_text().splitlines()]
    for n in nodes:
        if n["id"] == "filing-form700-example-2024-larkspur":
            n["properties"]["filed_at"] = "12 Sample Ridge"
    (w.export_dir / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    e = _evidence(w)
    text = iq.render_batch(_queue(e), e)
    assert "Sample Ridge" not in text and "filed_at withheld (not a date)" in text


def test_a_controlled_committee_is_named_even_with_an_election_year(world):
    e = _evidence(world)
    text = iq.render_batch(_queue(e), e)
    assert "committee-netfile-1400001 (Friends of Example for Council 2024)" in text
