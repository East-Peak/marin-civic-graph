"""The reported-contributor-detail policy: what an individual's Schedule A details may show publicly.

Every value here is fictional (EXAMPLE/SAMPLE streets, 555 phone numbers).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from contributor_detail import (  # noqa: E402
    FIELDS,
    PROPS,
    Outcome,
    classify,
    display,
    load_reviewed,
    review_key,
    transaction_details,
)


def _row(entity="IND", **reported):
    base = {"city": "San Anselmo", "state": "CA", "zip": "94960", "employer": "Example Co",
            "occupation": "Engineer"}
    return {"entity_cd": entity, "row_ref": {"file": "f", "sheet": "A-Contributions", "row": 2},
            "reported": {**base, **reported}}


class TestDisplay:
    def test_whitespace_is_the_only_normalization(self):
        assert display("  Example \t  Co ") == "Example Co"
        assert display("RETIRED") == "RETIRED"
        assert display("self-employed") == "self-employed"

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_blank_is_missing(self, raw):
        assert display(raw) is None


class TestZip:
    @pytest.mark.parametrize("raw, zip5", [("94901", "94901"), ("94901-1234", "94901"), (" 94960 ", "94960")])
    def test_five_digit_and_zip4_derive_zip5(self, raw, zip5):
        assert classify("zip5", raw) == Outcome(zip5, None)

    @pytest.mark.parametrize("raw", ["94901garbage", "9490", "949011", "UNKNOWN", "CA", "94901-12", "94901 1234",
                                     "94901-12345", "\uff19\uff14\uff19\uff10\uff11",
                                     "\u0669\u0664\u0669\u0660\u0661-1234"])
    def test_every_other_shape_is_withheld_not_guessed(self, raw):
        assert classify("zip5", raw) == Outcome(None, "malformed_zip")

    def test_a_valid_zip_is_never_mistaken_for_a_long_digit_run(self):
        assert classify("zip5", "94901-1234").value == "94901"


class TestLocality:
    def test_state_must_be_a_postal_code_and_shows_as_reported(self):
        assert classify("state", "CA") == Outcome("CA", None)
        assert classify("state", " ny ") == Outcome("ny", None)
        assert classify("state", "Calif") == Outcome(None, "malformed_state")
        assert classify("state", "ZZ") == Outcome(None, "malformed_state")

    def test_city_must_be_a_place_name(self):
        assert classify("city", "St. Helena") == Outcome("St. Helena", None)
        assert classify("city", "Mill  Valley") == Outcome("Mill Valley", None)
        assert classify("city", "Sampleton, CA 94999") == Outcome(None, "street")
        assert classify("city", "Sampleton 3") == Outcome(None, "malformed_city")

    @pytest.mark.parametrize("raw", ["San José", "Coeur d’Example", "Sample-by-the-Sea"])
    def test_city_names_keep_their_spelling(self, raw):
        assert classify("city", raw) == Outcome(raw, None)

    @pytest.mark.parametrize("raw", ["Sampleton (wife of Pat Example)", "Sampleton c/o Pat", "Exampleville.com"])
    def test_suspected_personal_information_is_screened_in_the_city_too(self, raw):
        assert classify("city", raw) == Outcome(None, "suspected_pii_unreviewed")

    def test_non_text_cells_are_withheld_not_missing(self):
        assert classify("zip5", 94901) == Outcome(None, "non_text_cell")
        assert classify("employer", 12) == Outcome(None, "non_text_cell")


class TestContactAndAddressShapes:
    @pytest.mark.parametrize("field, raw, rule", [
        ("employer", "415-555-0199", "phone"),
        ("employer", "4155550199", "phone"),
        ("occupation", "Retired (415) 555-0199", "phone"),
        ("employer", "call 555-0199", "phone"),
        ("employer", "Call 555.0199", "phone"),
        ("employer", "Call 555 0199", "phone"),
        ("employer", "Consultant, 12 Sample-Example Road", "street"),
        ("occupation", "Retired; 8 Example Crescent", "street"),
        ("employer", "pat@example.com", "email"),
        ("employer", "https://example.org/about", "url"),
        ("employer", "www.example.org", "url"),
        ("employer", "12 Sample Ln, apt 4Sampleton, CA 94999", "street"),
        ("employer", "Example University 500 Example St   Sampleton, CA 94999", "street"),
        ("employer", "7 Example CircleSampleton, CA 94999", "street"),
        ("employer", "PO Box 12", "street"),
        ("occupation", "Consultant, Suite 200", "street"),
        ("occupation", "Homemaker at 40 Sample Road", "street"),
    ])
    def test_contact_or_address_shaped_values_are_withheld(self, field, raw, rule):
        assert classify(field, raw) == Outcome(None, rule)


class TestSuspectedPersonalInformation:
    @pytest.mark.parametrize("field, raw", [
        ("occupation", "Homemaker, spouse of Pat Example"),
        ("occupation", "Retired c/o my daughter"),
        ("occupation", "Retired, DOB 01/02/1950"),
        ("occupation", "Retired 123-45-6789"),
        ("employer", "Exampleco.com"),
        ("employer", "12 Example"),
        ("employer", "Account 1234567"),
        ("employer", "Consultant, 12 Sample Ridge"),
        ("employer", "Example Co #12"),
        ("occupation", "Unit 3 Supervisor"),
    ])
    def test_suspected_values_are_flagged_and_withheld_until_reviewed(self, field, raw):
        assert classify(field, raw) == Outcome(None, "suspected_pii_unreviewed")

    def test_a_reviewed_value_publishes_as_reported(self):
        reviewed = frozenset({review_key("employer", "Exampleco.com")})
        assert classify("employer", "  Exampleco.com ", reviewed) == Outcome("Exampleco.com", None)
        assert classify("occupation", "Exampleco.com", reviewed).rule == "suspected_pii_unreviewed"

    def test_review_decisions_hold_hashes_never_text(self, tmp_path):
        path = tmp_path / "reviewed.json"
        path.write_text('{"reviewed": [{"field": "employer", "sha256": "%s", "decision": "publish"}]}'
                        % review_key("employer", "Exampleco.com")[1])
        assert load_reviewed(path) == frozenset({review_key("employer", "Exampleco.com")})
        assert "Exampleco" not in path.read_text()

    def test_review_decisions_must_be_publish_decisions_on_known_fields(self, tmp_path):
        path = tmp_path / "reviewed.json"
        path.write_text('{"reviewed": [{"field": "street", "sha256": "ab", "decision": "publish"}]}')
        with pytest.raises(ValueError):
            load_reviewed(path)

    def test_the_repo_review_file_loads(self):
        assert isinstance(load_reviewed(), frozenset)


class TestOrdinaryValuesPublish:
    @pytest.mark.parametrize("field, raw", [
        ("employer", "SELF-EMPLOYED"), ("employer", "RETIRED"), ("employer", "N/A"), ("employer", "NONE"),
        ("employer", "Golden 1 Example Union"), ("employer", "Example 360"), ("employer", "Pac-12 Example"),
        ("employer", "The 8th Example"), ("employer", "20th Century Example"), ("employer", "Example No.3 LLC"),
        ("occupation", "Supervisor (District 3)"), ("occupation", "Attorney/Planning Commissioner"),
        ("employer", "Example Local 3"), ("occupation", "Teacher, grades 3-5"), ("employer", "Class of 2019"),
        ("employer", "Example 2020 2021 Campaign"),
        # A home business reads like any business: it publishes as reported (the residual risk is documented).
        ("employer", "Sample Family Pottery Studio"),
        ("employer", "Self employed, Pat & Sam Example Window Cleaning"),
    ])
    def test_permitted_values_publish_unchanged(self, field, raw):
        assert classify(field, raw) == Outcome(raw, None)


class TestNonTextCells:
    def test_a_date_cell_is_kept_losslessly_and_withheld(self):
        from datetime import datetime
        from campaign_ledger import cell
        kept = cell(datetime(1950, 1, 2))
        assert kept == {"cell_type": "datetime", "value": "1950-01-02T00:00:00"}
        assert classify("occupation", kept) == Outcome(None, "non_text_cell")
        _, details = transaction_details("A", [_row(occupation=kept), _row(occupation=kept)])
        assert details["occupation"] == Outcome(None, "non_text_cell")

    def test_json_native_cells_are_kept_as_they_are(self):
        from campaign_ledger import cell
        assert [cell(v) for v in (None, "  x ", 94901, 1.5, True)] == [None, "  x ", 94901, 1.5, True]


class TestTransactionDetails:
    def test_an_individuals_details_become_as_reported_props(self):
        eligible, details = transaction_details("A", [_row(zip="94960-0001")])
        assert eligible is None
        assert {PROPS[f]: o.value for f, o in details.items()} == {
            "reported_occupation": "Engineer", "reported_employer": "Example Co",
            "reported_city": "San Anselmo", "reported_state": "CA", "reported_zip5": "94960"}

    def test_self_employed_with_a_sparse_locality_still_publishes(self):
        _, details = transaction_details("A", [_row(employer="SELF-EMPLOYED", city="Sampleton", zip="94999")])
        assert details["employer"].value == "SELF-EMPLOYED"
        assert details["city"].value == "Sampleton"
        assert details["zip5"].value == "94999"

    @pytest.mark.parametrize("schedule, codes, reason", [
        ("E", ["IND"], "not_schedule_a"),
        ("A", ["COM"], "entity_code_not_ind"),
        ("A", ["OTH"], "entity_code_not_ind"),
        ("A", [None], "entity_code_missing_or_conflicting"),
        ("A", ["IND", None], "entity_code_missing_or_conflicting"),
        ("A", ["IND", "COM"], "entity_code_missing_or_conflicting"),
    ])
    def test_only_explicit_ind_on_every_reporting_row_is_eligible(self, schedule, codes, reason):
        eligible, details = transaction_details(schedule, [_row(entity=c) for c in codes])
        assert eligible == reason
        assert details == {}

    def test_identical_duplicate_reports_share_details(self):
        _, details = transaction_details("A", [_row(), _row(employer="  Example   Co ")])
        assert details["employer"] == Outcome("Example Co", None)

    def test_conflicts_are_detected_before_zip_reduction_or_redaction(self):
        _, details = transaction_details("A", [_row(zip="94960-0001", employer="415-555-0199"),
                                               _row(zip="94960-0002", employer="415-555-0100")])
        assert details["zip5"] == Outcome(None, "conflicting_reports")
        assert details["employer"] == Outcome(None, "conflicting_reports")
        assert details["city"] == Outcome("San Anselmo", None)

    def test_one_report_missing_a_field_is_a_conflict_not_a_merge(self):
        _, details = transaction_details("A", [_row(occupation=None), _row()])
        assert details["occupation"] == Outcome(None, "conflicting_reports")

    def test_every_field_has_one_outcome(self):
        _, details = transaction_details("A", [_row()])
        assert set(details) == set(FIELDS)
