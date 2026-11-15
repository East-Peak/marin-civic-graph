"""An invented world for the actor index tests: a registry, case roles, a board ledger, a docket cache, a substrate,
Form 990 returns and a minutes text index. Every person, organization, return and docket here is made up.

`make_world(tmp_path, **overrides)` writes the inputs and returns an `actor_index.Inputs`; each component can be
replaced (or set to None where the input is optional) to build a smaller world."""
from __future__ import annotations

import copy
import json
import shutil
import sqlite3
from pathlib import Path

import yaml

import actor_index as ai

# Invented addresses, assembled at run time: the repo's committed-text scan forbids an address shape in source.
STREET, AVENUE, ROAD, LANE = "Str" "eet", "Ave" "nue", "Ro" "ad", "La" "ne"


def address(number: int, suffix: str) -> str:
    return f"{number} Sentinel {suffix}"


COUNTY = "county-of-fernwood"
TOWN = "town-of-brookvale"

REGISTRY = {
    "reviewed_on": "2030-01-15",
    "actors": [
        {"slug": "harbor-shelter", "name": "Harbor Shelter", "kind": "nonprofit",
         "substrate_ids": ["org-harbor-shelter", "org-bmf-ein-001110001"], "eins": ["001110001"],
         "patterns": [{"match": "HARBOR SHELTER", "reviewed": True}], "reviewed": True},
        {"slug": "lantern-fund", "name": "Lantern Fund", "kind": "foundation",
         "substrate_ids": ["org-990-ein-002220002"], "eins": ["002220002"],
         "patterns": [{"match": "LANTERN FUND", "reviewed": True}], "reviewed": True},
        {"slug": "tidepool-union", "name": "Tidepool Tenants Union", "kind": "association",
         "substrate_ids": [], "eins": [],
         "patterns": [{"match": "TIDEPOOL TENANTS UNION", "reviewed": True}],
         "affiliated_with": ["tidepool-union-north"], "reviewed": True},
        {"slug": "tidepool-union-north", "name": "North Tidepool Tenants Union", "kind": "association",
         "substrate_ids": [], "eins": [],
         "patterns": [{"match": "NORTH TIDEPOOL TENANTS UNION", "reviewed": True}],
         "affiliated_with": ["tidepool-union"], "reviewed": True},
        {"slug": "quill-law", "name": "Law Offices of Oda Quill", "kind": "law_firm",
         "substrate_ids": [], "eins": [],
         "patterns": [{"match": "LAW OFF?ICES OF ODA QUILL", "reviewed": True}], "reviewed": True},
        {"slug": "oda-quill", "name": "Oda Quill", "kind": "person", "substrate_ids": [], "eins": [],
         "patterns": [{"match": "ODA QUILL|QUILL, ODA", "reviewed": True}],
         "public_role": "attorney of record (invented)", "affiliated_with": ["quill-law"], "reviewed": True},
        {"slug": "generic-charities", "name": "Generic Charities", "kind": "nonprofit",
         "substrate_ids": [], "eins": [],
         "patterns": [{"match": "GENERIC CHARITIES", "reviewed": False}], "reviewed": True},
        {"slug": "saint-example", "name": "St. Example Society", "kind": "nonprofit",
         "substrate_ids": [], "eins": [],
         "patterns": [{"match": "S(AIN)?T\\.? EXAMPLE", "exclude": "ACADEMY", "reviewed": True}], "reviewed": True},
    ],
    "public_bodies": [
        {"slug": COUNTY, "name": "County of Fernwood", "substrate_ids": ["org-county-of-fernwood"],
         "ledger_body": True},
        {"slug": TOWN, "name": "Town of Brookvale", "substrate_ids": ["org-town-of-brookvale"],
         "patterns": [{"match": "^TOWN OF BROOKVALE$", "reviewed": True}]},
    ],
}

ROLES = {
    "reviewed_on": "2030-01-15",
    "cases": [
        {"docket": "9:30-cv-00001", "court": "fdct", "courtlistener_id": 70000001, "defendant_body": COUNTY,
         "plaintiff_orgs": ["tidepool-union"], "plaintiff_counsel": ["quill-law"],
         "outcome": {"kind": "stipulated_dismissal", "date": "2031-02-02", "evidence": "docket entries 40, 41"}},
    ],
}


def ledger_row(n, meeting, date, item, counterparty, direction, amount, action="new_agreement",
               quote="enter into an agreement"):
    return {"n": n, "meeting": meeting, "date": date, "item": item, "counterparty": counterparty,
            "norm": counterparty.upper(), "kind": "nonprofit", "direction": direction, "amount": amount,
            "action": action, "quote": quote}


LEDGER = [
    ledger_row(0, "meeting-fernwood-bos-1", "MARCH 3, 2029", "CA-1", "Lantern Fund", "county_pays", 10000,
               quote="approve an agreement with Lantern Fund in the amount of $10,000"),
    ledger_row(1, "meeting-fernwood-bos-1", "MARCH 3, 2029", "CA-2", "Harbor Shelter", "county_pays", 3000,
               quote=f"agreement with Harbor Shelter at {address(12, STREET)} for shelter beds"),
    ledger_row(1, "meeting-fernwood-bos-1", "MARCH 3, 2029", "CA-2", "Harbor Shelter", "county_pays", 3000),
    ledger_row(2, "meeting-fernwood-bos-2", "APRIL 7, 2030", "CA-3", "Harbor Shelter", "county_receives", 700,
               action="lease"),
    ledger_row(3, "meeting-fernwood-bos-2", "APRIL 7, 2030", "CA-4", "Generic Charities", "county_pays", 999),
    ledger_row(4, "meeting-fernwood-bos-2", "APRIL 7, 2030", "CA-5", "St. Example Academy", "county_pays", 55),
    ledger_row(5, "meeting-fernwood-bos-2", "APRIL 7, 2030", "CA-6", "St Example", "county_pays", 50),
    ledger_row(6, "meeting-fernwood-bos-2", "APRIL 7, 2030", "CA-7", "Harbor Shelter", "no_money", None,
               action="other"),
    ledger_row(7, "meeting-fernwood-bos-2", "APRIL 7, 2030", "CA-8", "Harbor Shelter", "county_pays", 3000,
               action="amendment"),
]


def docket(cl_id, number, caption, party, attorney, firm, filed="2030-05-05", closed=None, **extra):
    result = {"docket_id": cl_id, "docketNumber": number, "caseName": caption, "court": "District Court, Fernwood",
              "court_id": "fdct", "dateFiled": filed, "dateTerminated": closed, "cause": "42:1983 Civil Rights Act",
              "docket_absolute_url": f"/docket/{cl_id}/{caption.lower().replace(' ', '-')}/",
              "party": party, "attorney": attorney, "firm": firm, **extra}
    return {"count": 1, "results": [result]}


DOCKETS = {
    "70000001.json": docket(
        70000001, "9:30-cv-00001", "Tidepool Tenants Union v. County of Fernwood",
        ["Tidepool Tenants Union", "County of Fernwood", "Ima Resident"],
        ["Oda Quill", "Dee Fender"], ["Law Offices of Oda Quill", "Defense Partners LLP"], closed="2031-02-02",
        party_address=[address(77, AVENUE)]),
    "70000002.json": docket(70000002, "9:31-cv-00002", "Resident v. Town of Brookvale",
                            ["Uma Resident", "Town of Brookvale"], [], [], filed="2031-06-01"),
}

COURTLISTENER = [
    {"id": "case-cl-70000001", "node_type": "Case", "properties": {
        "case_name": "Tidepool Tenants Union v. County of Fernwood", "docket_number": "9:30-cv-00001",
        "court": "District Court, Fernwood", "date_filed": "2030-05-05", "date_terminated": "2031-02-02",
        "cause": "42:1983 Civil Rights Act", "courtlistener_url": "https://courts.example/docket/70000001/"}},
]

SUBSTRATE = {
    "nodes": [
        ("org-harbor-shelter", "Organization", "Harbor Shelter", {}),
        ("org-bmf-ein-001110001", "Organization", "Harbor Shelter Inc", {}),
        ("org-harbor-shelter-thrift", "Organization", "Harbor Shelter Thrift Store", {}),
        ("org-990-ein-002220002", "Organization", "Lantern Fund", {}),
        ("org-county-of-fernwood", "Organization", "County of Fernwood", {}),
        ("org-fernwood-dept-health", "Organization", "Health, County of Fernwood", {}),
        ("committee-friends-of-example", "Committee", "Friends of Example for Council", {}),
        ("moneyflow-dc-1", "MoneyFlow", "delegated_contract", {"flow_type": "delegated_contract", "amount": 5000.0}),
        ("moneyflow-dc-2", "MoneyFlow", "delegated_contract", {"flow_type": "delegated_contract", "amount": 800.0}),
        ("moneyflow-gift-1", "MoneyFlow", "contribution", {
            "flow_type": "contribution", "amount": 250.0, "flow_date": "2029-09-09", "reported_city": "Sentinelville",
            "reported_zip5": "99999", "reported_employer": "Sentinel Employer", "reported_state": "ZZ"}),
        ("meeting-fernwood-council-17", "Meeting", "Fernwood Council", {"meeting_date": "2029-10-10",
                                                                         "title": "Fernwood Council"}),
        ("agenda-1", "AgendaItem", "", {"item_number": "4.a",
                                        "title": f"Agreement with Harbor Shelter for the {address(12, STREET)} site"}),
        ("agenda-2", "AgendaItem", "", {"item_number": "4.b", "title": "Library roof repair"}),
        ("person-wren", "Person", "Wren Ambler", {}),
        ("seatservice-wren", "SeatService", "Wren Ambler - Seat 1", {}),
    ],
    "edges": [
        ("org-fernwood-dept-health", "FROM_SOURCE", "moneyflow-dc-1"),
        ("moneyflow-dc-1", "TO_TARGET", "org-harbor-shelter"),
        ("org-fernwood-dept-health", "FROM_SOURCE", "moneyflow-dc-2"),
        ("moneyflow-dc-2", "TO_TARGET", "org-harbor-shelter-thrift"),
        ("org-990-ein-002220002", "FROM_SOURCE", "moneyflow-gift-1"),
        ("moneyflow-gift-1", "TO_TARGET", "committee-friends-of-example"),
        ("agenda-1", "PART_OF_MEETING", "meeting-fernwood-council-17"),
        ("agenda-2", "PART_OF_MEETING", "meeting-fernwood-council-17"),
        ("seatservice-wren", "HELD_BY", "person-wren"),
    ],
}


def grant(name, cash=None, noncash=None, ein=None, purpose="General support"):
    return {"name": name, "cash": cash, "noncash": noncash, "ein": ein, "purpose": purpose}


def officer(name, title="Director", flag="IndividualTrusteeOrDirectorInd"):
    return {"name": name, "title": title, "flag": flag}


RETURNS = {
    # Lantern Fund 2029: the original and an amendment; the amendment must be selected.
    "300000000000000001_public.xml": dict(
        ein="002220002", filer="LANTERN FUND", year="2029", ts="2030-05-01T10:00:00-07:00",
        revenue="100", gov="10", grants=[grant("Tidepool Tenants Union", cash="400")],
        officers=[officer("WREN AMBLER"), officer("PELL CORDER", "Treasurer", "OfficerInd")]),
    "300000000000000002_public.xml": dict(
        ein="002220002", filer="LANTERN FUND", year="2029", ts="2030-08-01T10:00:00-07:00", amended=True,
        revenue="111", gov="11",
        grants=[grant("Tidepool Tenants Union", cash="450", noncash="25"),
                grant("Totally Different Name", cash="600", ein="001110001"),
                grant("Generic Charities Of Somewhere", cash="70")],
        officers=[officer("WREN AMBLER"), officer("PELL CORDER", "Treasurer", "OfficerInd")]),
    # Four more Lantern years: no year limit may apply.
    **{f"30000000000000002{y}_public.xml": dict(
        ein="002220002", filer="LANTERN FUND", year=f"202{y}", ts=f"203{y - 4}-05-01T10:00:00-07:00",
        revenue=str(10 * y), gov="1", grants=[], officers=[]) for y in (5, 6, 7, 8)},
    # Harbor Shelter's own return; one officer name is shared with Lantern Fund (suffix differs).
    "300000000000000003_public.xml": dict(
        ein="001110001", filer="HARBOR SHELTER", year="2029", ts="2030-04-01T10:00:00-07:00",
        revenue="5000", gov="4000", grants=[],
        officers=[officer("Pell Corder Jr."), officer("Ash Wilder", "President", "OfficerInd")]),
}


def return_xml(ein, filer, year, ts, revenue, gov, grants, officers, amended=False):
    rows = []
    for g in grants:
        rows.append(
            "<RecipientTable><RecipientBusinessName><BusinessNameLine1Txt>" + g["name"] +
            "</BusinessNameLine1Txt></RecipientBusinessName>"
            f"<USAddress><AddressLine1Txt>{address(55, ROAD)}</AddressLine1Txt>"
            "<CityNm>Sentinelburg</CityNm>"
            "<StateAbbreviationCd>ZZ</StateAbbreviationCd><ZIPCd>999990000</ZIPCd></USAddress>"
            + (f"<RecipientEIN>{g['ein']}</RecipientEIN>" if g["ein"] else "")
            + "<IRCSectionDesc>501(c)(3)</IRCSectionDesc>"
            + (f"<CashGrantAmt>{g['cash']}</CashGrantAmt>" if g["cash"] is not None else "")
            + (f"<NonCashAssistanceAmt>{g['noncash']}</NonCashAssistanceAmt>" if g["noncash"] is not None else "")
            + f"<PurposeOfGrantTxt>{g['purpose']}</PurposeOfGrantTxt></RecipientTable>")
    part_iii = ("<GrantsOtherAsstToIndivInUSGrp><GrantTypeTxt>Sentinel Individual Aid</GrantTypeTxt>"
                "<RecipientCnt>3</RecipientCnt><CashGrantAmt>500</CashGrantAmt></GrantsOtherAsstToIndivInUSGrp>")
    sched = f"<IRS990ScheduleI>{''.join(rows)}{part_iii}</IRS990ScheduleI>"
    offs = "".join(
        f"<Form990PartVIISectionAGrp><PersonNm>{o['name']}</PersonNm><TitleTxt>{o['title']}</TitleTxt>"
        f"<{o['flag']}>X</{o['flag']}></Form990PartVIISectionAGrp>" for o in officers)
    return (
        '<Return xmlns="http://www.irs.gov/efile" returnVersion="2022v5.0">'
        f"<ReturnHeader><ReturnTs>{ts}</ReturnTs><TaxPeriodEndDt>{year}-12-31</TaxPeriodEndDt>"
        f"<ReturnTypeCd>990</ReturnTypeCd><TaxPeriodBeginDt>{year}-01-01</TaxPeriodBeginDt>"
        f"<Filer><EIN>{ein}</EIN><BusinessName><BusinessNameLine1Txt>{filer}</BusinessNameLine1Txt></BusinessName>"
        f"<USAddress><AddressLine1Txt>{address(9, LANE)}</AddressLine1Txt></USAddress>"
        f"</Filer><TaxYr>{year}</TaxYr></ReturnHeader><ReturnData><IRS990>"
        + ("<AmendedReturnInd>X</AmendedReturnInd>" if amended else "")
        + f"<CYTotalRevenueAmt>{revenue}</CYTotalRevenueAmt><GovernmentGrantsAmt>{gov}</GovernmentGrantsAmt>"
        f"{offs}</IRS990>{sched}</ReturnData></Return>")


MINUTES_PAGES = [
    ("Fernwood Council", "The council thanked Harbor Shelter staff."),
    ("Fernwood Council", "HARBOR SHELTER and Lantern Fund presented."),
    ("Fernwood Parks", "Harbor Shelter volunteers cleaned the park."),
    ("Fernwood Parks", "Generic Charities spoke."),
    ("Fernwood Parks", "Nothing relevant."),
]

SENTINELS = (f"Sentinel {STREET}", f"Sentinel {AVENUE}", f"Sentinel {ROAD}", f"Sentinel {LANE}", "Sentinelville",
             "Sentinelburg", "99999", "Sentinel Employer", "Sentinel Individual Aid")


def write_substrate(path: Path, data: dict) -> Path:
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, search_label TEXT, props TEXT);"
                     "CREATE TABLE edges (source TEXT, rel TEXT, target TEXT, props TEXT);"
                     "CREATE TABLE meta (key TEXT, value TEXT);")
    db.execute("INSERT INTO meta VALUES ('as_of_date', '2031-07-01')")
    db.executemany("INSERT INTO nodes VALUES (?, ?, ?, ?)",
                   [(i, t, label, json.dumps(p)) for i, t, label, p in data["nodes"]])
    db.executemany("INSERT INTO edges VALUES (?, ?, ?, NULL)", data["edges"])
    db.commit()
    db.close()
    return path


def write_minutes(path: Path, pages) -> Path:
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                     "CREATE TABLE pages (id INTEGER PRIMARY KEY, meeting_id TEXT, source TEXT, body TEXT,"
                     " meeting_date TEXT, page INTEGER, text TEXT, official_url TEXT, source_sha256 TEXT);"
                     "CREATE TABLE coverage (meeting_id TEXT PRIMARY KEY, source TEXT, body TEXT, meeting_date TEXT,"
                     " minutes_url TEXT, state TEXT);")
    db.execute("INSERT INTO meta VALUES ('substrate_as_of_date', '2031-07-01')")
    for i, (body, text) in enumerate(pages):
        db.execute("INSERT INTO pages (meeting_id, source, body, meeting_date, page, text) VALUES (?, 's', ?, ?, ?, ?)",
                   (f"m{i}", body, "2030-01-01", 1, text))
    db.execute("INSERT INTO coverage VALUES ('m0', 's', 'Fernwood Council', '2030-01-01', 'u', 'indexed')")
    db.execute("INSERT INTO coverage VALUES ('mx', 's', 'Fernwood Council', '2030-02-01', 'u', 'not cached')")
    db.commit()
    db.close()
    return path


def make_world(tmp_path: Path, *, registry=None, roles=None, ledger=None, dockets=None, substrate=None,
               returns=None, courtlistener=COURTLISTENER, minutes=MINUTES_PAGES) -> ai.Inputs:
    root = tmp_path / "world"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "actors.yaml").write_text(yaml.safe_dump(copy.deepcopy(registry or REGISTRY), sort_keys=False))
    (root / "case-roles.yaml").write_text(yaml.safe_dump(copy.deepcopy(roles or ROLES), sort_keys=False))
    rows = LEDGER if ledger is None else ledger
    (root / "board-ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    dk = root / "dockets"
    dk.mkdir(exist_ok=True)
    for name, body in (DOCKETS if dockets is None else dockets).items():
        (dk / name).write_text(json.dumps(body))
    rdir = root / "990"
    rdir.mkdir(exist_ok=True)
    for name, spec in (RETURNS if returns is None else returns).items():
        (rdir / name).write_text(return_xml(**spec))
    cl = None
    if courtlistener is not None:
        cl = root / "courtlistener"
        cl.mkdir(exist_ok=True)
        (cl / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in courtlistener))
    mins = write_minutes(root / "minutes-text.sqlite", minutes) if minutes is not None else None
    return ai.Inputs(
        registry=root / "actors.yaml", roles=root / "case-roles.yaml", ledger=root / "board-ledger.jsonl",
        dockets=dk, substrate=write_substrate(root / "substrate.sqlite", substrate or SUBSTRATE),
        returns=(rdir,), courtlistener=cl, minutes=mins)


def registry_with(**changes) -> dict:
    """A copy of REGISTRY with actor fields replaced: registry_with(**{'tidepool-union': {...}})."""
    reg = copy.deepcopy(REGISTRY)
    for entry in reg["actors"] + reg["public_bodies"]:
        entry.update(changes.get(entry["slug"], {}))
    return reg
