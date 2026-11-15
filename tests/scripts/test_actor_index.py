"""Actor index: the registry is the identity gate; one facts table; narrow totals; labelled connections
(invented fixtures, tests/scripts/actor_world.py)."""
import copy
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
sys.path.insert(0, str(HERE))

import actor_index as ai  # noqa: E402
import actor_world as w  # noqa: E402


def build(tmp_path, name="actors.sqlite", **world):
    inputs = w.make_world(tmp_path, **world)
    out = tmp_path / name
    report = ai.build_index(inputs, out)
    return out, report


def rows(db: Path, sql: str, *args) -> list[dict]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def facts(db, **where) -> list[dict]:
    clause = " AND ".join(f"{k} = ?" for k in where) or "1"
    return rows(db, f"SELECT * FROM facts WHERE {clause} ORDER BY fact_key", *where.values())


@pytest.fixture
def world_db(tmp_path):
    return build(tmp_path)[0]


# --- determinism and registry gate -------------------------------------------------------------------------------

def test_two_builds_have_identical_row_sets(tmp_path):
    inputs = w.make_world(tmp_path)
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    ai.build_index(inputs, a)
    ai.build_index(inputs, b)
    tables = [r["name"] for r in rows(a, "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    assert {"facts", "actors", "cases", "connections", "coverage", "totals", "by_year", "name_overlaps"} <= set(tables)
    for t in tables:
        assert sorted(map(repr, rows(a, f"SELECT * FROM {t}"))) == sorted(map(repr, rows(b, f"SELECT * FROM {t}"))), t


@pytest.mark.parametrize("field,value,message", [
    ("substrate_ids", ["org-harbor-shelter"], "org-harbor-shelter"),
    ("eins", ["001110001"], "001110001"),
])
def test_overlapping_registry_ids_or_eins_fail_loudly(tmp_path, field, value, message):
    reg = w.registry_with(**{"lantern-fund": {field: value}})
    with pytest.raises(ai.RegistryError, match=message):
        build(tmp_path, registry=reg)


def test_one_string_matching_two_actors_reviewed_patterns_fails(tmp_path):
    ledger = w.LEDGER + [w.ledger_row(9, "meeting-fernwood-bos-3", "MAY 1, 2030", "1",
                                      "Harbor Shelter and Lantern Fund", "county_pays", 1)]
    with pytest.raises(ai.RegistryError, match="harbor-shelter.*lantern-fund|lantern-fund.*harbor-shelter"):
        build(tmp_path, ledger=ledger)


def test_a_match_nested_in_another_actors_match_belongs_to_the_outer_actor(world_db):
    firm = facts(world_db, kind="docket_appearance", actor_slug="quill-law")
    person = facts(world_db, kind="docket_appearance", actor_slug="oda-quill")
    assert [json.loads(f["detail"])["field"] for f in firm] == ["firm"]
    assert [(json.loads(f["detail"])["field"], f["quote"]) for f in person] == [("attorney", "Oda Quill")]
    north = rows(world_db, "SELECT * FROM facts WHERE actor_slug = 'tidepool-union-north'")
    assert north == []  # 'TIDEPOOL TENANTS UNION' never reaches the chapter that is merely affiliated


# --- identity: id and EIN before pattern; exclusions; unreviewed patterns ---------------------------------------

def test_substrate_id_attaches_and_a_matching_name_under_another_id_does_not(world_db):
    dc = facts(world_db, kind="delegated_contract")
    assert [(f["actor_slug"], f["source_ref"], f["identity_basis"]) for f in dc] == [
        ("harbor-shelter", "moneyflow-dc-1", "substrate_id")]  # dc-2's target is named 'Harbor Shelter Thrift Store'
    gift = facts(world_db, kind="political_gift")
    assert [(f["actor_slug"], f["amount"], f["identity_basis"], f["direction"]) for f in gift] == [
        ("lantern-fund", 250.0, "substrate_id", "actor_gives")]


def test_ein_beats_the_name_on_a_schedule_i_row(world_db):
    (g,) = [f for f in facts(world_db, kind="reported_grant") if f["counterparty_name"] == "Totally Different Name"]
    assert (g["actor_slug"], g["identity_basis"], g["counterparty_slug"], g["counterparty_basis"]) == (
        "lantern-fund", "ein", "harbor-shelter", "ein")


def test_a_name_match_on_an_ein_the_registry_does_not_list_is_only_a_possible_match(tmp_path):
    returns = copy.deepcopy(w.RETURNS)
    returns["300000000000000002_public.xml"]["grants"].append(w.grant("Harbor Shelter", cash="90", ein="009990009"))
    db, _ = build(tmp_path, returns=returns)
    (g,) = [f for f in facts(db, kind="reported_grant") if f["amount"] == 90.0]
    assert (g["counterparty_slug"], g["counterparty_basis"]) == ("harbor-shelter", "pattern_ein_not_in_registry")
    assert json.loads(g["detail"])["recipient_ein"] == "009990009"
    (received,) = rows(db, "SELECT * FROM totals WHERE actor_slug = 'harbor-shelter' AND kind = 'reported_grant' "
                           "AND metric = 'cash_grant'")
    assert received["amount"] == 600.0  # the EIN-attached row only


def test_pattern_exclusion_holds(world_db):
    saint = facts(world_db, kind="board_item", actor_slug="saint-example")
    assert [json.loads(f["detail"])["counterparty"] for f in saint] == ["St Example"]


def test_unreviewed_pattern_facts_are_possible_matches_never_totals_or_connections(world_db):
    possible = facts(world_db, actor_slug="generic-charities")
    assert {f["kind"] for f in possible} == {"board_item", "minutes_mentions"}
    assert {f["identity_basis"] for f in possible} == {"pattern_unreviewed"}
    (as_recipient,) = facts(world_db, kind="reported_grant", counterparty_slug="generic-charities")
    assert as_recipient["counterparty_basis"] == "pattern_unreviewed"
    assert rows(world_db, "SELECT * FROM totals WHERE actor_slug = 'generic-charities'") == []
    assert rows(world_db, "SELECT * FROM by_year WHERE actor_slug = 'generic-charities'") == []
    assert all("generic-charities" not in c["actors"] for c in rows(world_db, "SELECT * FROM connections"))


def test_affiliated_actors_are_never_merged(world_db):
    actors = {a["slug"]: a for a in rows(world_db, "SELECT * FROM actors")}
    assert {"tidepool-union", "tidepool-union-north", "quill-law", "oda-quill"} <= set(actors)
    assert json.loads(actors["tidepool-union"]["affiliated_with"]) == ["tidepool-union-north"]
    assert facts(world_db, actor_slug="tidepool-union-north") == []
    assert facts(world_db, kind="case_role", actor_slug="tidepool-union")


# --- totals ------------------------------------------------------------------------------------------------------

def test_totals_never_mix_kinds_metrics_or_directions(world_db):
    totals = rows(world_db, "SELECT * FROM totals")
    keys = [(t["actor_slug"], t["side"], t["kind"], t["metric"], t["direction"]) for t in totals]
    assert len(keys) == len(set(keys))
    own = {(t["metric"], t["n"], t["amount"]) for t in totals if t["actor_slug"] == "lantern-fund"
           and t["kind"] == "own_return"}
    assert own == {("total_revenue", 5, 111 + 50 + 60 + 70 + 80), ("government_grants", 5, 11 + 4)}
    harbor_board = {(t["direction"], t["n"], t["amount"]) for t in totals if t["actor_slug"] == "harbor-shelter"
                    and t["kind"] == "board_item"}
    assert harbor_board == {("county_pays", 2, 6000), ("county_receives", 1, 700)}  # no_money has no amount


def test_repeat_rows_are_kept_but_excluded_from_totals_with_the_fixed_note(world_db):
    board = facts(world_db, kind="board_item", actor_slug="harbor-shelter")
    repeats = [f for f in board if f["repeat_of"]]
    assert len(board) == 5 and len(repeats) == 1
    first = next(f for f in board if f["fact_key"] == repeats[0]["repeat_of"])
    assert json.loads(first["detail"])["line"] == 2 and json.loads(repeats[0]["detail"])["line"] == 3
    (pays,) = rows(world_db, "SELECT * FROM totals WHERE actor_slug = 'harbor-shelter' AND kind = 'board_item' "
                             "AND direction = 'county_pays'")
    assert pays["note"] == "amendments restate agreement ceilings; this sum overcounts"


def test_reported_grants_keep_cash_and_noncash_apart_and_are_stored_once(world_db):
    tidepool = facts(world_db, kind="reported_grant", counterparty_slug="tidepool-union")
    assert sorted((f["metric"], f["amount"]) for f in tidepool) == [("cash_grant", 450.0), ("noncash_assistance", 25.0)]
    assert all(f["actor_slug"] == "lantern-fund" for f in tidepool)
    sides = {(t["actor_slug"], t["side"], t["metric"]) for t in rows(world_db, "SELECT * FROM totals WHERE "
                                                                                "kind = 'reported_grant'")}
    assert ("lantern-fund", "subject", "cash_grant") in sides and ("tidepool-union", "counterparty", "cash_grant") in sides


# --- returns ----------------------------------------------------------------------------------------------------

def test_return_selection_picks_the_amendment_across_every_year(world_db):
    own = facts(world_db, kind="own_return", actor_slug="lantern-fund", metric="total_revenue")
    assert sorted((f["date"], f["amount"]) for f in own) == [
        ("2025", 50.0), ("2026", 60.0), ("2027", 70.0), ("2028", 80.0), ("2029", 111.0)]
    assert all("300000000000000001" not in f["source_ref"] for f in facts(world_db))
    (cov,) = rows(world_db, "SELECT * FROM coverage WHERE input = 'form_990' AND item = '002220002'")
    assert json.loads(cov["detail"])["superseded"] == ["300000000000000001"]


def test_equal_timestamps_prefer_the_amended_return():
    base = {"ein": "1", "tax_year": "2029", "return_type": "990", "status": "ok", "return_ts": "2030-01-01T00:00:00Z"}
    chosen = ai.select_returns([dict(base, object_id="9", amended=False), dict(base, object_id="1", amended=True)])
    assert chosen[("1", "2029")]["chosen"]["object_id"] == "1"
    assert chosen[("1", "2029")]["superseded"] == ["9"]


# --- cases and people -------------------------------------------------------------------------------------------

def test_sides_come_only_from_the_roles_file(world_db):
    roles = facts(world_db, kind="case_role")
    assert sorted((f["actor_slug"], json.loads(f["detail"])["role"]) for f in roles) == [
        (w.COUNTY, "defendant"), ("quill-law", "plaintiff_counsel"), ("tidepool-union", "plaintiff")]
    assert {f["assertion_status"] for f in roles} == {"reviewed_role"}
    appearances = facts(world_db, kind="docket_appearance")
    assert appearances and {f["assertion_status"] for f in appearances} == {"side_unknown"}
    assert all("side not established" in f["label"] for f in appearances)
    (brookvale,) = facts(world_db, kind="docket_appearance", actor_slug=w.TOWN)
    assert json.loads(brookvale["detail"])["docket"] == "9:31-cv-00002"


def test_every_cached_docket_is_a_case_and_no_attorney_is_stated_as_such(world_db):
    cases = {c["docket"]: c for c in rows(world_db, "SELECT * FROM cases")}
    assert set(cases) == {"9:30-cv-00001", "9:31-cv-00002"}
    one, two = cases["9:30-cv-00001"], cases["9:31-cv-00002"]
    assert (one["roles_reviewed"], two["roles_reviewed"]) == (1, 0)
    assert json.loads(one["firms"]) == ["Law Offices of Oda Quill", "Defense Partners LLP"]
    assert one["courtlistener_url"] == "https://courts.example/docket/70000001/"
    assert one["outcome_kind"] == "stipulated_dismissal" and one["outcome_evidence"] == "docket entries 40, 41"
    assert json.loads(two["attorneys"]) == [] and two["attorney_note"] == "no attorney listed in the source"
    assert "self" not in json.dumps(two).lower()


def test_officers_become_person_entries_and_name_overlaps_are_unconfirmed(world_db):
    officers = [f for f in facts(world_db, kind="officer") if f["actor_slug"] in ("harbor-shelter", "lantern-fund")]
    names = {f["counterparty_name"] for f in officers}
    assert names == {"Wren Ambler", "Pell Corder", "Pell Corder Jr.", "Ash Wilder"}
    people = {a["slug"]: a for a in rows(world_db, "SELECT * FROM actors WHERE registered = 0 AND kind = 'person'")}
    assert all(f["counterparty_slug"] in people for f in officers)
    overlaps = rows(world_db, "SELECT * FROM name_overlaps ORDER BY name_norm, right_kind")
    pairs = {(o["name_norm"], o["left_org"], o["right_kind"], o["right_org"]) for o in overlaps}
    assert ("PELL CORDER", "Harbor Shelter", "officer", "Lantern Fund") in pairs or \
        ("PELL CORDER", "Lantern Fund", "officer", "Harbor Shelter") in pairs
    assert any(o["name_norm"] == "WREN AMBLER" and o["right_kind"] == "official" for o in overlaps)
    assert {o["note"] for o in overlaps} == {"same name, not confirmed the same person"}
    assert all(o["left_source"] and o["right_source"] for o in overlaps)


def test_one_filer_under_two_legal_names_is_not_an_overlap_with_itself():
    people = [{"kind": "officer", "name": "Ada Brook", "norm": "ADA BROOK", "org": name, "org_key": "005550005",
               "source": f"990 {oid}"} for name, oid in (("Example School Fund", "1"), ("Example School Fund Dba X", "2"))]
    assert ai.name_overlaps(people, []) == []
    people.append(dict(people[0], org="Other Fund", org_key="006660006", source="990 3"))
    assert [o[3] for o in ai.name_overlaps(people, [])] == ["Example School Fund"]


def test_officers_of_a_filer_outside_the_registry_get_entries_reachable_from_the_filer(world_db):
    (filer,) = rows(world_db, "SELECT * FROM actors WHERE slug = 'filer-007770007'")
    assert (filer["name"], filer["registered"], filer["reviewed"]) == ("Brook Library Friends", 0, 0)
    (ivy,) = facts(world_db, kind="officer", actor_slug="filer-007770007")
    assert ivy["counterparty_name"] == "Ivy Reed" and ivy["identity_basis"] == "ein"
    (person,) = rows(world_db, "SELECT * FROM actors WHERE slug = ?", ivy["counterparty_slug"])
    assert (person["kind"], person["registered"], person["organization_slug"]) == ("person", 0, "filer-007770007")
    assert all("filer-007770007" not in c["actors"] for c in rows(world_db, "SELECT * FROM connections"))


def test_a_registered_person_gets_the_same_page_shape(world_db):
    (person,) = rows(world_db, "SELECT * FROM actors WHERE slug = 'oda-quill'")
    assert (person["kind"], person["registered"], person["reviewed"]) == ("person", 1, 1)


# --- connections -------------------------------------------------------------------------------------------------

FORBIDDEN = re.compile(r"\b(paid|funded|payment)\b", re.I)


def money_and_case_paths(db):
    return [c for c in rows(db, "SELECT * FROM connections ORDER BY connection_id") if c["form"] != "shared_officer"]


def litigation_world():
    """Only the chain under test: the county commits to the fund, the fund reports a grant to the union, the union
    sues the county. (The full world's EIN-attached grant to the shelter would add a second, shorter path.)"""
    returns = copy.deepcopy(w.RETURNS)
    amended = returns["300000000000000002_public.xml"]
    amended["grants"] = [w.grant("Tidepool Tenants Union", cash="450")]
    return returns


def test_the_commitment_grant_litigation_path_is_emitted_with_four_labelled_sources(tmp_path):
    db, _ = build(tmp_path, returns=litigation_world())
    (path,) = money_and_case_paths(db)
    hops = json.loads(path["hops"])
    assert path["form"] == "commitment_grant_litigation"
    assert json.loads(path["actors"]) == [w.COUNTY, "lantern-fund", "tidepool-union", w.COUNTY]
    assert [h["kind"] for h in hops] == ["board_item", "reported_grant", "case_role", "case_role"]
    sources = [s for h in hops for s in h["sources"]]
    assert len(sources) == 4 and all(s["label"] and s["source_ref"] and s["date"] for s in sources)
    assert [h["metric"] for h in hops[:2]] == ["stated_in_item", "cash_grant"]
    assert [s["source_ref"] for s in sources] == ["meeting-fernwood-bos-1 item CA-1",
                                                  "990 300000000000000002 Schedule I row 1",
                                                  "docket 9:30-cv-00001", "docket 9:30-cv-00001"]


def test_cash_and_noncash_share_one_grant_hop_with_their_own_metrics(world_db):
    (path,) = [c for c in money_and_case_paths(world_db) if c["form"] == "commitment_grant_litigation"]
    grant_hop = json.loads(path["hops"])[1]
    assert grant_hop["metric"] == "cash_grant, noncash_assistance"
    assert sorted((s["metric"], s["amount"]) for s in grant_hop["sources"]) == [
        ("cash_grant", 450.0), ("noncash_assistance", 25.0)]


def test_removing_one_review_flag_removes_the_path(tmp_path):
    reg = w.registry_with(**{"tidepool-union": {"patterns": [{"match": "TIDEPOOL TENANTS UNION", "reviewed": False}]}})
    db, _ = build(tmp_path, registry=reg, returns=litigation_world())
    assert money_and_case_paths(db) == []
    reg = w.registry_with(**{"lantern-fund": {"reviewed": False}})
    db, _ = build(tmp_path, name="b.sqlite", registry=reg, returns=litigation_world())
    assert money_and_case_paths(db) == []


def test_shared_officer_names_are_connections_marked_unconfirmed(world_db):
    (shared,) = [c for c in rows(world_db, "SELECT * FROM connections") if c["form"] == "shared_officer"]
    assert sorted(json.loads(shared["actors"])) == ["harbor-shelter", "lantern-fund"]
    assert "not confirmed the same person" in shared["label"]


def test_generated_hop_labels_never_use_the_forbidden_words(world_db):
    for c in rows(world_db, "SELECT * FROM connections"):
        for h in json.loads(c["hops"]):
            assert not FORBIDDEN.search(h["label"]), h
            assert all(not FORBIDDEN.search(s["label"]) for s in h["sources"])
    for f in rows(world_db, "SELECT * FROM facts WHERE kind IN ('board_item', 'delegated_contract', 'reported_grant')"):
        assert not FORBIDDEN.search(f["label"]), f["label"]
    assert ai.hop_label({"kind": "board_item", "direction": "county_pays"}) == "committed (stated in a board item)"
    assert ai.hop_label({"kind": "delegated_contract"}) == "contract ceiling"
    assert ai.hop_label({"kind": "reported_grant"}) == "reported grant"


def test_the_full_world_also_has_the_shorter_commitment_grant_path(world_db):
    forms = sorted((c["form"], c["actors"]) for c in money_and_case_paths(world_db))
    assert forms == [("commitment_grant", json.dumps([w.COUNTY, "lantern-fund", "harbor-shelter"])),
                     ("commitment_grant_litigation",
                      json.dumps([w.COUNTY, "lantern-fund", "tidepool-union", w.COUNTY]))]


def test_no_path_records_what_was_searched(tmp_path):
    db, report = build(tmp_path, roles={"reviewed_on": "2030-01-15", "cases": []}, returns=litigation_world())
    assert [c["form"] for c in money_and_case_paths(db)] == ["commitment_grant"]
    searched = report["connections"]["searched"]
    assert set(searched["forms"]) == {"commitment_grant", "commitment_grant_litigation", "shared_officer"}
    assert searched["reviewed_cases"] == 0
    (meta,) = rows(db, "SELECT value FROM meta WHERE key = 'connections_searched'")
    assert json.loads(meta["value"]) == searched  # the pages state what was searched when nothing was found


# --- privacy and coverage ----------------------------------------------------------------------------------------

def test_no_address_from_any_input_reaches_the_index(world_db):
    con = sqlite3.connect(world_db)
    dump = "\n".join(con.iterdump())
    con.close()
    for s in w.SENTINELS:
        assert s not in dump, s
    assert "12 Sentinel" not in dump and "[address withheld]" in dump


def test_coverage_separates_not_covered_from_none_found(world_db):
    cov = {(c["input"], c["item"]): c for c in rows(world_db, "SELECT * FROM coverage")}
    assert cov[("city_contracts", "all cities")]["state"] == "absent"
    assert cov[("dockets", "9:30-cv-00001")]["state"] == "cached, roles reviewed"
    assert cov[("dockets", "9:31-cv-00002")]["state"] == "cached, no reviewed roles"
    assert cov[("form_990", "001110001")]["state"] == "held"
    assert json.loads(cov[("form_990", "001110001")]["detail"])["tax_years"] == ["2029"]
    assert cov[("form_990_registry", "tidepool-union")]["state"] == "no EIN in the registry"
    assert ("minutes", "Fernwood Council") in cov


def test_minutes_mentions_are_page_counts_per_body(world_db):
    m = {(f["actor_slug"], f["counterparty_name"]): f["amount"] for f in facts(world_db, kind="minutes_mentions")}
    assert m[("harbor-shelter", "Fernwood Council")] == 2 and m[("harbor-shelter", "Fernwood Parks")] == 1
    assert m[("lantern-fund", "Fernwood Council")] == 1
    assert {f["assertion_status"] for f in facts(world_db, kind="minutes_mentions")} == {"count_only"}


def test_missing_minutes_index_is_coverage_not_failure(tmp_path):
    db, _ = build(tmp_path, minutes=None)
    assert facts(db, kind="minutes_mentions") == []
    assert rows(db, "SELECT state FROM coverage WHERE input = 'minutes'") == [{"state": "absent"}]


def test_identity_candidates_use_the_ledger_queue_shape(tmp_path):
    db, _ = build(tmp_path)
    lines = (tmp_path / "identity-candidates.jsonl").read_text().splitlines()
    (row,) = [json.loads(line) for line in lines]
    assert {row["subject_ref"], row["target_ref"]} == {"org-harbor-shelter", "org-bmf-ein-001110001"}
    assert row["status"] == "queued" and row["id"].startswith("assertion-")


def test_copy_inputs_writes_a_manifest_and_refuses_to_overwrite(tmp_path):
    src = w.make_world(tmp_path)
    dest = tmp_path / "inputs"
    manifest = ai.copy_inputs(src.ledger, src.dockets, dest, copied_on="2030-02-02")
    assert (dest / "board-ledger.jsonl").read_bytes() == src.ledger.read_bytes()
    assert {f["file"] for f in manifest["files"]} == {"board-ledger.jsonl", "dockets/70000001.json",
                                                       "dockets/70000002.json"}
    assert json.loads((dest / "inputs-manifest.json").read_text())["copied_on"] == "2030-02-02"
    (dest / "board-ledger.jsonl").write_text("changed\n")
    with pytest.raises(ai.IndexBuildError, match="differs"):
        ai.copy_inputs(src.ledger, src.dockets, dest, copied_on="2030-02-03")


def test_a_copied_input_that_no_longer_matches_its_manifest_fails_the_build(tmp_path):
    src = w.make_world(tmp_path)
    dest = tmp_path / "inputs"
    ai.copy_inputs(src.ledger, src.dockets, dest, copied_on="2030-02-02")
    (dest / "board-ledger.jsonl").write_text((dest / "board-ledger.jsonl").read_text() + "\n")
    inputs = ai.Inputs(**{**src.__dict__, "ledger": dest / "board-ledger.jsonl", "dockets": dest / "dockets"})
    with pytest.raises(ai.IndexBuildError, match="manifest"):
        ai.build_index(inputs, tmp_path / "x.sqlite")


# --- Codex review round 1 ----------------------------------------------------------------------------------------

ADDRESSY = re.compile(r"\b\d{1,6}\s+(?:[A-Z][a-z]+\s+){0,3}(?:Street|Avenue|Road|Lane|Alto|Camino)\b|Camino Alto",
                      re.I)


def test_no_address_survives_in_keys_details_or_case_fields(tmp_path):
    dockets = copy.deepcopy(w.DOCKETS)
    res = dockets["70000001.json"]["results"][0]
    res["party"].append(f"Harbor Shelter, {w.address(12, w.STREET)}")
    res["cause"] = "Civil rights; premises at 40 Camino Alto"
    roles = copy.deepcopy(w.ROLES)
    roles["cases"][0]["outcome"]["evidence"] = f"entry 41 (site at {w.address(9, w.ROAD)})"
    ledger = w.LEDGER + [w.ledger_row(10, "meeting-fernwood-bos-3", "MAY 1, 2030", "9", "Harbor Shelter",
                                      "county_pays", 5, quote="lease of 12 Camino Alto for Harbor Shelter")]
    db, _ = build(tmp_path, dockets=dockets, roles=roles, ledger=ledger)
    con = sqlite3.connect(db)
    dump = "\n".join(con.iterdump())
    con.close()
    assert not ADDRESSY.search(dump), ADDRESSY.search(dump)


def test_one_grant_row_with_several_possible_recipients_counts_once_for_the_grantor(tmp_path):
    reg = w.registry_with(**{"saint-example": {"patterns": [{"match": "OF SOMEWHERE", "reviewed": False}]}})
    db, _ = build(tmp_path, registry=reg)
    grant = [f for f in facts(db, kind="reported_grant") if f["amount"] == 70.0]
    assert sorted(f["counterparty_slug"] for f in grant) == ["generic-charities", "saint-example"]
    assert sum(1 for f in grant if not f["repeat_of"]) == 1
    (cash,) = rows(db, "SELECT * FROM totals WHERE actor_slug = 'lantern-fund' AND kind = 'reported_grant' "
                       "AND side = 'subject' AND metric = 'cash_grant'")
    assert cash["amount"] == 450 + 600 + 70


def test_minutes_pages_fail_on_one_occurrence_claimed_by_two_reviewed_actors(tmp_path):
    reg = w.registry_with(**{"saint-example": {"patterns": [{"match": "HARBOR SHELTER", "reviewed": True}]}})
    (tmp_path / "r.yaml").write_text(yaml.safe_dump(reg))
    registry = ai.load_registry(tmp_path / "r.yaml")
    assert registry.mentions("Lantern Fund met; Harbor Annex too") == {"lantern-fund": "pattern_reviewed"}
    with pytest.raises(ai.RegistryError, match="harbor-shelter.*saint-example"):
        registry.mentions("The council thanked Harbor Shelter staff.")


def counsel_world(extra_plaintiff=None):
    """Union sues the county with counsel in case 1; the same counsel, without the union, sues the town in case 2."""
    roles = copy.deepcopy(w.ROLES)
    if extra_plaintiff:
        roles["cases"][0]["plaintiff_orgs"].append(extra_plaintiff)
    roles["cases"].append({"docket": "9:31-cv-00002", "court": "fdct", "courtlistener_id": 70000002,
                           "defendant_body": w.TOWN, "plaintiff_orgs": [], "plaintiff_counsel": ["quill-law"],
                           "outcome": {"kind": "dismissed", "date": "2032-01-01", "evidence": "entry 9"}})
    return roles


def test_counsel_carries_the_path_to_another_case_only_for_a_sole_plaintiff(tmp_path):
    db, _ = build(tmp_path, roles=counsel_world(), returns=litigation_world())
    actors = sorted(c["actors"] for c in money_and_case_paths(db))
    assert json.dumps([w.COUNTY, "lantern-fund", "tidepool-union", "quill-law", w.TOWN]) in actors
    (via,) = [c for c in money_and_case_paths(db) if w.TOWN in c["actors"]]
    assert "sole plaintiff" in json.loads(via["hops"])[2]["label"]
    db, _ = build(tmp_path, name="b.sqlite", roles=counsel_world("saint-example"), returns=litigation_world())
    assert all(w.TOWN not in c["actors"] for c in money_and_case_paths(db))


def test_a_return_file_present_in_two_roots_is_read_once_and_conflicting_copies_fail(tmp_path):
    inputs = w.make_world(tmp_path)
    other = tmp_path / "other-990"
    other.mkdir()
    name = "300000000000000003_public.xml"
    (other / name).write_bytes((inputs.returns[0] / name).read_bytes())
    both = ai.Inputs(**{**inputs.__dict__, "returns": (inputs.returns[0], other)})
    ai.build_index(both, tmp_path / "a.sqlite")
    assert len(facts(tmp_path / "a.sqlite", kind="own_return", actor_slug="harbor-shelter")) == 2
    (other / name).write_text((other / name).read_text().replace("5000", "5001"))
    with pytest.raises(ai.IndexBuildError, match="300000000000000003"):
        ai.build_index(both, tmp_path / "b.sqlite")
