"""Unit tests for search-property builders. We test pure functions here;
the Cypher side-effect runner is integration-tested manually against AuraDB."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_search_properties import (
    build_search_key_fact,
    build_search_label,
    build_search_last_activity,
    build_search_terms,
    compute_search_rank,
)


def test_person_label_uses_name():
    props = {"id": "person-kate-colin", "name": "Kate Colin", "aliases": []}
    assert build_search_label("Person", props) == "Kate Colin"


def test_meeting_label_combines_title_and_date():
    props = {
        "id": "meeting-san-rafael-2024-08-19",
        "title": "San Rafael City Council",
        "meeting_date": "2024-08-19",
    }
    assert (
        build_search_label("Meeting", props)
        == "San Rafael City Council — 2024-08-19"
    )


def test_filing_label_form_700():
    props = {
        "id": "filing-kate-colin-form-700-2024",
        "filing_type": "form_700",
        "signed_at": "2024-03-01",
        "filed_by_name": "Kate Colin",
    }
    assert (
        build_search_label("Filing", props)
        == "Form 700 · Kate Colin · 2024-03-01"
    )


def test_search_terms_lowercases_and_joins():
    props = {"id": "person-kate-colin", "name": "Kate Colin", "aliases": ["Mayor Colin"]}
    terms = build_search_terms("Person", props)
    assert "kate colin" in terms
    assert "mayor colin" in terms
    assert "person-kate-colin" in terms


def test_entity_search_rank_in_0_100():
    props = {"id": "person-kate-colin", "degree": 200}
    rank = compute_search_rank("Person", props)
    assert 0 <= rank <= 100


def test_record_search_rank_capped_at_30():
    props = {"id": "record-staff-report-1", "degree": 100}
    rank = compute_search_rank("Record", props)
    assert rank <= 30


# ---------- search_key_fact ----------


def test_key_fact_person_with_current_seat():
    props = {
        "id": "person-kate-colin",
        "name": "Kate Colin",
        "current_seat_display": "Mayor, San Rafael",
        "current_seat_start": "2024",
    }
    assert (
        build_search_key_fact("Person", props)
        == "Mayor, San Rafael · 2024–"
    )


def test_key_fact_person_seat_no_start_returns_seat():
    props = {"name": "Kate Colin", "current_seat_display": "Mayor, San Rafael"}
    assert build_search_key_fact("Person", props) == "Mayor, San Rafael"


def test_key_fact_person_no_seat_returns_none():
    props = {"name": "Kate Colin"}
    assert build_search_key_fact("Person", props) is None


def test_key_fact_decision_title_and_date():
    props = {"title": "Resolution 15336", "decided_at": "2024-08-19"}
    assert (
        build_search_key_fact("Decision", props)
        == "Resolution 15336 · 2024-08-19"
    )


def test_key_fact_project_name_and_status():
    props = {"name": "Transit Center Redesign", "status": "Active"}
    assert (
        build_search_key_fact("Project", props)
        == "Transit Center Redesign · Active"
    )


def test_key_fact_case_caption_and_filed_at():
    props = {"caption": "Smith v. Marin County", "filed_at": "2023-05-12"}
    assert (
        build_search_key_fact("Case", props)
        == "Smith v. Marin County · 2023-05-12"
    )


def test_key_fact_meeting_combines_title_date_institution():
    props = {
        "title": "San Rafael City Council",
        "meeting_date": "2024-08-19",
        "institution_name": "San Rafael City Council",
    }
    assert (
        build_search_key_fact("Meeting", props)
        == "San Rafael City Council · 2024-08-19 · San Rafael City Council"
    )


def test_key_fact_filing_type_filer_date():
    props = {
        "filing_type": "form_700",
        "signed_at": "2024-03-01",
        "filed_by_name": "Kate Colin",
    }
    assert (
        build_search_key_fact("Filing", props)
        == "Form 700 · Kate Colin · 2024-03-01"
    )


# ---------- search_last_activity ----------


def test_last_activity_picks_max_of_linked_dates():
    props = {
        "_linked_event_dates": ["2022-01-01", "2024-08-19", "2023-05-12"],
    }
    assert build_search_last_activity("Person", props) == "2024-08-19"


def test_last_activity_empty_list_falls_back_to_own_date():
    props = {"_linked_event_dates": [], "decided_at": "2024-08-19"}
    assert build_search_last_activity("Decision", props) == "2024-08-19"


def test_last_activity_no_dates_returns_none():
    props = {"_linked_event_dates": []}
    assert build_search_last_activity("Person", props) is None


# ---------- compute_search_rank recency component ----------


def test_rank_recency_boost_recent_beats_old():
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    old = "2015-01-01"
    recent_props = {"id": "a", "degree": 10, "_last_activity": today}
    old_props = {"id": "b", "degree": 10, "_last_activity": old}
    assert (
        compute_search_rank("Person", recent_props)
        > compute_search_rank("Person", old_props)
    )


def test_rank_ignores_unparseable_last_activity():
    # Shouldn't crash on bad dates.
    props = {"id": "x", "degree": 10, "_last_activity": "not-a-date"}
    rank = compute_search_rank("Person", props)
    assert 0 <= rank <= 100
