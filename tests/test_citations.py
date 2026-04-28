import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from citations import has_primary_source_citation


class TestEvidenceArrays:
    def test_evidence_record_ids_non_empty(self):
        assert has_primary_source_citation({"evidence_record_ids": ["rec-1"]})

    def test_evidence_record_ids_empty_array(self):
        assert not has_primary_source_citation({"evidence_record_ids": []})

    def test_record_ids_alternative(self):
        assert has_primary_source_citation({"record_ids": ["rec-2"]})


class TestSingleFieldCitations:
    def test_filing_id(self):
        assert has_primary_source_citation({"filing_id": "F-123"})

    def test_fppc_report_id(self):
        assert has_primary_source_citation({"fppc_report_id": "fppc-2024"})

    def test_minutes_url(self):
        assert has_primary_source_citation({"minutes_url": "https://..."})

    def test_docket_number(self):
        assert has_primary_source_citation({"docket_number": "CV-1"})

    def test_permit_id(self):
        assert has_primary_source_citation({"permit_id": "P-1"})

    def test_source_url_plus_source_id(self):
        assert has_primary_source_citation({"source_url": "u", "source_id": "s"})

    def test_source_url_alone_insufficient(self):
        # Spec requires source_url AND source_id together for Records.
        assert not has_primary_source_citation({"source_url": "u"})

    def test_moneyflow_source_filing_id(self):
        assert has_primary_source_citation({"source_filing_id": "fppc-sched-A"})

    def test_committee_fppc_id(self):
        assert has_primary_source_citation({"fppc_id": "1234567"})


class TestNoCitation:
    def test_empty_node(self):
        assert not has_primary_source_citation({})

    def test_only_irrelevant_fields(self):
        assert not has_primary_source_citation(
            {"name": "x", "label": "y", "id": "z"}
        )

    def test_blank_string_not_a_citation(self):
        assert not has_primary_source_citation({"filing_id": ""})
        assert not has_primary_source_citation({"minutes_url": "   "})
