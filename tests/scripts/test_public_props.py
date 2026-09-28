"""Tests for the per-type public property allowlist (substrate contract).

APP_READS is pinned from a grep of app/src (entity-facts, entity-temporal,
graph-engine ranking, explorer SUB_SPECS, data-queries-sql, browse columns,
search-backend-sql, entity-evidence, hero-title, editorial-callout,
path-finder-substrate). If the app starts reading a key, add it here AND to
the allowlist; this test is the tripwire that keeps them in step.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from bake_public_substrate import bake_substrate  # noqa: E402
from public_props import (  # noqa: E402
    BAKE_ONLY_PROPS,
    COMMON_PUBLIC_PROPS,
    PUBLIC_PROPS,
    SUPPORT_PUBLIC_PROPS,
    public_props,
)

PATH_EVENT_DATE_KEYS = (
    "meeting_date", "decided_at", "flow_date", "signed_at", "election_date",
    "occurred_at", "proceeding_date", "date", "effective_date", "filed_at",
    "started_at", "start_date", "parent_meeting_date", "published_at", "captured_at",
)
TYPE_AGNOSTIC_READS = (
    "name", "search_key_fact", "search_last_activity", "search_rank",
    "jurisdiction_name", "editorial_note", "editorial_blurb", "editorial",
    *PATH_EVENT_DATE_KEYS,
)
PLACE_JOIN_KEYS = ("primary_place_id", "jurisdiction_place_id", "place_ids")
ROLLUP_HERO = ("total_money", "decisions_count", "counterparties_count",
               "records_count", "evidence_count")

APP_READS: dict[str, tuple[str, ...]] = {
    "Person": ("name", "current_seat_display", "jurisdiction_name", "aliases",
               "current_seat_started_at", "service_start_date",
               "current_seat_ended_at", "service_end_date", "filings_count"),
    "Decision": ("decided_at", "institution_name", "vote_summary", "status",
                 "agenda_item_number", "item_number", "institution_id", "title"),
    "Project": ("name", "status", "address", "jurisdiction_name", *ROLLUP_HERO,
                *PLACE_JOIN_KEYS),
    "Program": ("name", "status", "program_type", "jurisdiction_name", *ROLLUP_HERO,
                *PLACE_JOIN_KEYS),
    "Case": ("caption", "name", "docket_number", "filed_at", "closed_at", "status",
             "court_name", "court", "constrains_count", *PLACE_JOIN_KEYS),
    "Meeting": ("title", "meeting_date", "institution_name", "meeting_type",
                "agenda_items_count", "decisions_count"),
    "Filing": ("filing_type", "signed_at", "period_start", "period_end",
               "filed_by_name", "filer_name", "candidate_name", "filed_by"),
    "Committee": ("name", "fppc_id", "treasurer", "candidate_name",
                  "elections_count", "total_money_in"),
    "Organization": ("name", "subtype", "labels", "jurisdiction_name", "website"),
    "MoneyFlow": ("amount", "flow_date", "flow_type", "source_schedule"),
    "Seat": ("title", "name", "institution_name", "jurisdiction_name", "jurisdiction_id"),
    "SeatService": ("seat_title", "person_name", "start_date", "end_date",
                    "started_at", "ended_at", "jurisdiction_id", "seat_id"),
    "Election": ("name", "title", "election_date", "election_type", "jurisdiction_name"),
    "Candidacy": ("person_name", "name", "seat_title", "election_name", "outcome"),
    "AgendaItem": ("heading", "title", "meeting_title", "meeting_date", "item_number",
                   "parent_meeting_date"),
    "Proceeding": ("title", "name", "proceeding_date", "date", "occurred_at",
                   "case_caption", "proceeding_type"),
    "Agreement": ("title", "name", "agreement_type", "effective_date", "parties",
                  "amount", "project_id"),
    "Amendment": ("title", "name", "parent_title", "parent_id", "effective_date"),
    "Record": ("record_type", "captured_at", "preferred_display_artifact",
               "preferred_public_url", "has_public_source", "published_at"),
    "Place": ("name", "place_type", "parent_name"),
    "Issue": ("name", "description"),
    "Membership": ("person_name", "organization_name", "role", "started_at",
                   "ended_at", "source_basis"),
    "EconomicInterest": ("interest_type", "counterparty_name_raw", "amount_band",
                         "amount", "position", "schedule"),
}


def _allowed(node_type: str) -> frozenset[str]:
    return PUBLIC_PROPS[node_type] | COMMON_PUBLIC_PROPS


@pytest.mark.parametrize("node_type", sorted(APP_READS))
def test_every_key_the_app_reads_is_allowlisted_for_its_type(node_type: str) -> None:
    missing = sorted(
        key for key in (*APP_READS[node_type], *TYPE_AGNOSTIC_READS)
        if key not in _allowed(node_type)
    )
    assert missing == []


def test_sql_prop_reads_in_the_app_are_allowlisted_somewhere() -> None:
    """Live backstop: every prop the app's SQL extracts is serialized for some type."""
    pattern = re.compile(r"""prop\([\w"]+,\s*"(\w+)"\)|props,\s*'\$\.(\w+)'""")
    keys = {
        key
        for path in (REPO / "app/src").rglob("*.ts")
        if ".test." not in path.name
        for match in pattern.finditer(path.read_text(encoding="utf-8"))
        for key in match.groups()
        if key
    }
    assert keys, "grep found no prop reads; the pattern is stale"
    union = COMMON_PUBLIC_PROPS.union(*PUBLIC_PROPS.values())
    assert sorted(keys - union) == []


def test_support_nodes_have_an_explicit_policy_and_unknown_types_fail_closed() -> None:
    check = {"id": "validationcheck-x", "measured_value_number": 1.0,
             "subject_node_id": "filing-x", "display_label": "validationcheck-x"}
    assert SUPPORT_PUBLIC_PROPS == {"ValidationCheck": frozenset({"id"})}
    assert public_props("ValidationCheck", check) == {"id": "validationcheck-x"}
    with pytest.raises(ValueError, match="no public property policy"):
        public_props("Spaceship", {"id": "x"})


def test_public_props_drops_pipeline_internals_and_keeps_facts() -> None:
    props = {
        "id": "permit-marin-IN_B1_1", "name": None, "address": "WOODLAND RD, KENTFIELD",
        "display_label": "Permit at WOODLAND RD, KENTFIELD", "embedding_hash": "ab",
        "embedded_at": "2026-04-29", "embedding_version": 1, "cluster_label": "x",
        "cluster_centroid_distance": 0.1, "cluster_id": 3, "had_canonical_before": False,
        "promotion_state": "", "source": "marin-county-socrata-permits",
        "search_rank": 66, "editorial_note": "hi",
    }
    assert public_props("Project", props) == {
        "id": "permit-marin-IN_B1_1", "name": None, "address": "WOODLAND RD, KENTFIELD",
        "search_rank": 66, "editorial_note": "hi",
    }
    assert "display_label" in BAKE_ONLY_PROPS
    assert not BAKE_ONLY_PROPS & COMMON_PUBLIC_PROPS


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_bake_serializes_allowlist_but_derives_from_bake_only_inputs(tmp_path: Path) -> None:
    nodes = _write_jsonl(tmp_path / "nodes.jsonl", [
        {"id": "org-a", "node_type": "Organization", "labels": ["Organization"],
         "display_label": "Display Only Org",
         "properties": {"search_terms": "terms only token", "embedding_hash": "ab",
                        "cluster_label": "Org · x", "promotion_state": "promoted"}},
        {"id": "org-b", "node_type": "Organization", "labels": ["Organization"],
         "properties": {"name": "Org B"}},
        {"id": "org-c", "node_type": "Organization", "labels": ["Organization"],
         "properties": {"name": "Org C"}},
        {"id": "flow-1", "node_type": "MoneyFlow", "labels": ["MoneyFlow"],
         "properties": {"amount": 10, "flow_date": "2026-01-01", "embedded_at": "x"}},
    ])
    edges = _write_jsonl(tmp_path / "edges.jsonl", [
        {"source_id": "org-c", "relationship_type": "SAME_AS", "target_id": "org-b",
         "properties": {"assertion_id": "as-1", "basis": "ein", "decided_at": "2026-07-01",
                        "reviewer": "stuart", "embedding": [0.1]}},
        {"source_id": "flow-1", "relationship_type": "FROM_SOURCE", "target_id": "org-a",
         "properties": {}},
        {"source_id": "flow-1", "relationship_type": "TO_TARGET", "target_id": "org-b",
         "properties": {}},
    ])
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"graph_node_types": {
        "Organization": {}, "MoneyFlow": {}}}))
    sqlite_path = tmp_path / "public-substrate.sqlite"
    bake_substrate([nodes], [edges], registry, sqlite_path, tmp_path / "report.json")

    with sqlite3.connect(sqlite_path) as conn:
        props = {row[0]: json.loads(row[1]) for row in conn.execute("SELECT id, props FROM nodes")}
        label = conn.execute("SELECT search_label FROM nodes WHERE id = 'org-a'").fetchone()[0]
        browse = conn.execute("SELECT search_label FROM browse_rows WHERE id = 'org-a'").fetchone()[0]
        terms_hit = conn.execute(
            "SELECT n.id FROM search_fts JOIN nodes n ON n.rowid = search_fts.rowid "
            "WHERE search_fts MATCH 'token'"
        ).fetchall()
        identity = conn.execute(
            "SELECT assertion_id, basis, decided_at, reviewer FROM identity_links"
        ).fetchall()
        rollup = conn.execute(
            "SELECT top_counterparties FROM money_rollups WHERE org_id = 'org-b'"
        ).fetchone()[0]

    for serialized in props.values():
        assert not {"display_label", "embedding_hash", "embedded_at", "cluster_label",
                    "promotion_state"} & set(serialized)
    assert props["flow-1"] == {"amount": 10, "flow_date": "2026-01-01"}
    # Bake-only inputs still drove the label, FTS and rollup labels.
    assert label == "Display Only Org"
    assert browse == "org-a"
    assert terms_hit == [("org-a",)]
    assert json.loads(rollup) == [{"id": "org-a", "label": "Display Only Org", "total": 10.0}]
    # Edges are not node-allowlisted: identity assertion props survive.
    assert identity == [("as-1", "ein", "2026-07-01", "stuart")]
