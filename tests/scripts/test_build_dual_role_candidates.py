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
    collect_same_as_edges,
    extract_funding_in,
    extract_influence_out,
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
