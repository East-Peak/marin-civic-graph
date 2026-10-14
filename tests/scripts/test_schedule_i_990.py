"""Tests for scripts/schedule_i_990.py — Form 990 Schedule I Part II parser.

Fixtures are small fictional e-file documents built inline (IRS efile
namespace, ReturnHeader / ReturnData siblings IRS990 and IRS990ScheduleI).
Officer and Part III sentinels prove those sections never reach the output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import schedule_i_990 as s990  # noqa: E402
from campaign_ledger import UnsafeOutputError  # noqa: E402

EIN = "001234567"
OFFICER_SENTINEL = "Zelda Officersentinel"
PART_III_SENTINEL = "Part Three Sentinel Supplies"


def recipient(name, ein=None, address="us", cash=None, noncash=None, extra=""):
    if address == "us":
        addr = (
            "<USAddress><AddressLine1Txt>Sentinel Line One</AddressLine1Txt>"
            "<CityNm>Exampleton</CityNm><StateAbbreviationCd>CA</StateAbbreviationCd>"
            "<ZIPCd>949030000</ZIPCd></USAddress>"
        )
    elif address == "foreign":
        addr = "<ForeignAddress><CityNm>Sampleville</CityNm><CountryCd>MX</CountryCd></ForeignAddress>"
    else:
        addr = address
    parts = [
        f"<RecipientBusinessName><BusinessNameLine1Txt>{name}</BusinessNameLine1Txt></RecipientBusinessName>",
        addr,
        f"<RecipientEIN>{ein}</RecipientEIN>" if ein else "",
        "<IRCSectionDesc>501(c)(3)</IRCSectionDesc>",
        f"<CashGrantAmt>{cash}</CashGrantAmt>" if cash is not None else "",
        f"<NonCashAssistanceAmt>{noncash}</NonCashAssistanceAmt>" if noncash is not None else "",
        extra,
    ]
    return f"<RecipientTable>{''.join(parts)}</RecipientTable>"


PART_III = (
    f"<GrantsOtherAsstToIndivInUSGrp><GrantTypeTxt>{PART_III_SENTINEL}</GrantTypeTxt>"
    "<RecipientCnt>3</RecipientCnt><CashGrantAmt>500</CashGrantAmt></GrantsOtherAsstToIndivInUSGrp>"
)


def make_return(
    *, ein=EIN, rtype="990", version="2022v5.0", year="2022", ts="2023-05-01T10:00:00-07:00",
    amended=False, schedule=None, body="<CYTotalRevenueAmt>1000000.50</CYTotalRevenueAmt>"
    "<GovernmentGrantsAmt>250000</GovernmentGrantsAmt>", data_child="IRS990",
):
    sched = f'<IRS990ScheduleI documentId="x">{schedule}</IRS990ScheduleI>' if schedule is not None else ""
    ind = "<AmendedReturnInd>X</AmendedReturnInd>" if amended else ""
    officers = (
        "<Form990PartVIISectionAGrp><PersonNm>" + OFFICER_SENTINEL + "</PersonNm>"
        "<TitleTxt>Chair</TitleTxt><OfficerInd>X</OfficerInd></Form990PartVIISectionAGrp>"
    )
    return (
        f'<Return xmlns="http://www.irs.gov/efile" returnVersion="{version}">'
        f"<ReturnHeader><ReturnTs>{ts}</ReturnTs><TaxPeriodEndDt>{year}-12-31</TaxPeriodEndDt>"
        f"<ReturnTypeCd>{rtype}</ReturnTypeCd><TaxPeriodBeginDt>{year}-01-01</TaxPeriodBeginDt>"
        f"<Filer><EIN>{ein}</EIN><BusinessName><BusinessNameLine1Txt>Example Fund</BusinessNameLine1Txt>"
        f"</BusinessName></Filer><TaxYr>{year}</TaxYr></ReturnHeader>"
        f"<ReturnData><{data_child}>{ind}{body}{officers}</{data_child}>{sched}</ReturnData></Return>"
    ).encode()


def two_rows():
    return (
        recipient("Sample Housing Agency", ein="009876543", cash="120000.00",
                  extra="<PurposeOfGrantTxt>Housing support</PurposeOfGrantTxt>")
        + recipient("Example Pantry", cash="500", noncash="75",
                    extra="<NonCashAssistanceDesc>Food</NonCashAssistanceDesc>"
                          "<ValuationMethodUsedDesc>Cost</ValuationMethodUsedDesc>")
    )


# --- header ---------------------------------------------------------------

def test_header_fields_and_amounts():
    r = s990.parse_return(make_return(schedule=two_rows(), amended=True), object_id="111")
    assert r["status"] == "ok"
    assert (r["ein"], r["return_type"], r["return_version"], r["tax_year"]) == (EIN, "990", "2022v5.0", "2022")
    assert (r["tax_period_begin"], r["tax_period_end"]) == ("2022-01-01", "2022-12-31")
    assert r["return_ts"] == "2023-05-01T10:00:00-07:00"
    assert r["amended"] is True and r["object_id"] == "111"
    assert r["total_revenue"] == "1000000.50" and r["government_grants"] == "250000"


def test_total_revenue_prefers_part_viii_group_and_absent_is_none():
    body = "<TotalRevenueGrp><TotalRevenueColumnAmt>77</TotalRevenueColumnAmt></TotalRevenueGrp>"
    r = s990.parse_return(make_return(body=body))
    assert r["total_revenue"] == "77" and r["government_grants"] is None
    assert r["amended"] is False


def test_object_id_from_filename(tmp_path):
    p = tmp_path / "202300000000000001_public.xml"
    p.write_bytes(make_return())
    assert s990.parse_return(p)["object_id"] == "202300000000000001"


# --- Schedule I ------------------------------------------------------------

def test_part_ii_rows_cash_and_noncash_kept_apart():
    r = s990.parse_return(make_return(schedule=two_rows() + PART_III))
    si = r["schedule_i"]
    assert (si["present"], si["part_ii_present"], si["part_iii_present"]) == (True, True, True)
    ha, pantry = si["grants"]
    assert ha["recipient_name"] == "Sample Housing Agency" and ha["recipient_ein"] == "009876543"
    assert ha["cash_grant_amt"] == "120000.00" and ha["non_cash_assistance_amt"] is None
    assert ha["purpose"] == "Housing support" and ha["irc_section"] == "501(c)(3)"
    assert pantry["cash_grant_amt"] == "500" and pantry["non_cash_assistance_amt"] == "75"
    assert pantry["non_cash_description"] == "Food" and pantry["valuation_method"] == "Cost"
    assert ha["address"] == {"country": "US", "city": "Exampleton", "state": "CA", "zip5": "94903"}


def test_non_cash_only_row_has_no_cash():
    r = s990.parse_return(make_return(schedule=recipient("Example Pantry", noncash="40")))
    row = r["schedule_i"]["grants"][0]
    assert row["cash_grant_amt"] is None and row["non_cash_assistance_amt"] == "40"


def test_two_line_and_legacy_names():
    two = (
        "<RecipientTable><RecipientBusinessName><BusinessNameLine1Txt>Example Fund For</BusinessNameLine1Txt>"
        "<BusinessNameLine2Txt>Sampling</BusinessNameLine2Txt></RecipientBusinessName></RecipientTable>"
        "<RecipientTable><RecipientBusinessName><BusinessNameLine1>Legacy Org</BusinessNameLine1>"
        "</RecipientBusinessName></RecipientTable>"
    )
    rows = s990.parse_return(make_return(schedule=two))["schedule_i"]["grants"]
    assert [x["recipient_name"] for x in rows] == ["Example Fund For Sampling", "Legacy Org"]
    assert rows[0]["address"]["country"] is None


def test_absent_schedule_is_not_empty_list():
    si = s990.parse_return(make_return())["schedule_i"]
    assert si == {"present": False, "part_ii_present": False, "part_iii_present": False, "grants": None}


def test_part_iii_only_yields_no_grants():
    si = s990.parse_return(make_return(schedule=PART_III))["schedule_i"]
    assert (si["present"], si["part_ii_present"], si["part_iii_present"]) == (True, False, True)
    assert si["grants"] is None


def test_recipient_without_ein_and_foreign_address():
    rows = s990.parse_return(make_return(
        schedule=recipient("No Ein Org", cash="1") + recipient("Abroad Org", address="foreign", cash="2")
    ))["schedule_i"]["grants"]
    assert rows[0]["recipient_ein"] is None
    assert rows[1]["address"] == {"country": "MX", "city": "Sampleville", "state": None, "zip5": None}


def test_street_lines_never_emitted():
    r = s990.parse_return(make_return(schedule=two_rows()))
    assert "Sentinel Line One" not in json.dumps(r)


# --- status ----------------------------------------------------------------

@pytest.mark.parametrize("rtype,child", [("990PF", "IRS990PF"), ("990EZ", "IRS990EZ"), ("990T", "IRS990T")])
def test_other_form_types_are_not_form_990(rtype, child):
    r = s990.parse_return(make_return(rtype=rtype, data_child=child, schedule=two_rows()))
    assert r["status"] == "not_form_990" and r["return_type"] == rtype
    assert r["schedule_i"] is None


def test_unknown_version_is_unsupported_not_parsed():
    r = s990.parse_return(make_return(version="2099v9.9", schedule=two_rows()))
    assert r["status"] == "unsupported_version" and r["return_version"] == "2099v9.9"
    assert r["schedule_i"] is None


def test_supported_versions_cover_data_years():
    for v in sorted(s990.SUPPORTED_RETURN_VERSIONS):
        r = s990.parse_return(make_return(version=v, schedule=two_rows()))
        assert r["status"] == "ok" and len(r["schedule_i"]["grants"]) == 2
    assert "2019v5.0" not in s990.SUPPORTED_RETURN_VERSIONS


def test_2024v5_5_is_supported():
    # verified 2026-10-13: a real 2024v5.5 return's Schedule I uses exactly the element set of 2023v6.0
    r = s990.parse_return(make_return(version="2024v5.5", schedule=two_rows()))
    assert r["status"] == "ok" and len(r["schedule_i"]["grants"]) == 2


def test_prefixed_namespace_extracts_fields():
    xml = make_return(schedule=two_rows()).decode()
    xml = xml.replace(' xmlns="http://www.irs.gov/efile"', "")
    xml = xml.replace("<", "<irs:").replace("<irs:/", "</irs:").replace(
        "<irs:Return ", '<irs:Return xmlns:irs="http://www.irs.gov/efile" ')
    r = s990.parse_return(xml.encode())
    assert r["status"] == "ok" and r["ein"] == EIN and r["total_revenue"] == "1000000.50"
    assert r["schedule_i"]["grants"][0]["recipient_name"] == "Sample Housing Agency"


# --- privacy gate ----------------------------------------------------------

@pytest.mark.parametrize("leak", [OFFICER_SENTINEL, "OFFICERSENTINEL, Zelda"])
def test_person_text_withheld_from_free_text_fields(leak):
    rows = recipient(leak, cash="1", extra=f"<PurposeOfGrantTxt>Support from {leak} fund</PurposeOfGrantTxt>"
                     f"<NonCashAssistanceDesc>{leak}</NonCashAssistanceDesc>")
    rows += recipient("Clean Org", cash="2", extra="<PurposeOfGrantTxt>Housing</PurposeOfGrantTxt>")
    r = s990.parse_return(make_return(schedule=rows + PART_III))
    text = json.dumps(r)
    assert "entinel" not in text.replace("Sentinel Line One", "")
    first, clean = r["schedule_i"]["grants"]
    assert first["recipient_name"] == first["purpose"] == first["non_cash_description"] == s990.WITHHELD
    assert clean["purpose"] == "Housing" and r["withheld_fields"] == 3


# --- selection -------------------------------------------------------------

def parsed(object_id, year="2022", ts="2023-05-01T10:00:00-07:00", amended=False, ein=EIN, rtype="990", **kw):
    return s990.parse_return(make_return(year=year, ts=ts, amended=amended, ein=ein, rtype=rtype, **kw),
                             object_id=object_id)


def test_amendment_chosen_original_superseded():
    sel = s990.select_latest_per_year(
        [parsed("A", ts="2023-05-01T10:00:00-07:00"), parsed("B", ts="2023-09-01T10:00:00-07:00", amended=True)], EIN)
    (y,) = sel["years"]
    assert (y["tax_year"], y["object_id"], y["amended"], y["superseded"], y["ambiguous"]) == \
        ("2022", "B", True, ["A"], False)


def test_tie_and_missing_ts_flagged_ambiguous_but_deterministic():
    tie = s990.select_latest_per_year([parsed("A"), parsed("B")], EIN)["years"][0]
    assert tie["ambiguous"] is True and tie["object_id"] == "B" and tie["superseded"] == ["A"]
    missing = s990.select_latest_per_year([parsed("A", ts=""), parsed("B", ts="")], EIN)["years"][0]
    assert missing["ambiguous"] is True


def test_three_most_recent_years_and_considered_list():
    rows = [parsed(str(y), year=str(y)) for y in (2019, 2020, 2021, 2022)]
    sel = s990.select_latest_per_year(rows, EIN)
    assert [y["tax_year"] for y in sel["years"]] == ["2022", "2021", "2020"]
    assert len(sel["considered"]) == 4


def test_ineligible_returns_excluded():
    rows = [parsed("A"), parsed("OTHER", ein="009999999"), parsed("PF", rtype="990PF", data_child="IRS990PF"),
            parsed("V", version="2099v1.0")]
    sel = s990.select_latest_per_year(rows, EIN)
    assert [c["object_id"] for c in sel["considered"]] == ["A", "V"]


def test_unsupported_later_amendment_is_a_gap_not_substituted():
    sel = s990.select_latest_per_year([
        parsed("A", ts="2023-05-01T10:00:00-07:00"),
        parsed("B", ts="2023-09-01T10:00:00-07:00", amended=True, version="2099v1.0")], EIN)
    (y,) = sel["years"]
    assert (y["status"], y["object_id"], y["superseded"], y["return_version"]) == \
        ("unsupported_latest", "B", ["A"], "2099v1.0")
    assert {c["object_id"] for c in sel["considered"]} == {"A", "B"}


def test_newest_year_unsupported_is_reported_as_gap():
    sel = s990.select_latest_per_year([parsed("A", year="2021"), parsed("N", year="2022", version="2099v1.0")], EIN)
    assert [(y["tax_year"], y["status"]) for y in sel["years"]] == [("2022", "unsupported_latest"), ("2021", "ok")]


# --- geography and targets -------------------------------------------------

def addr(country="US", state="CA", zip5="94903"):
    return {"country": country, "city": "Exampleton", "state": state, "zip5": zip5}


def test_marin_rule():
    assert s990.MARIN_ZIP_LIST_VERSION == "usps-preferred-city-2026-10"
    assert isinstance(s990.MARIN_ZIP5, frozenset)
    for z in ("94901", "94998", "94966", "94979"):
        assert s990.marin_rule(addr(zip5=z)) == "in_rule"
    for z in ("94102", "94801", "94590"):
        assert s990.marin_rule(addr(zip5=z)) == "outside_rule"
    assert s990.marin_rule(addr()) == "in_rule"
    assert s990.marin_rule(addr(zip5="90001")) == "outside_rule"
    assert s990.marin_rule(addr(state="NV")) == "outside_rule"
    assert s990.marin_rule(addr(country="MX", state=None, zip5=None)) == "outside_rule"
    assert s990.marin_rule(addr(zip5=None)) == "unknown"
    assert s990.marin_rule(addr(state=None)) == "unknown"
    assert s990.marin_rule({"country": None, "city": None, "state": None, "zip5": None}) == "unknown"


def test_match_targets_independent_of_geography():
    targets = [{"label": "ha", "eins": ["009876543"], "names": ["Sample Housing Agency"]},
               {"label": "county", "eins": [], "names": ["County of Example"]}]
    far = addr(state="NV", zip5=None)
    assert s990.match_targets({"recipient_ein": "00-9876543", "recipient_name": "x", "address": far}, targets) == "ein_match:ha"
    assert s990.match_targets({"recipient_ein": None, "recipient_name": "COUNTY OF EXAMPLE, Inc.", "address": far}, targets) == "name_match:county"
    # a differing EIN is never rescued by an equal name
    assert s990.match_targets({"recipient_ein": "001111111", "recipient_name": "Sample Housing Agency",
                               "address": far}, targets) is None
    assert s990.match_targets({"recipient_ein": None, "recipient_name": "Other", "address": addr()}, targets) is None


# --- CLI -------------------------------------------------------------------

@pytest.fixture
def staging(tmp_path, monkeypatch):
    root = tmp_path / "staging"
    root.mkdir()
    monkeypatch.setattr(s990, "STAGING_ROOT", root)
    return root


def write_inputs(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    (d / "1_public.xml").write_bytes(make_return(schedule=two_rows() + PART_III))
    (d / "2_public.xml").write_bytes(make_return(year="2021", ts="2022-05-01T10:00:00-07:00"))
    return d


def test_cli_writes_selection_and_returns_without_restricted_text(tmp_path, staging):
    d = write_inputs(tmp_path)
    out = staging / "run1"
    assert s990.main(["--input", str(d), "--ein", EIN, "--out", str(out)]) == 0
    text = (out / "schedule-i.json").read_text()
    data = json.loads(text)
    assert [y["tax_year"] for y in data["selection"]["years"]] == ["2022", "2021"]
    assert len(data["returns"]) == 2
    assert OFFICER_SENTINEL not in text and PART_III_SENTINEL not in text
    assert "officers" not in data["returns"][0]


def test_cli_refuses_output_outside_staging(tmp_path, staging):
    d = write_inputs(tmp_path)
    with pytest.raises(UnsafeOutputError):
        s990.main(["--input", str(d), "--ein", EIN, "--out", str(tmp_path / "elsewhere")])
    assert not (tmp_path / "elsewhere").exists()


def test_cli_refuses_symlink_escape(tmp_path, staging):
    d = write_inputs(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (staging / "link").symlink_to(outside)
    with pytest.raises(UnsafeOutputError):
        s990.main(["--input", str(d), "--ein", EIN, "--out", str(staging / "link" / "x")])
    assert not any(outside.iterdir())


def test_cli_refuses_git_checkout_and_data_normalized(tmp_path, staging):
    d = write_inputs(tmp_path)
    (staging / ".git").mkdir()
    with pytest.raises(UnsafeOutputError):
        s990.main(["--input", str(d), "--ein", EIN, "--out", str(staging / "run")])
    root = Path(s990.__file__).resolve().parent.parent
    with pytest.raises(UnsafeOutputError):
        s990.resolve_safe_output(root / "data" / "normalized" / "x")


def test_part_iii_text_never_emitted_and_does_not_withhold_part_ii():
    purpose = f"Support for {PART_III_SENTINEL.split()[-1]} programs"
    rows = recipient("Clean Org", cash="2", extra=f"<PurposeOfGrantTxt>{purpose}</PurposeOfGrantTxt>")
    r = s990.parse_return(make_return(schedule=rows + PART_III))
    assert PART_III_SENTINEL not in json.dumps(r)
    assert r["schedule_i"]["grants"][0]["purpose"] == purpose and r["withheld_fields"] == 0


def test_person_name_in_address_city_is_withheld():
    row = recipient("Clean Org", cash="1").replace("<CityNm>Exampleton</CityNm>", f"<CityNm>{OFFICER_SENTINEL}</CityNm>")
    r = s990.parse_return(make_return(schedule=row))
    assert r["schedule_i"]["grants"][0]["address"]["city"] == s990.WITHHELD
    assert OFFICER_SENTINEL not in json.dumps(r) and r["withheld_fields"] == 1


# --- real-shape returns already committed for ingest_990 (tests/fixtures/990) -----------------------------------

FIXTURE_990 = Path(__file__).resolve().parents[1] / "fixtures" / "990"


@pytest.mark.parametrize("path", sorted(FIXTURE_990.glob("*.xml")), ids=lambda p: p.stem)
def test_each_committed_return_parses_under_its_own_schema_version(path):
    r = s990.parse_return(path)
    if r["return_type"] != "990":  # e.g. a 990-EZ: classified, never parsed as a Form 990
        assert r["status"] == "not_form_990" and r["schedule_i"] is None
        return
    assert r["return_version"] in s990.SUPPORTED_RETURN_VERSIONS
    assert r["status"] == "ok" and r["total_revenue"] is not None and r["tax_year"]
    if r["schedule_i"]["part_ii_present"]:
        g = r["schedule_i"]["grants"][0]
        assert g["recipient_name"] and (g["cash_grant_amt"] is not None or g["non_cash_assistance_amt"] is not None)
