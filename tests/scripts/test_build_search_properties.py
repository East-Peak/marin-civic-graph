"""Unit tests for search-property builders. We test pure functions here;
the Cypher side-effect runner is integration-tested manually against AuraDB."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_search_properties import (
    build_search_label,
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
