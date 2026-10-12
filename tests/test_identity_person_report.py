"""The operator report: per effective person cross-committee totals over distinct flows; per bucket its clusters;
queue, stale and conflict counts. Private directory only; never a street or hash."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import identity_person_decisions as dec  # noqa: E402
import identity_person_evidence as ev  # noqa: E402
import identity_person_key as ik  # noqa: E402
import identity_person_queue as iq  # noqa: E402
import identity_person_report as rep  # noqa: E402
from tests.identity_person_fixtures import assert_no_street, build_world  # noqa: E402

KEY = ik.Key(1, bytes(range(32)))


def _setup(tmp_path, lines_for):
    w = build_world(tmp_path)
    e = ev.collect(ev.Inputs(w.ledger_dir, w.raw_root, w.export_dir, w.decisions), KEY)
    decisions = [dec.parse_line(t, n) for n, t in enumerate(lines_for(e), start=1)]
    state = dec.effective_state(decisions, {r.row_id: r.fp for r in e.rows},
                                {r.row_id: r.moneyflow_id for r in e.rows},
                                iq.target_fingerprints(KEY, e.graph, decisions))
    q = iq.build_queue(e, state, KEY, "2026-10-12")
    return e, q, rep.build_report(q, e)


def _same(e, *buckets):
    rows = [r for r in e.rows if r.bucket in buckets]
    return dec.decision_line("same", [[r.row_id for r in rows]], {r.row_id: r.fp for r in rows}, "stuart",
                             "2026-10-12")


def test_person_totals_cross_committees_over_distinct_flows(tmp_path):
    e, q, report = _setup(tmp_path, lambda e: [_same(e, "person-quill-avery"), _same(e, "person-vale-morgan")])
    people = {p["label"]: p for p in report["persons"]}
    assert len(people) == 2
    quill = next(p for p in people.values() if p["buckets"] == ["person-quill-avery"])
    assert quill["total_cents"] == 85000 and quill["committees"] == 2 and quill["flows"] == 3
    vale = next(p for p in people.values() if p["buckets"] == ["person-vale-morgan"])
    assert vale["rows"] == 2 and vale["flows"] == 1 and vale["total_cents"] == 60000  # one flow, counted once


def test_every_scoped_bucket_lists_its_clusters(tmp_path):
    e, q, report = _setup(tmp_path, lambda e: [])
    buckets = {b["id"]: b for b in report["buckets"]}
    assert set(buckets) == {r.bucket for r in e.rows}
    assert [(c["label"], c["rows"]) for c in buckets["person-quill-avery"]["clusters"]] == [("A", 2), ("B", 1)]
    assert buckets["person-fable-jordan"]["clusters"] == []
    assert buckets["person-fable-jordan"]["unclustered"] == {"invalid_zip": 1, "placeholder_street": 1}


def test_counts_and_markdown_hold_no_street_or_hash(tmp_path):
    e, q, report = _setup(tmp_path, lambda e: [])
    text = rep.render_report(report)
    assert report["queue"]["items"] == {"A": 2, "B": 1, "C": 1}
    assert "Queue" in text and "person-thornbury-casey" in text
    assert_no_street(text)
    assert not any(r.address_hash and r.address_hash in text for r in e.rows)


def test_the_report_names_rows_by_opaque_id_never_by_transaction_text(tmp_path):
    from tests.identity_person_fixtures import base_rows
    rows = base_rows()
    for row in rows["A-Contributions"]:
        if row["Tran_NamL"] == "Quill":
            row["Tran_ID"] = row["Tran_ID"] + " 12 Sample Ridge"
    w = build_world(tmp_path / "odd", rows=rows)
    e = ev.collect(ev.Inputs(w.ledger_dir, w.raw_root, w.export_dir, w.decisions), KEY)
    rows_q = [r for r in e.rows if r.bucket == "person-quill-avery"]
    line = dec.decision_line("same", [[r.row_id for r in rows_q]], {r.row_id: r.fp for r in rows_q}, "stuart",
                             "2026-10-12")
    d = [dec.parse_line(line, 1)]
    state = dec.effective_state(d, {r.row_id: r.fp for r in e.rows}, {r.row_id: r.moneyflow_id for r in e.rows},
                                iq.target_fingerprints(KEY, e.graph, d))
    report = rep.build_report(iq.build_queue(e, state, KEY, "2026-10-12"), e)
    text = json.dumps(report) + rep.render_report(report)
    assert "Sample Ridge" not in text
