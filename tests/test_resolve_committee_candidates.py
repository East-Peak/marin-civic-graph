import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from resolve_committee_candidates import (
    extract_candidate_name,
    slugify_name,
    find_person_match,
)


class TestExtractCandidateName:
    def test_standard_pattern(self):
        assert extract_candidate_name("Kate Colin for Mayor 2020") == "Kate Colin"

    def test_friends_of_pattern(self):
        assert extract_candidate_name("Friends of Heather McPhail Sridharan for Marin County Supervisor 2024") == "Heather McPhail Sridharan"

    def test_reelect_pattern(self):
        name = extract_candidate_name("Re-Elect Colbert for Supervisor 2028")
        assert name == "Colbert"

    def test_committee_to_elect(self):
        assert extract_candidate_name("Committee to Elect Anna Pletcher District Attorney 2018") == "Anna Pletcher"

    def test_committee_to_reelect(self):
        name = extract_candidate_name("Committee to Re-Elect Treanor for Trustee, Marin Community College District 2018")
        assert name == "Treanor"

    def test_last_name_only_for_pattern(self):
        assert extract_candidate_name("Rodoni for Supervisor 2020") == "Rodoni"

    def test_full_name_for_office(self):
        assert extract_candidate_name("Eric Lucan for Marin County Supervisor 2022") == "Eric Lucan"

    def test_pac_returns_none(self):
        assert extract_candidate_name("Marin Professional Firefighters Political Action Committee") is None

    def test_ballot_measure_returns_none(self):
        assert extract_candidate_name("Stay Green, Keep SMART 2020 - Yes on I") is None

    def test_multi_candidate_returns_none(self):
        assert extract_candidate_name("Aguila, Hawkins, LeBlanc, Nagle & Nagle for Central Committee 2024") is None

    def test_rachel_kertz(self):
        assert extract_candidate_name("Rachel Kertz for San Rafael City Council 2024") == "Rachel Kertz"

    def test_elect_prefix(self):
        assert extract_candidate_name("Elect Ana Doradea for Supervisor 2022") == "Ana Doradea"


class TestSlugifyName:
    def test_basic(self):
        assert slugify_name("Kate Colin") == "kate-colin"

    def test_middle_name(self):
        assert slugify_name("Heather McPhail Sridharan") == "heather-mcphail-sridharan"

    def test_single_name(self):
        assert slugify_name("Rodoni") == "rodoni"

    def test_lowercase(self):
        assert slugify_name("AL RODONI") == "al-rodoni"


class TestFindPersonMatch:
    def test_exact_match(self):
        persons = {"person-kate-colin": "Kate Colin", "person-eli-hill": "Eli Hill"}
        assert find_person_match("Kate Colin", persons) == "person-kate-colin"

    def test_slug_match(self):
        persons = {"person-kate-colin": "Kate Colin"}
        assert find_person_match("Kate Colin", persons) == "person-kate-colin"

    def test_last_name_match_single_result(self):
        persons = {"person-rodoni-al": "Al Rodoni", "person-kate-colin": "Kate Colin"}
        assert find_person_match("Rodoni", persons) == "person-rodoni-al"

    def test_no_match_returns_none(self):
        persons = {"person-kate-colin": "Kate Colin"}
        assert find_person_match("Nobody Here", persons) is None

    def test_ambiguous_last_name_returns_none(self):
        persons = {"person-smith-john": "John Smith", "person-smith-jane": "Jane Smith"}
        assert find_person_match("Smith", persons) is None

    def test_slug_last_first_ordering(self):
        # Campaign finance uses last-first slug convention
        persons = {"person-kertz-rachel": "Rachel Kertz"}
        assert find_person_match("Rachel Kertz", persons) == "person-kertz-rachel"

    def test_slug_first_last_ordering(self):
        # Migration seeds used first-last convention for some actors
        persons = {"person-kate-colin": "Kate Colin"}
        assert find_person_match("Kate Colin", persons) == "person-kate-colin"

    def test_case_insensitive_name_match(self):
        persons = {"person-colin-kate": "Kate Colin"}
        assert find_person_match("kate colin", persons) == "person-colin-kate"

    def test_finds_cf_prefixed_person(self):
        """Resolver must find campaign-finance-namespaced person IDs."""
        persons = {"person-cf-kertz-rachel": "Rachel Kertz"}
        assert find_person_match("Rachel Kertz", persons) == "person-cf-kertz-rachel"

    def test_finds_f700_prefixed_person(self):
        """Resolver must find Form 700-namespaced person IDs."""
        persons = {"person-f700-kate-colin": "Kate Colin"}
        assert find_person_match("Kate Colin", persons) == "person-f700-kate-colin"

    def test_prefers_canonical_over_prefixed(self):
        """Canonical person-{slug} should be preferred over namespaced variants."""
        persons = {
            "person-kate-colin": "Kate Colin",
            "person-cf-colin-kate": "Kate Colin",
        }
        assert find_person_match("Kate Colin", persons) == "person-kate-colin"
