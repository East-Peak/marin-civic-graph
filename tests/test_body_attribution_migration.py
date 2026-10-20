"""Body attribution, increment (b): the migration re-points only institution_id and AT_INSTITUTION, adds only the
new institutions, and its inverse restores the exact pre-state or refuses. Fictional fixtures (Lakeport)."""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import body_attribution as ba  # noqa: E402
from test_body_attribution_map import BODIES, COMMITTEES, COUNCIL  # noqa: E402

GOV = ["Government", "Organization"]


def node(nid, labels, **props):
    return {"id": nid, "labels": sorted(labels), "properties": {"id": nid, **props}}


def edge(s, t, typ, **props):
    return {"start_id": s, "type": typ, "end_id": t, "properties": props}


def baseline():
    nodes = [
        node(COUNCIL, GOV, name="Lakeport Town Council", jurisdiction_id="place-lakeport", embedding=[0.1, 0.2]),
        node(COMMITTEES, GOV, name="Shoreview Committees", jurisdiction_id="place-shoreview"),
        node("org-shoreview-planning-commission", GOV, name="org-shoreview-planning-commission"),
        node("place-lakeport", ["Place"], name="Lakeport"),
        node("place-shoreview", ["Place"], name="Shoreview"),
        node("place-lake-county", ["Place"], name="Lake County"),
    ]
    edges = [edge(COUNCIL, "place-lakeport", "IN_JURISDICTION"), edge(COMMITTEES, "place-shoreview", "IN_JURISDICTION")]
    rows = [("meeting-lakeport-town-council-10", COUNCIL, "Town Council", "Town Council regular meeting"),
            ("meeting-lakeport-town-council-11", COUNCIL, "Harbor Commission", "Harbor Commission agenda"),
            ("meeting-lakeport-town-council-12", COUNCIL, "Harbor Commission", "Special Joint Meeting of all Boards"),
            ("meeting-lakeport-town-council-13", COUNCIL, "Water District No. 1 Board", "Water District No. 1 Board"),
            ("meeting-shoreview-committees-1", COMMITTEES, "Planning Commission", "Planning Commission Agenda")]
    for mid, inst, cat, title in rows:
        place = "place-lakeport" if inst == COUNCIL else "place-shoreview"
        nodes.append(node(mid, ["Meeting"], institution_id=inst, jurisdiction_id=place, category=cat, title=title,
                          meeting_date="2023-02-01", payload_json="{}", search_terms=title.lower()))
        edges += [edge(mid, inst, "AT_INSTITUTION"), edge(mid, place, "IN_JURISDICTION"),
                  edge(mid, f"record-{mid}-agenda", "EVIDENCED_BY")]
        nodes.append(node(f"record-{mid}-agenda", ["Record"], record_type="meeting_agenda"))
    nodes.append(node("decision-lakeport-town-council-13-vote-0", ["Decision"], meeting_id="meeting-lakeport-town-council-13",
                      source_id="lakeport-town-council", tally="3-0"))
    edges.append(edge("decision-lakeport-town-council-13-vote-0", "meeting-lakeport-town-council-13", "DECIDED_AT"))
    nodes.append(node("agenda-item-11-1", ["AgendaItem"], meeting_id="meeting-lakeport-town-council-11"))
    edges.append(edge("agenda-item-11-1", "meeting-lakeport-town-council-11", "PART_OF_MEETING"))
    return sorted(nodes, key=lambda n: n["id"]), sorted(edges, key=ba.edge_key)


def bodies_with_jurisdictions():
    data = copy.deepcopy(BODIES)
    data["sources"][COUNCIL]["bodies"][1]["jurisdiction_id"] = "place-lake-county"
    return ba.Bodies.from_dict(data)


@pytest.fixture
def world(tmp_path):
    nodes, edges = baseline()
    base = tmp_path / "baseline"
    ba.write_export(base, nodes, edges)
    bodies = bodies_with_jurisdictions()
    registry = tmp_path / "bodies.yaml"
    data = copy.deepcopy(BODIES)
    data["sources"][COUNCIL]["bodies"][1]["jurisdiction_id"] = "place-lake-county"
    registry.write_text(yaml.safe_dump(data))
    return {"dir": base, "nodes": nodes, "edges": edges, "bodies": bodies, "registry": registry, "tmp": tmp_path}


def plan(world):
    rows = ba.build_map(world["nodes"], world["bodies"]).rows
    return ba.plan_migration(world["nodes"], world["edges"], rows, world["bodies"])


# --- the plan ----------------------------------------------------------------------------------------------------

def test_plan_repoints_moved_meetings_and_creates_only_new_institutions(world):
    ops = plan(world)
    assert ops["repoint"] == [
        {"id": "meeting-lakeport-town-council-11", "from": COUNCIL, "to": "org-lakeport-harbor-commission", "props": {}},
        {"id": "meeting-lakeport-town-council-13", "from": COUNCIL, "to": "org-lakeport-water-district-no-1", "props": {}},
        {"id": "meeting-shoreview-committees-1", "from": COMMITTEES, "to": "org-shoreview-planning-commission",
         "props": {}}]
    created = {n["id"]: n for n in ops["create_nodes"]}
    assert sorted(created) == ["org-lakeport-harbor-commission", "org-lakeport-trail-pedestrian-advisory-committee",
                               "org-lakeport-water-district-no-1", "org-shoreview-harbor-mobility-committee"]
    assert created["org-lakeport-water-district-no-1"] == {
        "id": "org-lakeport-water-district-no-1", "labels": GOV, "properties": {
            "id": "org-lakeport-water-district-no-1", "name": "Lakeport Water District No. 1",
            "display_label": "Lakeport Water District No. 1", "subtype": "government",
            "jurisdiction_id": "place-lake-county", "promotion_state": "promoted"}}
    assert {(e["start_id"], e["type"], e["end_id"]) for e in ops["create_edges"]} == {
        (i, "IN_JURISDICTION", created[i]["properties"]["jurisdiction_id"]) for i in created}
    assert ops["reused"] == ["org-shoreview-planning-commission"]


def test_plan_inventories_dependents_of_moved_meetings(world):
    deps = plan(world)["dependents"]
    assert deps["edges_touching_moved"] == {"DECIDED_AT": 1, "EVIDENCED_BY": 3, "IN_JURISDICTION": 3, "PART_OF_MEETING": 1,
                                        "AT_INSTITUTION": 3}
    assert deps["decision_edges"] == {"DECIDED_AT": 1}  # no DECIDED_BY / CAST_VOTE to re-point
    assert deps["institution_fields"] == {}  # no Decision / AgendaItem names an institution


@pytest.mark.parametrize("breakage,match", [
    (lambda n, e: e.append(edge("meeting-lakeport-town-council-11", "org-shoreview-committees", "AT_INSTITUTION")),
     "exactly one AT_INSTITUTION"),
    (lambda n, e: next(x for x in e if x["start_id"] == "meeting-lakeport-town-council-11"
                       and x["type"] == "AT_INSTITUTION")["properties"].update(note="x"), "properties"),
    (lambda n, e: n.append(node("org-lakeport-harbor-commission-board", ["Organization"], name="x")), "near-duplicate"),
    (lambda n, e: n.remove(next(x for x in n if x["id"] == "place-lake-county")), "place-lake-county"),
])
def test_plan_refuses_a_baseline_it_cannot_repoint_exactly(world, breakage, match):
    nodes, edges = copy.deepcopy(world["nodes"]), copy.deepcopy(world["edges"])
    rows = ba.build_map(nodes, world["bodies"]).rows
    breakage(nodes, edges)
    with pytest.raises(ba.AttributionError, match=match):
        ba.plan_migration(nodes, edges, rows, world["bodies"])


@pytest.mark.parametrize("dependent,match", [
    (lambda n, e: _node(n, "decision-lakeport-town-council-13-vote-0")["properties"].update(institution_id=COUNCIL),
     "Decision.institution_id"),
    (lambda n, e: e.append(edge("decision-lakeport-town-council-13-vote-0", COUNCIL, "DECIDED_BY")), "DECIDED_BY"),
])
def test_plan_refuses_a_dependent_that_names_the_old_institution(world, dependent, match):
    nodes, edges = copy.deepcopy(world["nodes"]), copy.deepcopy(world["edges"])
    dependent(nodes, edges)
    rows = ba.build_map(nodes, world["bodies"]).rows
    with pytest.raises(ba.AttributionError, match=match):
        ba.plan_migration(nodes, edges, rows, world["bodies"])


def test_plan_refuses_a_map_whose_meeting_changed_institution_since(world):
    rows = ba.build_map(world["nodes"], world["bodies"]).rows
    nodes = copy.deepcopy(world["nodes"])
    next(n for n in nodes if n["id"] == "meeting-lakeport-town-council-11")["properties"]["institution_id"] = COMMITTEES
    with pytest.raises(ba.AttributionError, match="meeting-lakeport-town-council-11"):
        ba.plan_migration(nodes, world["edges"], rows, world["bodies"])


# --- forward / inverse ---------------------------------------------------------------------------------------------

def test_forward_changes_only_the_planned_rows(world):
    ops = plan(world)
    nodes, edges = ba.apply_ops(world["nodes"], world["edges"], ops)
    before, after = {n["id"]: n for n in world["nodes"]}, {n["id"]: n for n in nodes}
    changed = {i for i in before if before[i] != after[i]}
    assert changed == {r["id"] for r in ops["repoint"]}
    for r in ops["repoint"]:
        diff = {k for k in before[r["id"]]["properties"] | after[r["id"]]["properties"]
                if before[r["id"]]["properties"].get(k) != after[r["id"]]["properties"].get(k)}
        assert diff == {"institution_id"} and after[r["id"]]["properties"]["institution_id"] == r["to"]
    assert set(after) - set(before) == {n["id"] for n in ops["create_nodes"]}
    key = lambda e: ba.stable_line(e)  # noqa: E731
    removed = {key(e) for e in world["edges"]} - {key(e) for e in edges}
    added = {key(e) for e in edges} - {key(e) for e in world["edges"]}
    assert removed == {key(edge(r["id"], r["from"], "AT_INSTITUTION")) for r in ops["repoint"]}
    assert added == {key(edge(r["id"], r["to"], "AT_INSTITUTION")) for r in ops["repoint"]} | \
        {key(e) for e in ops["create_edges"]}


def test_forward_then_inverse_is_byte_identical(world):
    ops = plan(world)
    nodes, edges = ba.apply_ops(world["nodes"], world["edges"], ops)
    assert ba.inverse_problems(nodes, edges, ops) == []
    back = ba.apply_inverse(nodes, edges, ops)
    out = ba.write_export(world["tmp"] / "back", *back)
    assert out == ba.fingerprint(world["dir"])
    assert (world["tmp"] / "back" / "nodes.jsonl").read_bytes() == (world["dir"] / "nodes.jsonl").read_bytes()


def _compensating_drift(nodes, edges):
    gone = next(e for e in edges if e["start_id"] == "org-lakeport-harbor-commission" and e["type"] == "IN_JURISDICTION")
    edges.remove(gone)
    twice = next(e for e in edges if e["start_id"] == "org-lakeport-water-district-no-1" and e["type"] == "IN_JURISDICTION")
    edges.append(copy.deepcopy(twice))


@pytest.mark.parametrize("drift,match", [
    (lambda n, e: _node(n, "org-lakeport-harbor-commission")["properties"].update(website="x"), "properties"),
    (lambda n, e: _node(n, "org-lakeport-harbor-commission")["labels"].append("Committee"), "labels"),
    (lambda n, e: e.append(edge("decision-lakeport-town-council-13-vote-0", "org-lakeport-water-district-no-1",
                                "DECIDED_BY")), "relationships"),
    (lambda n, e: next(x for x in e if x["start_id"] == "org-lakeport-harbor-commission")["properties"].update(a=1),
     "relationships"),
    (lambda n, e: e.append(edge("meeting-lakeport-town-council-11", "org-lakeport-harbor-commission", "AT_INSTITUTION")),
     "relationships|AT_INSTITUTION"),
    (lambda n, e: _node(n, "meeting-lakeport-town-council-13")["properties"].update(institution_id=COUNCIL),
     "institution_id"),
    (lambda n, e: n.remove(_node(n, "org-lakeport-trail-pedestrian-advisory-committee")), "missing"),
    (_compensating_drift, "relationships"),
    (lambda n, e: _node(n, "meeting-lakeport-town-council-13")["labels"].remove("Meeting"), "Meeting"),
    (lambda n, e: n.remove(_node(n, COUNCIL)), COUNCIL),
    (lambda n, e: _node(n, "place-lake-county")["labels"].remove("Place"), "place-lake-county"),
])
def test_inverse_refuses_when_its_creations_acquired_other_data(world, drift, match):
    """Includes compensating drift: one institution loses its jurisdiction edge and another gains a second."""
    ops = plan(world)
    nodes, edges = ba.apply_ops(world["nodes"], world["edges"], ops)
    drift(nodes, edges)
    problems = ba.inverse_problems(nodes, edges, ops)
    assert problems and any(__import__("re").search(match, p) for p in problems), problems
    with pytest.raises(ba.AttributionError):
        ba.apply_inverse(nodes, edges, ops)


def _node(nodes, nid):
    return next(n for n in nodes if n["id"] == nid)


# --- Cypher: exact counts, one transaction ------------------------------------------------------------------------

def test_statements_cover_every_row_with_exact_counts(world):
    ops = plan(world)
    stmts = ba.statements(ops)
    steps = [s["step"] for s in stmts]
    assert steps == ["precheck:new_institutions_absent", "precheck:reused_institutions_present",
                     "precheck:places_present", "precheck:meetings_at_from", "create:institutions",
                     "create:institution_jurisdictions", "repoint:set_institution_id", "repoint:delete_old_edge",
                     "repoint:create_new_edge"]
    expect = {s["step"]: s["expect"] for s in stmts}
    assert expect["precheck:new_institutions_absent"] == 0
    assert expect["create:institutions"] == 4 and expect["repoint:delete_old_edge"] == 3
    assert all("RETURN count(" in s["query"] for s in stmts)
    inv = [s["step"] for s in ba.inverse_statements(ops)]
    assert inv[:6] == ["guard:institutions_as_created", "guard:institution_incident_counts",
                       "guard:created_jurisdictions_exact", "guard:created_attributions_exact",
                       "guard:old_institutions_present", "guard:meetings_at_to"]
    assert inv[6:] == ["restore:delete_new_edge", "restore:create_old_edge", "restore:set_institution_id",
                       "restore:delete_institution_jurisdictions", "restore:delete_institutions"]


class CountingTx:
    """Answers each statement with its planned count, except `wrong_at` (0-based), where it answers one more."""

    def __init__(self, stmts, wrong_at=None):
        self.expect, self.wrong_at, self.ran = [s["expect"] for s in stmts], wrong_at, []

    def run(self, query, **params):
        i = len(self.ran)
        self.ran.append(query)
        n = self.expect[i] + (1 if i == self.wrong_at else 0)
        return type("R", (), {"single": lambda self_: {"n": n}})()


def test_a_count_off_plan_midway_stops_before_the_next_statement(world):
    ops = plan(world)
    stmts = ba.statements(ops)
    k = [s["step"] for s in stmts].index("repoint:delete_old_edge")
    tx = CountingTx(stmts, wrong_at=k)
    with pytest.raises(ba.StatementCountError, match="repoint:delete_old_edge"):
        ba.apply_in_transaction(tx, ops)
    assert len(tx.ran) == k + 1  # nothing after it ran; the caller rolls the transaction back
    assert ba.apply_in_transaction(CountingTx(stmts), ops)["repoint:create_new_edge"] == 3


NEO4J = os.environ.get("BODY_ATTRIBUTION_TEST_NEO4J")  # a throwaway instance, never 7687 / 7688


@pytest.mark.skipif(not NEO4J, reason="needs a throwaway Neo4j (BODY_ATTRIBUTION_TEST_NEO4J=bolt://localhost:<port>)")
def test_cypher_matches_the_pure_twins_and_rolls_back_midway(world):
    """On a real (throwaway) Neo4j: forward == the pure candidate, inverse == the baseline, byte for byte; a failure
    midway through re-pointing leaves the graph exactly as it was."""
    from neo4j_target import open_driver
    from export_live_graph import export_live_graph

    assert not NEO4J.endswith((":7687", ":7688"))
    driver = open_driver(NEO4J, auth=("neo4j", os.environ.get("BODY_ATTRIBUTION_TEST_NEO4J_PASSWORD", "throwaway")))
    db = "neo4j"
    ops = plan(world)

    def export(name):  # the export's own bytes, as the apply's fingerprints see them
        out = world["tmp"] / name
        export_live_graph(driver, database=db, out_dir=out, backup=True, progress=None)
        return ba.fingerprint(out)

    def pure(name, nodes, edges):
        return ba.write_export(world["tmp"] / name, nodes, edges)

    try:
        with driver.session(database=db) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            for n in world["nodes"]:
                s.run(f"CREATE (n:{':'.join(n['labels'])}) SET n = $p", p=n["properties"]).consume()
            for e in world["edges"]:
                s.run(f"MATCH (a {{id: $s}}), (b {{id: $t}}) CREATE (a)-[r:{e['type']}]->(b) SET r = $p",
                      s=e["start_id"], t=e["end_id"], p=e["properties"]).consume()
        assert export("seeded") == pure("p-seeded", world["nodes"], world["edges"])
        broken = copy.deepcopy(ops)
        broken["repoint"][-1]["from"] = "org-nowhere"  # the last re-point's old edge is not there: count off plan
        with driver.session(database=db) as s:
            tx = s.begin_transaction()
            with pytest.raises(ba.StatementCountError):
                ba.run_statements(tx, [st for st in ba.statements(broken) if not st["step"].startswith("precheck")])
            tx.rollback()
        assert export("after-rollback") == pure("p-rollback", world["nodes"], world["edges"])
        with driver.session(database=db) as s:
            tx = s.begin_transaction()
            ba.apply_in_transaction(tx, ops)
            tx.commit()
        forward = export("forward")
        assert forward == pure("p-forward", *ba.apply_ops(world["nodes"], world["edges"], ops))
        with driver.session(database=db) as s:  # compensating drift: the inverse refuses and changes nothing
            s.run("MATCH (:Organization {id: 'org-lakeport-harbor-commission'})-[r:IN_JURISDICTION]->() DELETE r").consume()
            s.run("MATCH (o:Organization {id: 'org-lakeport-water-district-no-1'}), (p:Place {id: 'place-lake-county'}) "
                  "CREATE (o)-[:IN_JURISDICTION]->(p)").consume()
        drifted = export("drifted")
        with driver.session(database=db) as s:
            tx = s.begin_transaction()
            with pytest.raises(ba.StatementCountError, match="guard"):
                ba.inverse_in_transaction(tx, ops)
            tx.rollback()
        assert export("drift-refused") == drifted
        with driver.session(database=db) as s:  # undo the drift by hand, then the inverse restores the baseline
            s.run("MATCH (:Organization {id: 'org-lakeport-water-district-no-1'})-[r:IN_JURISDICTION]->() "
                  "WITH r LIMIT 1 DELETE r").consume()
            s.run("MATCH (o:Organization {id: 'org-lakeport-harbor-commission'}), (p:Place {id: 'place-lakeport'}) "
                  "CREATE (o)-[:IN_JURISDICTION]->(p)").consume()
        assert export("undrifted") == forward
        with driver.session(database=db) as s:
            tx = s.begin_transaction()
            ba.inverse_in_transaction(tx, ops)
            tx.commit()
        assert export("inverse") == ba.fingerprint(world["dir"])
    finally:
        driver.close()


# --- the plan bundle ------------------------------------------------------------------------------------------------

def test_write_plan_binds_the_map_to_its_baseline_and_proves_the_inverse(world, monkeypatch):
    monkeypatch.setattr(ba, "STAGING_ROOT", world["tmp"] / "staging")
    m = world["tmp"] / "staging" / "map"
    ba.write_map(world["dir"], world["registry"], m)
    report = ba.write_plan(world["dir"], m, world["registry"], world["tmp"] / "staging" / "plan")
    plan_dir = world["tmp"] / "staging" / "plan"
    assert report["baseline"]["sha256"] == ba.fingerprint(world["dir"])
    assert report["candidate_sha256"] == ba.fingerprint(plan_dir / "candidate")
    assert report["verification"] == []
    proof = json.loads((plan_dir / "inverse-identity.json").read_text())
    assert proof["identical"] is True and proof["restored_sha256"] == report["baseline"]["sha256"]
    assert json.loads((plan_dir / "ops.json").read_text())["repoint"][0]["id"] == "meeting-lakeport-town-council-11"
    # a map drawn from another baseline is refused
    other = world["tmp"] / "other"
    nodes, edges = copy.deepcopy(world["nodes"]), world["edges"]
    _node(nodes, "place-lakeport")["properties"]["name"] = "Lakeport!"
    ba.write_export(other, nodes, edges)
    with pytest.raises(ba.AttributionError, match="baseline"):
        ba.write_plan(other, m, world["registry"], world["tmp"] / "staging" / "plan2")
    # a hand-edited map is refused: the reviewed map must be the one the code draws
    (m / "map.jsonl").write_text((m / "map.jsonl").read_text().replace("org-lakeport-harbor-commission",
                                                                     "org-lakeport-water-district-no-1", 1))
    with pytest.raises(ba.AttributionError, match="map"):
        ba.write_plan(world["dir"], m, world["registry"], world["tmp"] / "staging" / "plan3")
