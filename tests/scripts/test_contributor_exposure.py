"""The campaign_contributor exposure level: reported contributor details on the public artifact.

Every value is fictional (EXAMPLE/SAMPLE names, 555 phone numbers). The bake is driven end to end.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from bake_public_substrate import bake_substrate  # noqa: E402
from contributor_detail import review_key  # noqa: E402
from public_exposure import ADDRESS_EXPOSURE, sanitize_node_props  # noqa: E402

DETAILS = {"reported_occupation": "Engineer", "reported_employer": "Example Co", "reported_city": "Sampleton",
           "reported_state": "CA", "reported_zip5": "94999"}


def _flow(node_id="moneyflow-1400001-a1", **props) -> dict:
    return {"id": node_id, "amount": 100.0, "flow_type": "contribution", "source_schedule": "A",
            "flow_date": "2024-01-05", "display_label": "contribution $100.00", "reported_entity_cd": "IND",
            **DETAILS, **props}


def _shown(props: dict) -> dict:
    return {k: v for k, v in props.items() if k in DETAILS}


class TestPolicy:
    def test_the_level_is_one_knob_beside_the_project_classes(self):
        assert ADDRESS_EXPOSURE["campaign_contributor"] == "city_zip"

    def test_an_eligible_flow_keeps_its_details(self):
        assert _shown(sanitize_node_props("MoneyFlow", _flow())) == DETAILS

    @pytest.mark.parametrize("override, gone", [
        ({"reported_employer": "415-555-0199"}, "reported_employer"),
        ({"reported_employer": "Exampleco.com"}, "reported_employer"),
        ({"reported_occupation": "Homemaker at 40 Sample Road"}, "reported_occupation"),
        ({"reported_zip5": "9499"}, "reported_zip5"),
        ({"reported_city": "Sampleton, CA 94999"}, "reported_city"),
        ({"reported_state": "Calif"}, "reported_state"),
    ])
    def test_the_bake_reapplies_the_value_rules_whatever_the_graph_holds(self, override, gone):
        shown = _shown(sanitize_node_props("MoneyFlow", _flow(**override)))
        assert gone not in shown
        assert shown == {k: v for k, v in DETAILS.items() if k != gone}

    def test_a_zip_plus_4_in_the_graph_publishes_only_its_zip5(self):
        assert _shown(sanitize_node_props("MoneyFlow", _flow(reported_zip5="94999-0001")))["reported_zip5"] == "94999"

    def test_a_reviewed_value_publishes(self):
        reviewed = frozenset({review_key("employer", "Exampleco.com")})
        shown = _shown(sanitize_node_props("MoneyFlow", _flow(reported_employer="Exampleco.com"), reviewed=reviewed))
        assert shown["reported_employer"] == "Exampleco.com"

    @pytest.mark.parametrize("props", [
        _flow(reported_entity_cd="COM"),
        _flow(reported_entity_cd=None),
        {k: v for k, v in _flow().items() if k != "reported_entity_cd"},
        _flow(source_schedule="E", flow_type="expenditure"),
        _flow(flow_type="delegated_contract", source_schedule=None, node_id="moneyflow-marincontract-1"),
        _flow(node_id="moneyflow-marincontract-1"),
        _flow(node_id="moneyflow-committee-example-1", flow_type="campaign_contribution",
              source_schedule="schedule_a", address_raw="1 SAMPLE ST"),
    ])
    def test_ineligible_flows_get_nothing(self, props):
        clean = sanitize_node_props("MoneyFlow", props, node_id=props["id"])
        assert _shown(clean) == {}
        assert {k: v for k, v in clean.items() if not k.startswith("reported_")} == \
            {k: v for k, v in props.items() if not k.startswith("reported_")}

    @pytest.mark.parametrize("level, kept", [
        ("city_zip", set(DETAILS)),
        ("city", set(DETAILS) - {"reported_zip5"}),
        ("none", {"reported_occupation", "reported_employer"}),
    ])
    def test_the_knob_dials_locality_without_code_changes(self, level, kept):
        policy = {**ADDRESS_EXPOSURE, "campaign_contributor": level}
        assert set(_shown(sanitize_node_props("MoneyFlow", _flow(), policy=policy))) == kept

    def test_an_unknown_level_fails(self):
        with pytest.raises(ValueError):
            sanitize_node_props("MoneyFlow", _flow(), policy={**ADDRESS_EXPOSURE, "campaign_contributor": "street"})

    def test_a_flow_without_details_is_returned_as_is(self):
        props = {"id": "moneyflow-1400001-e1", "amount": 5.0, "flow_type": "expenditure", "source_schedule": "E"}
        assert sanitize_node_props("MoneyFlow", props) is props


# --- the bake ----------------------------------------------------------------

PERMIT = {"id": "permit-marin-IN_B1_1", "labels": ["Project"], "properties": {
    "id": "permit-marin-IN_B1_1", "address": "12 SAMPLE RD, SAMPLETON, CA 94999", "city_town": "SAMPLETON",
    "display_label": "Permit at 12 SAMPLE RD, SAMPLETON, CA 94999", "project_type": "building_permit",
    "source": "marin-county-socrata-permits", "type_permit": "RESIDENTIAL", "latitude": 37.9, "longitude": -122.5}}


def _node(props: dict) -> dict:
    return {"id": props["id"], "labels": ["MoneyFlow"], "properties": props}


FLOWS = [
    _flow(),
    _flow("moneyflow-1400001-a2", reported_employer="415-555-0199", reported_zip5="94999-0001"),
    _flow("moneyflow-1400001-a3", reported_entity_cd="COM"),
    _flow("moneyflow-marincontract-9", flow_type="delegated_contract", source_schedule=None),
    _flow("moneyflow-committee-example-1", flow_type="campaign_contribution", source_schedule="schedule_a",
          address_raw="1 SAMPLE ST, SAMPLETON", occupation_employer_raw="Engineer / Example Co"),
]


def _bake(tmp_path: Path, flows: list[dict], name: str) -> tuple[Path, dict]:
    root = tmp_path / name
    export, overlay = root / "export", root / "overlay"
    for directory, rows in ((export, [PERMIT, *map(_node, flows)]), (overlay, [])):
        directory.mkdir(parents=True)
        (directory / "nodes.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (directory / "edges.jsonl").write_text("")
    registry = root / "node-types.json"
    registry.write_text(json.dumps({"graph_node_types": {"Project": {}, "MoneyFlow": {}},
                                    "id_prefixes": {"permit-": "Project", "moneyflow-": "MoneyFlow"}}))
    report = bake_substrate(registry_path=registry, sqlite_path=root / "public.sqlite",
                            report_path=root / "report.json", source="live-export", live_export_dir=export,
                            attach_overlay_dir=overlay)
    return root / "public.sqlite", report


def _props(sqlite_path: Path) -> dict[str, dict]:
    with sqlite3.connect(sqlite_path) as conn:
        return {i: json.loads(p) for i, p in conn.execute("SELECT id, props FROM nodes")}


def _rows(sqlite_path: Path, query: str) -> list:
    with sqlite3.connect(sqlite_path) as conn:
        return sorted(conn.execute(query).fetchall())


class TestBake:
    def test_the_bake_publishes_eligible_details_only(self, tmp_path):
        sqlite_path, report = _bake(tmp_path, FLOWS, "rich")
        props = _props(sqlite_path)
        assert _shown(props["moneyflow-1400001-a1"]) == DETAILS
        assert _shown(props["moneyflow-1400001-a2"]) == {k: v for k, v in {**DETAILS, "reported_zip5": "94999"}.items()
                                                          if k != "reported_employer"}
        for ineligible in ("moneyflow-1400001-a3", "moneyflow-marincontract-9", "moneyflow-committee-example-1"):
            assert _shown(props[ineligible]) == {}
        text = json.dumps(props)
        assert "415-555-0199" not in text and "94999-0001" not in text and "SAMPLE ST" not in text
        assert "reported_entity_cd" not in text and "occupation_employer_raw" not in text
        contributor = report["exposure"]["campaign_contributor"]
        assert contributor["level"] == "city_zip"
        assert contributor["eligible_flows"] == 2 and contributor["stripped_ineligible_flows"] == 3
        assert contributor["published"]["reported_employer"] == 1
        assert contributor["withheld_at_bake"] == {"reported_employer": 1}

    def test_search_browse_and_projects_are_unchanged_by_the_details(self, tmp_path):
        bare = [{k: v for k, v in f.items() if k not in DETAILS} for f in FLOWS]
        rich_path, _ = _bake(tmp_path, FLOWS, "rich")
        bare_path, _ = _bake(tmp_path, bare, "bare")
        for query in ("SELECT rowid, * FROM search_fts", "SELECT * FROM browse_rows",
                      "SELECT id, search_label FROM nodes"):
            assert _rows(rich_path, query) == _rows(bare_path, query), query
        assert _props(rich_path)[PERMIT["id"]] == _props(bare_path)[PERMIT["id"]]
        with sqlite3.connect(rich_path) as conn:
            hits = conn.execute("SELECT count(*) FROM search_fts WHERE search_fts MATCH '\"Example Co\"'").fetchone()
        assert hits == (0,)  # published props stay queryable in SQLite, but search never indexes them

    def _texts(self, sqlite_path: Path) -> str:
        with sqlite3.connect(sqlite_path) as conn:
            tables = [t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            return json.dumps([conn.execute(f'SELECT * FROM "{t}"').fetchall() for t in tables], default=str)

    def test_an_ocr_flow_leaks_nothing_anywhere(self, tmp_path):
        ocr = {"id": "moneyflow-committee-example-2", "amount": 50.0, "flow_type": "campaign_contribution",
               "source_schedule": "schedule_a", "display_label": "campaign_contribution $50.00",
               "address_raw": "77 SAMPLEWOOD LN, SAMPLETON CA 94999-0077",
               "occupation_employer_raw": "Welder / Example Forge", "from_actor_label": "Pat Example"}
        sqlite_path, _ = _bake(tmp_path, [ocr], "ocr")
        text = self._texts(sqlite_path)
        for needle in ("SAMPLEWOOD", "94999-0077", "Example Forge"):
            assert needle not in text

    @pytest.mark.parametrize("key", ["display_label", "name", "search_terms"])
    def test_a_withheld_value_repeated_in_other_text_fails_the_bake(self, tmp_path, key):
        contaminated = _flow(reported_employer="415-555-0199", **{key: "contribution from 415-555-0199"})
        with pytest.raises(ValueError, match="withheld contributor value"):
            _bake(tmp_path, [contaminated], "dirty")

    def test_a_published_value_may_appear_elsewhere(self, tmp_path):
        _bake(tmp_path, [_flow(name="Example Co contribution")], "fine")

    def test_the_bake_reads_the_level_and_the_review_decisions(self, tmp_path, monkeypatch):
        import bake_public_substrate
        monkeypatch.setitem(ADDRESS_EXPOSURE, "campaign_contributor", "city")
        monkeypatch.setattr(bake_public_substrate, "load_reviewed",
                            lambda: frozenset({review_key("employer", "Exampleco.com")}))
        sqlite_path, report = _bake(tmp_path, [_flow(reported_employer="Exampleco.com")], "dial")
        shown = _shown(_props(sqlite_path)["moneyflow-1400001-a1"])
        assert shown["reported_employer"] == "Exampleco.com" and "reported_zip5" not in shown
        assert report["exposure"]["campaign_contributor"]["level"] == "city"

    def test_projection_mode_applies_the_same_policy(self, tmp_path):
        bundle_rows = [{"id": f["id"], "node_type": "MoneyFlow", "labels": ["MoneyFlow"],
                        "display_label": f["display_label"], "properties": {k: v for k, v in f.items()
                                                                            if k not in ("id", "display_label")}}
                       for f in FLOWS]
        nodes, edges = tmp_path / "nodes.jsonl", tmp_path / "edges.jsonl"
        nodes.write_text("".join(json.dumps(r) + "\n" for r in bundle_rows))
        edges.write_text("")
        registry = tmp_path / "node-types.json"
        registry.write_text(json.dumps({"graph_node_types": {"MoneyFlow": {}},
                                        "id_prefixes": {"moneyflow-": "MoneyFlow"}}))
        bake_substrate(node_sources=[nodes], edge_sources=[edges], registry_path=registry,
                       sqlite_path=tmp_path / "p.sqlite", report_path=tmp_path / "r.json", source="projection")
        props = _props(tmp_path / "p.sqlite")
        assert _shown(props["moneyflow-1400001-a1"]) == DETAILS
        assert _shown(props["moneyflow-1400001-a3"]) == {} and _shown(props["moneyflow-marincontract-9"]) == {}
        assert "415-555-0199" not in json.dumps(props)
