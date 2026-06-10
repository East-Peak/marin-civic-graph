"""Tests for scripts/build_dual_role_candidates.py — the dual-role read model (M2d).

The read model consumes ingestor-envelope JSONL dirs only (no database, no
fetching). Funding-in inputs are GENERATED, not staged: the real ingest_990 /
ingest_usaspending CLIs run on their committed fixtures into tmp_path, and the
loader/extractors are asserted against that real output. The influence-out
input is the staged byte-verbatim slice of the real NetFile-derived campaign
bundle in tests/fixtures/dual_role/influence-out/. Loader dedupe per
Decision 1 (nodes by id, byte-identical collapse silently, divergent payload
fails loud; edges by full-row equality, campaign-superset keys tolerated by
normalizing to the v2 envelope); funding legs per Decision 3 (990
gov-grant-positive Filings via FILED_BY_ORG — the MCF negative; USASpending
flows via TO_TARGET); influence-out legs FROM_SOURCE-direction-exact (the CAM
TO_TARGET-only negative). The suite must leave `git status` untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_dual_role_candidates import (  # noqa: E402
    COVERAGE_NOTE,
    assemble_table,
    build_components,
    build_join_links,
    collect_same_as_edges,
    extract_funding_in,
    extract_influence_out,
    load_approved_resolutions,
    load_envelope_dirs,
)
from ingest_990 import main as ingest_990_main  # noqa: E402
from ingest_usaspending import main as ingest_usaspending_main  # noqa: E402

FIXTURES_990 = Path(__file__).resolve().parents[1] / "fixtures" / "990"
FIXTURES_USASP = Path(__file__).resolve().parents[1] / "fixtures" / "usaspending"
FIXTURES_INFLUENCE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "dual_role" / "influence-out"
)

MALT_ORG = "org-990-ein-942689383"
MCF_ORG = "org-990-ein-943007979"
CAM_ORG = "org-usasp-uei-JZ9FLAVMPEB9"
MALT_CAMPAIGN_ORG = "org-marin-agricultural-land-trust"
CAM_CAMPAIGN_ORG = "org-community-action-marin"


@pytest.fixture(scope="module")
def funding_dirs(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    """Real ingestor output: both funding-in envelope dirs, built once."""
    base = tmp_path_factory.mktemp("funding-in")
    dir_990 = base / "990" / "normalized"
    dir_usasp = base / "usaspending" / "normalized"
    ingest_990_main(
        [
            "--input-dir", str(FIXTURES_990),
            "--output-dir", str(dir_990),
            "--review-dir", str(base / "990" / "review"),
        ]
    )
    ingest_usaspending_main(
        [
            "--input-dir", str(FIXTURES_USASP),
            "--output-dir", str(dir_usasp),
            "--review-dir", str(base / "usaspending" / "review"),
        ]
    )
    return [dir_990, dir_usasp]


# ---------------------------------------------------------------------------
# Loader — multi-dir merge + Decision 1 dedupe
# ---------------------------------------------------------------------------


def test_loader_merges_dirs_keyed_by_node_id(funding_dirs: list[Path]):
    nodes_by_id, edges = load_envelope_dirs(funding_dirs)
    assert MALT_ORG in nodes_by_id
    assert MCF_ORG in nodes_by_id
    assert CAM_ORG in nodes_by_id
    assert nodes_by_id[MALT_ORG]["display_label"] == "Marin Agricultural Land Trust"
    # Every loaded edge keeps the envelope edge shape.
    for edge in edges:
        assert set(edge) == {"source_id", "target_id", "relationship_type", "properties"}


def test_loader_collapses_byte_identical_duplicates_silently(funding_dirs: list[Path]):
    # The same dir passed twice is operator-normal (Decision 1): byte-identical
    # rows collapse — the loaded sets are identical to a single pass.
    once = load_envelope_dirs(funding_dirs)
    twice = load_envelope_dirs([*funding_dirs, funding_dirs[0]])
    assert once == twice


def test_loader_fails_loud_on_same_id_divergent_payload(
    funding_dirs: list[Path], tmp_path: Path
):
    # An overlapping bundle that re-emits a real org id with a DIFFERING
    # payload must never silently pick one (Decision 1).
    nodes_text = (funding_dirs[0] / "nodes.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in nodes_text.splitlines()]
    divergent = next(r for r in rows if r["id"] == MALT_ORG)
    divergent = {**divergent, "display_label": "Different Label"}
    overlap = tmp_path / "overlap"
    overlap.mkdir()
    (overlap / "nodes.jsonl").write_text(
        json.dumps(divergent) + "\n", encoding="utf-8"
    )
    (overlap / "edges.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match=MALT_ORG):
        load_envelope_dirs([*funding_dirs, overlap])


# ---------------------------------------------------------------------------
# Funding legs — Decision 3, asserted on real fixture output
# ---------------------------------------------------------------------------


def test_990_leg_includes_only_gov_grant_positive_filings(funding_dirs: list[Path]):
    nodes_by_id, edges = load_envelope_dirs(funding_dirs)
    funding = extract_funding_in(nodes_by_id, edges)
    # MALT: one gov-grant-positive filing, fields carried verbatim.
    assert funding[MALT_ORG]["form_990"] == [
        {
            "tax_year": "2022",
            "gov_grants_amount": 3150000,
            "gov_revenue_share": 0.4278,
            "total_revenue": 7362936,
            "revenue_scope": "form_990_aggregate_government_grants",
            "evidence_record_ids": ["record-990-942689383-2022"],
        }
    ]
    # MCF files in BOTH fixture years but carries no gov_grants_amount —
    # a 990 Filing without positive gov grants is NOT funding-in evidence.
    assert MCF_ORG not in funding


def test_usaspending_leg_is_to_target_directed(funding_dirs: list[Path]):
    nodes_by_id, edges = load_envelope_dirs(funding_dirs)
    funding = extract_funding_in(nodes_by_id, edges)
    cam_flows = funding[CAM_ORG]["usaspending"]
    assert len(cam_flows) == 2  # CAM's two real awards
    for flow in cam_flows:
        assert flow["coverage_scope"] == "usaspending_prime_award_total_obligation"
        assert len(flow["evidence_record_ids"]) == 1
    # Flows held per-flow in flow-id order (Decision 6 sums in this order).
    assert [f["flow_id"] for f in cam_flows] == sorted(f["flow_id"] for f in cam_flows)
    # Awarding AGENCIES sit on the FROM_SOURCE side — never a funding leg.
    assert "org-usasp-agency-department-of-the-treasury" not in funding
    # 20 award flows across the fixture recipients, all funding-in.
    total_flows = sum(
        len(entry.get("usaspending", [])) for entry in funding.values()
    )
    assert total_flows == 20


def test_funding_org_set_is_exactly_the_evidence_positive_orgs(
    funding_dirs: list[Path],
):
    nodes_by_id, edges = load_envelope_dirs(funding_dirs)
    funding = extract_funding_in(nodes_by_id, edges)
    # Every funding org carries ≥1 lane with ≥1 entry; no empty shells.
    for org_id, entry in funding.items():
        assert entry.get("form_990") or entry.get("usaspending"), org_id
        assert set(entry) <= {"form_990", "usaspending"}
    # 9 USASpending recipients + MALT (990) = 10; MCF excluded.
    assert len(funding) == 10


# ---------------------------------------------------------------------------
# SAME_AS collection — the ingestors' deterministic key merges, carried
# ---------------------------------------------------------------------------


def test_no_existing_orgs_means_no_same_as(funding_dirs: list[Path]):
    _, edges = load_envelope_dirs(funding_dirs)
    assert collect_same_as_edges(edges) == []


def test_same_as_edges_collected_with_basis(tmp_path: Path):
    # Real resolver path: ingest_990 with an EIN-keyed existing org emits the
    # deterministic SAME_AS merge into its edges output; the collector carries
    # it through (basis enforcement is the join lane's job, not the loader's).
    existing = tmp_path / "existing-orgs.json"
    existing.write_text(
        json.dumps(
            [
                {
                    "id": "org-marin-community-foundation",
                    "display_label": "Marin Community Foundation",
                    "ein": "94-3007979",
                }
            ]
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "normalized"
    ingest_990_main(
        [
            "--input-dir", str(FIXTURES_990),
            "--output-dir", str(out_dir),
            "--review-dir", str(tmp_path / "review"),
            "--existing-orgs", str(existing),
        ]
    )
    _, edges = load_envelope_dirs([out_dir])
    assert collect_same_as_edges(edges) == [
        {
            "source_id": MCF_ORG,
            "target_id": "org-marin-community-foundation",
            "relationship_type": "SAME_AS",
            "properties": {"basis": "ein_exact"},
        }
    ]


# ---------------------------------------------------------------------------
# Influence-out — campaign superset tolerated, FROM_SOURCE-direction-exact
# ---------------------------------------------------------------------------


def test_campaign_superset_envelope_normalizes_to_v2():
    # The campaign bundle carries extra promotion_state/qa_lane/source_* keys
    # on every row — the loader tolerates them by normalizing to the v2
    # envelope, so dedupe and every downstream read see one shape.
    nodes_by_id, edges = load_envelope_dirs([FIXTURES_INFLUENCE])
    assert len(nodes_by_id) == 19
    assert len(edges) == 30
    for node in nodes_by_id.values():
        assert set(node) == {
            "id", "node_type", "labels", "display_label", "properties",
        }
    for edge in edges:
        assert set(edge) == {
            "source_id", "target_id", "relationship_type", "properties",
        }


def test_influence_out_is_from_source_direction_exact():
    nodes_by_id, edges = load_envelope_dirs([FIXTURES_INFLUENCE])
    flows = extract_influence_out(nodes_by_id, edges)
    # MALT sources 6 real flows — amounts verbatim (one REAL negative),
    # entries in flow-id order, dangling evidence ids carried as-is.
    assert flows[MALT_CAMPAIGN_ORG] == [
        {
            "flow_id": "moneyflow-1424535-EXP21",
            "amount": -7307.5,
            "flow_date": "2020-06-16",
            "flow_type": "contribution",
            "evidence_record_ids": ["record-marin-county-campaign-finance-export-2020"],
        },
        {
            "flow_id": "moneyflow-1424535-INC4",
            "amount": 10000.0,
            "flow_date": "2020-03-06",
            "flow_type": "contribution",
            "evidence_record_ids": ["record-marin-county-campaign-finance-export-2020"],
        },
        {
            "flow_id": "moneyflow-1444863-Pp5X1tktd8nP",
            "amount": 56000.0,
            "flow_date": "2022-06-06",
            "flow_type": "contribution",
            "evidence_record_ids": ["record-marin-county-campaign-finance-export-2022"],
        },
        {
            "flow_id": "moneyflow-1444863-WLcNvnGn98LV",
            "amount": 42000.0,
            "flow_date": "2022-06-03",
            "flow_type": "contribution",
            "evidence_record_ids": ["record-marin-county-campaign-finance-export-2022"],
        },
        {
            "flow_id": "moneyflow-1444863-jFpQhLaJMEFZ",
            "amount": 42000.0,
            "flow_date": "2022-05-16",
            "flow_type": "contribution",
            "evidence_record_ids": ["record-marin-county-campaign-finance-export-2022"],
        },
        {
            "flow_id": "moneyflow-1444863-juXUJhrbP8bL",
            "amount": 10000.0,
            "flow_date": "2022-05-02",
            "flow_type": "contribution",
            "evidence_record_ids": ["record-marin-county-campaign-finance-export-2022"],
        },
    ]
    # CAM appears in the real bundle ONLY as the TO_TARGET of its flow —
    # money TO the org is not influence-out (the direction negative).
    assert CAM_CAMPAIGN_ORG not in flows
    # That flow's FROM_SOURCE is a Committee node — sources credit an
    # influence-out leg only when the source node is an Organization.
    assert "committee-netfile-1474069" not in flows
    # The two other contributor orgs in the slice carry their own flows.
    assert [f["flow_id"] for f in flows["org-3qc-inc"]] == [
        "moneyflow-1447634-dQZzVLJUhseS"
    ]
    assert [f["flow_id"] for f in flows["org-alten-construction-inc"]] == [
        "moneyflow-1436437-5nlEO5NWLpm9",
        "moneyflow-1447634-ie8hUWpb9FdG",
    ]
    assert set(flows) == {
        MALT_CAMPAIGN_ORG, "org-3qc-inc", "org-alten-construction-inc",
    }


def test_influence_out_evidence_targets_dangle_by_design():
    # The campaign slice's EVIDENCED_BY targets are record ids whose Record
    # nodes live in a different bundle — carried verbatim, never resolved.
    nodes_by_id, edges = load_envelope_dirs([FIXTURES_INFLUENCE])
    flows = extract_influence_out(nodes_by_id, edges)
    for entries in flows.values():
        for entry in entries:
            for record_id in entry["evidence_record_ids"]:
                assert record_id not in nodes_by_id


# ---------------------------------------------------------------------------
# Join core — lanes A/B/C, Decision 2
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def malt_queued_row(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """The REAL queued MALT pair: ingest_990 on the committed fixtures with
    existing-orgs = the influence-out campaign org stubs (the operator's
    graph export). The resolver queues the normalized-name-exact pair —
    this is the row the operator reviews."""
    base = tmp_path_factory.mktemp("resolver")
    existing = base / "existing-orgs.json"
    existing.write_text(
        json.dumps(
            [
                {
                    "id": MALT_CAMPAIGN_ORG,
                    "display_label": "Marin Agricultural Land Trust",
                },
                {
                    "id": CAM_CAMPAIGN_ORG,
                    "display_label": "Community Action Marin",
                },
            ]
        ),
        encoding="utf-8",
    )
    ingest_990_main(
        [
            "--input-dir", str(FIXTURES_990),
            "--output-dir", str(base / "normalized"),
            "--review-dir", str(base / "review"),
            "--existing-orgs", str(existing),
        ]
    )
    review = base / "review" / "resolution-candidates-990.jsonl"
    rows = [json.loads(line) for line in review.read_text().splitlines()]
    matches = [r for r in rows if r["candidate_ref"] == MALT_CAMPAIGN_ORG]
    assert len(matches) == 1
    row = matches[0]
    assert row["subject_ref"] == MALT_ORG
    assert row["signals"] == ["normalized_name_exact"]
    assert row["confidence"] == 0.9
    assert row["status"] == "queued"
    return row


KNOWN_IDS = {MALT_ORG, MCF_ORG, CAM_ORG, MALT_CAMPAIGN_ORG, CAM_CAMPAIGN_ORG}


def test_approved_extract_loads_and_dedupes(malt_queued_row: dict, tmp_path: Path):
    # The operator approves the real queued row and exports the approved-only
    # extract; an idempotent re-export (the same row twice) loads once.
    approved = {**malt_queued_row, "status": "approved"}
    path = tmp_path / "approved.jsonl"
    path.write_text(json.dumps(approved) + "\n" + json.dumps(approved) + "\n")
    rows = load_approved_resolutions(path, KNOWN_IDS)
    assert rows == [approved]


def test_mixed_status_review_file_fails_loud(malt_queued_row: dict, tmp_path: Path):
    # Passing the annotated reviewed queue instead of the approved-only
    # extract is an error by design — §4.3 vocabulary (queued/approved/
    # rejected), all realistic operator annotation states.
    approved = {**malt_queued_row, "status": "approved"}
    still_queued = dict(malt_queued_row)
    rejected = {
        "subject_ref": MCF_ORG,
        "candidate_ref": CAM_CAMPAIGN_ORG,
        "signals": ["name_similarity:0.86"],
        "confidence": 0.86,
        "status": "rejected",
        "evidence_record_ids": ["record-990-943007979-2022"],
    }
    path = tmp_path / "reviewed-queue.jsonl"
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in [approved, still_queued, rejected])
    )
    with pytest.raises(ValueError, match="queued"):
        load_approved_resolutions(path, KNOWN_IDS)


def test_stale_approved_refs_fail_loud(malt_queued_row: dict, tmp_path: Path):
    # A stale approval (ref absent from the loaded inputs) is operator
    # error, never silently skipped.
    approved = {**malt_queued_row, "status": "approved"}
    stale_candidate = {**approved, "candidate_ref": "org-not-in-these-inputs"}
    path = tmp_path / "approved.jsonl"
    path.write_text(json.dumps(stale_candidate) + "\n")
    with pytest.raises(ValueError, match="org-not-in-these-inputs"):
        load_approved_resolutions(path, KNOWN_IDS)

    stale_subject = {**approved, "subject_ref": "org-990-ein-000000000"}
    path.write_text(json.dumps(stale_subject) + "\n")
    with pytest.raises(ValueError, match="org-990-ein-000000000"):
        load_approved_resolutions(path, KNOWN_IDS)


def test_same_as_allowlist_gates_the_deterministic_lane(malt_queued_row: dict):
    # Allowlisted bases pass with basis carried through; a review-derived or
    # unknown-provenance basis must never silently enter the deterministic
    # lane.
    ein_edge = {
        "source_id": MCF_ORG,
        "target_id": "org-marin-community-foundation",
        "relationship_type": "SAME_AS",
        "properties": {"basis": "ein_exact"},
    }
    uei_edge = {
        "source_id": CAM_ORG,
        "target_id": CAM_CAMPAIGN_ORG,
        "relationship_type": "SAME_AS",
        "properties": {"basis": "uei_exact"},
    }
    assert build_join_links([ein_edge, uei_edge], []) == [
        {
            "funding_org_ref": MCF_ORG,
            "influence_org_ref": "org-marin-community-foundation",
            "basis": "same_as:ein_exact",
        },
        {
            "funding_org_ref": CAM_ORG,
            "influence_org_ref": CAM_CAMPAIGN_ORG,
            "basis": "same_as:uei_exact",
        },
    ]
    name_basis = {**ein_edge, "properties": {"basis": "normalized_name_exact"}}
    with pytest.raises(ValueError, match="normalized_name_exact"):
        build_join_links([name_basis], [])
    no_basis = {**ein_edge, "properties": {}}
    with pytest.raises(ValueError, match="SAME_AS"):
        build_join_links([no_basis], [])


def test_approved_rows_become_links_with_signals_carried(malt_queued_row: dict):
    approved = {**malt_queued_row, "status": "approved"}
    assert build_join_links([], [approved]) == [
        {
            "funding_org_ref": MALT_ORG,
            "influence_org_ref": MALT_CAMPAIGN_ORG,
            "basis": "approved_resolution",
            "signals": ["normalized_name_exact"],
            "confidence": 0.9,
        }
    ]


def test_queued_rows_never_join(funding_dirs: list[Path], malt_queued_row: dict):
    # The real queued MALT pair exists in the review sidecar — but with no
    # approval there is NO link, and the funding-side and campaign-side MALT
    # orgs stay in separate components (the judgment gate).
    nodes_by_id, edges = load_envelope_dirs(funding_dirs)
    funding = extract_funding_in(nodes_by_id, edges)
    influence_nodes, influence_edges = load_envelope_dirs([FIXTURES_INFLUENCE])
    influence = extract_influence_out(influence_nodes, influence_edges)

    components = build_components(set(funding), set(influence), [])
    by_member = {member: tuple(c) for c in components for member in c}
    assert by_member[MALT_ORG] == (MALT_ORG,)
    assert by_member[MALT_CAMPAIGN_ORG] == (MALT_CAMPAIGN_ORG,)

    # The approved link merges exactly that pair and nothing else.
    approved_link = build_join_links([], [{**malt_queued_row, "status": "approved"}])
    components = build_components(set(funding), set(influence), approved_link)
    by_member = {member: tuple(c) for c in components for member in c}
    assert by_member[MALT_ORG] == (MALT_ORG, MALT_CAMPAIGN_ORG)
    assert by_member[CAM_ORG] == (CAM_ORG,)


def test_component_assembly_is_deterministic_and_link_order_free(
    funding_dirs: list[Path], malt_queued_row: dict
):
    nodes_by_id, edges = load_envelope_dirs(funding_dirs)
    funding = extract_funding_in(nodes_by_id, edges)
    influence_nodes, influence_edges = load_envelope_dirs([FIXTURES_INFLUENCE])
    influence = extract_influence_out(influence_nodes, influence_edges)
    links = build_join_links(
        [
            {
                "source_id": CAM_ORG,
                "target_id": CAM_CAMPAIGN_ORG,
                "relationship_type": "SAME_AS",
                "properties": {"basis": "uei_exact"},
            }
        ],
        [{**malt_queued_row, "status": "approved"}],
    )
    forward = build_components(set(funding), set(influence), links)
    backward = build_components(set(funding), set(influence), list(reversed(links)))
    assert forward == backward
    # Sorted members, components ordered by first member — and a SAME_AS
    # target joins its component even when it carries no leg itself.
    assert [CAM_CAMPAIGN_ORG, CAM_ORG] in forward
    assert all(c == sorted(c) for c in forward)
    assert forward == sorted(forward)


def test_lane_a_identical_id_is_one_component():
    # Lane A id_exact: the same org id carrying both legs is trivially one
    # component with no link required (future-proof).
    components = build_components(
        {MALT_CAMPAIGN_ORG}, {MALT_CAMPAIGN_ORG}, []
    )
    assert components == [[MALT_CAMPAIGN_ORG]]


# ---------------------------------------------------------------------------
# Table assembly — Decisions 4/5/6
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def table_inputs(funding_dirs: list[Path]) -> dict:
    """Assembly inputs, legs extracted PER INPUT CLASS — funding legs over the
    funding-in dirs only, influence legs over the influence-out dir only. The
    real campaign slice carries a MoneyFlow TO_TARGETing an Organization (the
    CAM flow), which would falsely register as a funding leg if extraction
    crossed input classes. Node maps merge for label lookups (the bundles'
    id namespaces are disjoint)."""
    funding_nodes, funding_edges = load_envelope_dirs(funding_dirs)
    influence_nodes, influence_edges = load_envelope_dirs([FIXTURES_INFLUENCE])
    return {
        "nodes": {**funding_nodes, **influence_nodes},
        "funding": extract_funding_in(funding_nodes, funding_edges),
        "influence": extract_influence_out(influence_nodes, influence_edges),
    }


def _malt_candidate_row() -> dict:
    """The full post-approval MALT candidate row — every value a real ground
    truth from the committed fixtures (goal doc COMPLETION 3)."""
    return {
        "subject_ref": MALT_CAMPAIGN_ORG,
        "subject_label": "Marin Agricultural Land Trust",
        "status": "candidate",
        "joined_via": [
            {
                "funding_org_ref": MALT_ORG,
                "influence_org_ref": MALT_CAMPAIGN_ORG,
                "basis": "approved_resolution",
                "signals": ["normalized_name_exact"],
                "confidence": 0.9,
            }
        ],
        "funding_in": {
            "form_990": [
                {
                    "tax_year": "2022",
                    "gov_grants_amount": 3150000,
                    "gov_revenue_share": 0.4278,
                    "total_revenue": 7362936,
                    "revenue_scope": "form_990_aggregate_government_grants",
                    "evidence_record_ids": ["record-990-942689383-2022"],
                }
            ]
        },
        "influence_out": {
            "flow_count": 6,
            "amount_total": 152692.5,
            "first_flow_date": "2020-03-06",
            "last_flow_date": "2022-06-06",
            "flow_types": ["contribution"],
            "coverage_scope": "netfile_campaign_finance_export",
            "evidence_record_ids": [
                "record-marin-county-campaign-finance-export-2020",
                "record-marin-county-campaign-finance-export-2022",
            ],
        },
        "evidence_record_ids": [
            "record-990-942689383-2022",
            "record-marin-county-campaign-finance-export-2020",
            "record-marin-county-campaign-finance-export-2022",
        ],
        "dependency_refs": [],
        "coverage_note": COVERAGE_NOTE,
        "rank": 1,
        "rank_basis": "influence_out_amount_total",
    }


def test_coverage_note_is_the_pinned_constant():
    assert COVERAGE_NOTE == (
        "Dual-role candidate from broad-coverage sources (USASpending "
        "prime-award obligations; Form 990 aggregate government grants; "
        "NetFile campaign-finance exports). Identity joins are deterministic "
        "or operator-reviewed. Not a confirmed local-dollar claim; "
        "local-spend coverage is milestone M3. Rank orders rows by "
        "campaign-finance dollars only and does not assess severity."
    )


def test_pre_approval_queued_pair_withholds_the_row(
    table_inputs: dict, malt_queued_row: dict
):
    # The real queued MALT pair with no approval: the would-be row is
    # withheld with EXACTLY the pinned 5-key subset — no rank, no joined_via,
    # no dollar blocks, no evidence (Decision 5).
    rows, counts = assemble_table(
        table_inputs["nodes"],
        table_inputs["funding"],
        table_inputs["influence"],
        [],
        [malt_queued_row],
    )
    assert rows == [
        {
            "subject_ref": MALT_CAMPAIGN_ORG,
            "subject_label": "Marin Agricultural Land Trust",
            "status": "withheld_pending_resolution",
            "dependency_refs": [
                {"subject_ref": MALT_ORG, "candidate_ref": MALT_CAMPAIGN_ORG}
            ],
            "coverage_note": COVERAGE_NOTE,
        }
    ]
    assert counts == {
        "candidate_rows": 0,
        "funding_in_only": 9,
        "influence_out_only": 2,
        "withheld_pending_resolution": 1,
    }


def test_post_approval_candidate_row_is_complete_and_rank_1(
    table_inputs: dict, malt_queued_row: dict
):
    links = build_join_links([], [{**malt_queued_row, "status": "approved"}])
    rows, counts = assemble_table(
        table_inputs["nodes"],
        table_inputs["funding"],
        table_inputs["influence"],
        links,
        [],
    )
    assert rows == [_malt_candidate_row()]
    assert counts == {
        "candidate_rows": 1,
        "funding_in_only": 9,
        "influence_out_only": 2,
        "withheld_pending_resolution": 0,
    }


def test_queued_pair_inside_a_candidate_component_attaches_not_withholds(
    table_inputs: dict, malt_queued_row: dict
):
    # The operator approved the pair but the sidecar still carries the queued
    # row (annotate-in-place is operator-normal): Decision 5(ii) — a queued
    # pair touching a candidate component creates NO withheld row and is
    # recorded in that row's dependency_refs.
    links = build_join_links([], [{**malt_queued_row, "status": "approved"}])
    rows, counts = assemble_table(
        table_inputs["nodes"],
        table_inputs["funding"],
        table_inputs["influence"],
        links,
        [malt_queued_row],
    )
    expected = _malt_candidate_row()
    expected["dependency_refs"] = [
        {"subject_ref": MALT_ORG, "candidate_ref": MALT_CAMPAIGN_ORG}
    ]
    assert rows == [expected]
    assert counts == {
        "candidate_rows": 1,
        "funding_in_only": 9,
        "influence_out_only": 2,
        "withheld_pending_resolution": 0,
    }


def test_queued_component_with_one_leg_is_not_withheld(table_inputs: dict):
    # The REAL CAM pair the usaspending resolver queues: CAM carries
    # funding-in, but org-community-action-marin sources no flows — the
    # queued component has ONE leg, so withholding does not apply and the
    # component counts in funding_in_only (Decision 5(iii): both legs only).
    queued = [{"subject_ref": CAM_ORG, "candidate_ref": CAM_CAMPAIGN_ORG}]
    rows, counts = assemble_table(
        table_inputs["nodes"],
        table_inputs["funding"],
        table_inputs["influence"],
        [],
        queued,
    )
    assert rows == []
    assert counts == {
        "candidate_rows": 0,
        "funding_in_only": 10,
        "influence_out_only": 3,
        "withheld_pending_resolution": 0,
    }


def test_approved_join_without_influence_flows_yields_no_row(table_inputs: dict):
    # Approving the CAM pair merges the component but adds no influence leg
    # (the TO_TARGET-only direction negative) — rows are for both-legs
    # components ONLY; the merged component counts once in funding_in_only.
    links = [
        {
            "funding_org_ref": CAM_ORG,
            "influence_org_ref": CAM_CAMPAIGN_ORG,
            "basis": "approved_resolution",
        }
    ]
    rows, counts = assemble_table(
        table_inputs["nodes"],
        table_inputs["funding"],
        table_inputs["influence"],
        links,
        [],
    )
    assert rows == []
    assert counts == {
        "candidate_rows": 0,
        "funding_in_only": 10,
        "influence_out_only": 3,
        "withheld_pending_resolution": 0,
    }


def test_usaspending_lane_aggregates_per_decision_4(table_inputs: dict):
    # Mechanism link (operator-shaped test construction, the M2b/M2c
    # precedent): joining a USASpending recipient to a flow-sourcing org
    # exercises the usaspending aggregate block — the committed fixtures
    # carry no real recipient identity that also sources campaign flows.
    links = [
        {
            "funding_org_ref": CAM_ORG,
            "influence_org_ref": "org-3qc-inc",
            "basis": "approved_resolution",
        }
    ]
    rows, counts = assemble_table(
        table_inputs["nodes"],
        table_inputs["funding"],
        table_inputs["influence"],
        links,
        [],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["subject_ref"] == "org-3qc-inc"
    assert row["subject_label"] == "3QC, Inc."
    # Lane present only with evidence: no form_990 key for this component.
    assert row["funding_in"] == {
        "usaspending": {
            "award_count": 2,
            "obligation_total": 38960291.2,
            "coverage_scope": "usaspending_prime_award_total_obligation",
            "evidence_record_ids": [
                "record-usasp-asst_non_09ch011669_075",
                "record-usasp-asst_non_09ch013338_075",
            ],
        }
    }
    assert row["influence_out"] == {
        "flow_count": 1,
        "amount_total": 1000.0,
        "first_flow_date": "2022-04-01",
        "last_flow_date": "2022-04-01",
        "flow_types": ["contribution"],
        "coverage_scope": "netfile_campaign_finance_export",
        "evidence_record_ids": [
            "record-marin-county-campaign-finance-export-2022"
        ],
    }
    # Top-level evidence = sorted union of both legs'.
    assert row["evidence_record_ids"] == [
        "record-marin-county-campaign-finance-export-2022",
        "record-usasp-asst_non_09ch011669_075",
        "record-usasp-asst_non_09ch013338_075",
    ]
    assert (row["rank"], row["rank_basis"]) == (1, "influence_out_amount_total")
    assert counts == {
        "candidate_rows": 1,
        "funding_in_only": 9,
        "influence_out_only": 2,
        "withheld_pending_resolution": 0,
    }


def test_alias_approvals_merge_components_and_aggregate_flows(
    table_inputs: dict, malt_queued_row: dict
):
    # Decision 2: one funding org approved to two campaign name-stubs is the
    # expected alias case — components merge, every link stays listed in
    # joined_via, and influence flows aggregate across the merged orgs in
    # flow-id order. subject_ref = the smallest influence-out member.
    alias_link = {
        "funding_org_ref": MALT_ORG,
        "influence_org_ref": "org-3qc-inc",
        "basis": "approved_resolution",
    }
    links = build_join_links([], [{**malt_queued_row, "status": "approved"}])
    rows, counts = assemble_table(
        table_inputs["nodes"],
        table_inputs["funding"],
        table_inputs["influence"],
        links + [alias_link],
        [],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["subject_ref"] == "org-3qc-inc"
    assert row["subject_label"] == "3QC, Inc."
    assert row["joined_via"] == [
        alias_link,
        {
            "funding_org_ref": MALT_ORG,
            "influence_org_ref": MALT_CAMPAIGN_ORG,
            "basis": "approved_resolution",
            "signals": ["normalized_name_exact"],
            "confidence": 0.9,
        },
    ]
    assert row["funding_in"] == _malt_candidate_row()["funding_in"]
    assert row["influence_out"]["flow_count"] == 7
    assert row["influence_out"]["amount_total"] == 153692.5
    assert row["influence_out"]["first_flow_date"] == "2020-03-06"
    assert row["influence_out"]["last_flow_date"] == "2022-06-06"
    assert counts == {
        "candidate_rows": 1,
        "funding_in_only": 9,
        "influence_out_only": 1,
        "withheld_pending_resolution": 0,
    }


def test_withheld_rows_sort_after_ranked_rows(
    table_inputs: dict, malt_queued_row: dict
):
    # One ranked candidate + one disjoint queued both-legs component: the
    # withheld row sorts AFTER every ranked row (Decision 5).
    links = build_join_links([], [{**malt_queued_row, "status": "approved"}])
    queued = [
        {"subject_ref": CAM_ORG, "candidate_ref": "org-alten-construction-inc"}
    ]
    rows, counts = assemble_table(
        table_inputs["nodes"],
        table_inputs["funding"],
        table_inputs["influence"],
        links,
        queued,
    )
    assert [r["status"] for r in rows] == [
        "candidate",
        "withheld_pending_resolution",
    ]
    assert rows[0] == _malt_candidate_row()
    assert rows[1] == {
        "subject_ref": "org-alten-construction-inc",
        "subject_label": "Alten Construction Inc.",
        "status": "withheld_pending_resolution",
        "dependency_refs": [
            {
                "subject_ref": CAM_ORG,
                "candidate_ref": "org-alten-construction-inc",
            }
        ],
        "coverage_note": COVERAGE_NOTE,
    }
    assert counts == {
        "candidate_rows": 1,
        "funding_in_only": 8,
        "influence_out_only": 1,
        "withheld_pending_resolution": 1,
    }


def test_rows_never_carry_envelope_keys(
    table_inputs: dict, malt_queued_row: dict
):
    # Sidecar-never-envelope (M2c precedent), over BOTH row shapes.
    links = build_join_links([], [{**malt_queued_row, "status": "approved"}])
    queued = [
        {"subject_ref": CAM_ORG, "candidate_ref": "org-alten-construction-inc"}
    ]
    rows, _ = assemble_table(
        table_inputs["nodes"],
        table_inputs["funding"],
        table_inputs["influence"],
        links,
        queued,
    )
    envelope_keys = {
        "id", "node_type", "labels", "properties",
        "source_id", "target_id", "relationship_type",
    }
    assert {r["status"] for r in rows} == {
        "candidate", "withheld_pending_resolution",
    }
    for row in rows:
        assert not envelope_keys & set(row)


def test_assembly_is_deterministic_and_link_order_free(
    table_inputs: dict, malt_queued_row: dict
):
    links = build_join_links([], [{**malt_queued_row, "status": "approved"}]) + [
        {
            "funding_org_ref": CAM_ORG,
            "influence_org_ref": CAM_CAMPAIGN_ORG,
            "basis": "approved_resolution",
        }
    ]
    queued = [
        {"subject_ref": CAM_ORG, "candidate_ref": "org-alten-construction-inc"}
    ]
    args = (
        table_inputs["nodes"],
        table_inputs["funding"],
        table_inputs["influence"],
    )
    first = assemble_table(*args, links, queued)
    second = assemble_table(*args, links, queued)
    reordered = assemble_table(*args, list(reversed(links)), queued)
    assert first == second == reordered
