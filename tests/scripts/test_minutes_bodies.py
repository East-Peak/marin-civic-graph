"""Minutes text: the real governing body of a Meeting, from its listing title."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from minutes_bodies import SOURCES, normalize_body, source_of  # noqa: E402


@pytest.mark.parametrize("meeting_id,source", [
    ("meeting-corte-madera-town-council-1005", "corte-madera-town-council"),
    ("meeting-novato-city-council-1422", "novato-city-council"),
    ("meeting-marin-county-bos-10009", "marin-county-bos"),
    ("meeting-sausalito-city-council-1064", "sausalito-city-council"),
    ("meeting-san-anselmo-town-council-2739", "san-anselmo-town-council"),
    ("meeting-san-rafael-city-council-1", None),
    ("record-novato-city-council-1", None),
])
def test_source_of_a_meeting_id(meeting_id, source):
    assert source_of(meeting_id) == source


def test_the_five_sources_are_named():
    assert set(SOURCES) == {"corte-madera-town-council", "novato-city-council", "marin-county-bos",
                            "sausalito-city-council", "san-anselmo-town-council"}


@pytest.mark.parametrize("source,title,body", [
    # session variants fold into the body
    ("san-anselmo-town-council", "Town Council", "San Anselmo Town Council"),
    ("san-anselmo-town-council", "Town Council - Special Meeting", "San Anselmo Town Council"),
    ("san-anselmo-town-council", "Special Town Council (No Video Available)", "San Anselmo Town Council"),
    ("san-anselmo-town-council", "Emergency Town Council Meeting", "San Anselmo Town Council"),
    ("san-anselmo-town-council", "Town Council - Cancelled", "San Anselmo Town Council"),
    # one source's id space holds several bodies
    ("san-anselmo-town-council", "Parks and Recreation Commission - Special Meeting",
     "San Anselmo Parks and Recreation Commission"),
    ("san-anselmo-town-council", "Bicycle and Pedestrian Advisory Committee",
     "San Anselmo Bicycle and Pedestrian Advisory Committee"),
    ("san-anselmo-town-council", "Planning Commission", "San Anselmo Planning Commission"),
    ("corte-madera-town-council", "The agenda for the April 2, 2019 Regular Town Council Meeting",
     "Corte Madera Town Council"),
    ("corte-madera-town-council", "The agenda for the December 16, 2025 council closed session special meeting",
     "Corte Madera Town Council"),
    # a council meeting that interviews commission applicants is still the council
    ("corte-madera-town-council",
     "The agenda for the January 17, 2023 Town Council Special Meeting for Planning Commission Interviews",
     "Corte Madera Town Council"),
    ("corte-madera-town-council", "Agenda for the meeting of the Planning Commission",
     "Corte Madera Planning Commission"),
    # a "Fire Council" is not the Town Council
    ("corte-madera-town-council",
     "The agenda for the regular meeting of the Fire Council of the Central Marin Fire Authority",
     "Central Marin Fire Authority Fire Council"),
    ("corte-madera-town-council", "The agenda for the meeting of the Sanitary District No. 2 Board of Directors",
     "Sanitary District No. 2 Board of Directors"),
    ("corte-madera-town-council", "Bicycle Pedestrian Advisory Committee (BPAC) Agenda for 10-17-19 Meeting",
     "Corte Madera Bicycle and Pedestrian Advisory Committee"),
    ("corte-madera-town-council",
     "The agenda for the February 15, 2022 Special Joint Meeting of Town Council & Planning Commission",
     "Corte Madera joint meeting"),
    ("novato-city-council", "City Council Special Closed Session (No Video)", "Novato City Council"),
    ("novato-city-council", "Council Council", "Novato City Council"),
    # the council sitting as its own successor agency is the council
    ("novato-city-council", "Joint City Council / City Council as Successor Agency Meeting", "Novato City Council"),
    ("novato-city-council", "Joint Special Meeting - City Council / Design Review Commission / Planning Commission",
     "Novato joint meeting"),
    ("novato-city-council", "Planning Commission Meeting", "Novato Planning Commission"),
    ("marin-county-bos", "Board of Supervisors 2022", "Marin County Board of Supervisors"),
    ("marin-county-bos", "Budget 2025", "Marin County Board of Supervisors"),
    ("marin-county-bos", "Joint BOS/Planning Commission", "Marin County joint meeting"),
    ("sausalito-city-council", "City Council- Special", "Sausalito City Council"),
    ("sausalito-city-council", "Special City Council", "Sausalito City Council"),
])
def test_known_titles_normalize_to_the_real_body(source, title, body):
    assert normalize_body(source, title) == (body, True)


@pytest.mark.parametrize("source,title", [
    ("novato-city-council", "State of the City"),
    ("sausalito-city-council", "February 5, 2021- Updated Video"),
    ("marin-county-bos", "Spanish Audio Files"),
    ("san-anselmo-town-council", "Imaginary Kite Board"),
])
def test_unknown_titles_pass_through_unchanged(source, title):
    assert normalize_body(source, title) == (title, False)


def test_an_empty_title_passes_through_as_unknown():
    assert normalize_body("sausalito-city-council", "") == ("", False)
