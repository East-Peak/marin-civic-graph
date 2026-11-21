"""Minutes coverage: the explicit source map (registry id, meeting-id shapes, raw directory, document hosts)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import minutes_sources as ms  # noqa: E402


@pytest.mark.parametrize("meeting_id, source", [
    ("meeting-novato-city-council-1234", "novato-city-council"),
    ("meeting-tiburon-town-council-granicus-1000", "tiburon-town-council-granicus"),
    ("meeting-mill-valley-committees-10", "mill-valley-committees"),
    ("meeting-fairfax-town-council-town-council-meeting-april-3-2024", "fairfax-town-council"),
    ("meeting-belvedere-city-council-city-council-meeting-april-10-2023", "belvedere-city-council"),
    ("meeting-ross-town-council-2025-11-13-row-17", "ross-town-council"),
    ("meeting-ross-town-council-towncouncil-page-ross-town-council-meeting-1", "ross-town-council"),
    ("meeting-san-rafael-city-council-city-council-april-20-2026", "san-rafael-city-council"),
    ("meeting-2026-04-06-san-rafael-city-council-closed-session", "san-rafael-city-council"),
])
def test_every_id_shape_maps_to_exactly_one_source(meeting_id, source):
    assert [s.id for s in ms.SOURCE_MAP.values() if s.matches(meeting_id)] == [source]
    assert ms.source_of(meeting_id) == source


@pytest.mark.parametrize("meeting_id", [
    "meeting-tiburon-town-council-77",            # the other Tiburon source, not in this map
    "meeting-novato-city-council-12a",            # a numeric source never takes a slug
    "meeting-corte-madera-town-council-",          # empty suffix
    "meeting-larkspur-city-council-5",
    "meeting-ross-town-council-2025-11-13",        # a date without its row is no shape we hold
])
def test_ids_outside_the_shapes_map_to_no_source(meeting_id):
    assert ms.source_of(meeting_id) is None


def test_file_names_take_the_source_shapes_and_extensions():
    fx = ms.SOURCE_MAP["fairfax-town-council"]
    assert fx.file_meeting_id("meeting-fairfax-town-council-town-council-meeting-may-1-2024.pdf") == \
        "meeting-fairfax-town-council-town-council-meeting-may-1-2024"
    assert fx.file_meeting_id("meeting-fairfax-town-council-x.exe") is None
    ross = ms.SOURCE_MAP["ross-town-council"]
    assert ross.file_meeting_id("meeting-ross-town-council-2025-11-13-row-17.html") == \
        "meeting-ross-town-council-2025-11-13-row-17"
    assert ms.SOURCE_MAP["novato-city-council"].file_meeting_id("meeting-novato-city-council-abc.pdf") is None


def test_the_map_holds_the_eleven_sources_with_their_raw_dirs():
    assert set(ms.SOURCE_MAP) == {
        "san-anselmo-town-council", "corte-madera-town-council", "tiburon-town-council-granicus",
        "novato-city-council", "marin-county-bos", "sausalito-city-council", "mill-valley-committees",
        "fairfax-town-council", "belvedere-city-council", "ross-town-council", "san-rafael-city-council"}
    assert all(s.raw_dir == s.id for s in ms.SOURCE_MAP.values())


def test_initial_hosts_are_exact_and_shared_cloud_hosts_need_the_publisher_path():
    fx = ms.SOURCE_MAP["fairfax-town-council"]
    assert fx.admits("https://storage.googleapis.com/proudcity/fairfaxca/uploads/2020/12/x.pdf")
    assert not fx.admits("https://storage.googleapis.com/proudcity/belvedereca/uploads/2020/12/x.pdf")
    assert not fx.admits("https://storage.googleapis.com/other-bucket/fairfaxca/x.pdf")
    assert not fx.admits("https://evil.storage.googleapis.com/proudcity/fairfaxca/x.pdf")
    assert not fx.admits("http://storage.googleapis.com/proudcity/fairfaxca/x.pdf")  # https only
    nov = ms.SOURCE_MAP["novato-city-council"]
    assert nov.admits("https://novato.granicus.com/MinutesViewer.php?clip_id=1")
    assert not nov.admits("https://marin.granicus.com/MinutesViewer.php?clip_id=1")  # another source's host


def test_a_path_prefix_matches_whole_segments_only():
    rule = ms.HostRule("storage.googleapis.com", "/proudcity/fairfaxca/", "fixture")
    assert rule.admits("https://storage.googleapis.com/proudcity/fairfaxca/a.pdf")
    assert not rule.admits("https://storage.googleapis.com/proudcity/fairfaxca-evil/a.pdf")
    assert not rule.admits("https://storage.googleapis.com/proudcity/fairfaxca/../belvedereca/a.pdf")


@pytest.mark.parametrize("rules, problem", [
    ((ms.HostRule("storage.googleapis.com", None, "x"),), "shared cloud host"),
    ((ms.HostRule("granicus_production_attachments.s3.amazonaws.com", None, "x"),), "shared cloud host"),
    ((ms.HostRule("d3n9y02raazwpg.cloudfront.net", None, "x"),), "shared cloud host"),
    ((ms.HostRule("www.marincounty.gov", None, "x"),), "refused"),
    ((ms.HostRule("novato.gov", None, "x"),), "refused"),
    ((ms.HostRule("example.org", "/a/", ""),), "evidence"),
    ((ms.HostRule("example.org", "a/", "x"),), "path prefix"),
])
def test_validation_rejects_unsafe_rules(rules, problem):
    src = ms.Source("x", "X", "x", ("numeric",), rules)
    with pytest.raises(ms.SourceMapError, match=problem):
        ms.validate(src)


def test_the_shipped_map_validates():
    for s in ms.SOURCE_MAP.values():
        ms.validate(s)


@pytest.mark.parametrize("host, family", [
    ("novato.granicus.com", "granicus.com"), ("townoftiburon.granicus.com", "granicus.com"),
    ("www.cortemadera.gov", "cortemadera.gov"), ("cortemadera.gov", "cortemadera.gov"),
    ("storage.googleapis.com", "storage.googleapis.com"),
    ("granicus_production_attachments.s3.amazonaws.com", "granicus_production_attachments.s3.amazonaws.com"),
    ("www.townofrossca.gov", "townofrossca.gov"), ("NOVATO.Granicus.com.", "granicus.com"),
])
def test_host_families(host, family):
    assert ms.host_family(host) == family


@pytest.mark.parametrize("host", ["marincounty.gov", "www.marincounty.gov", "apps.marincounty.gov", "novato.gov",
                                  "www.novato.gov", "WWW.NOVATO.GOV."])
def test_off_limits_hosts(host):
    assert ms.off_limits(host)


def test_granicus_authority_is_the_vendor_host_or_a_listed_attachment_rule():
    assert ms.granicus_authorized("https://sausalito.granicus.com/MinutesViewer.php?x=1")
    assert not ms.granicus_authorized("https://granicus.com.evil.example/x")
    assert not ms.granicus_authorized("https://storage.googleapis.com/proudcity/fairfaxca/x.pdf")
    rule = ms.HostRule("granicus_production_attachments.s3.amazonaws.com", "/sausalito/", "fixture",
                       authority="granicus")
    assert ms.granicus_authorized("https://granicus_production_attachments.s3.amazonaws.com/sausalito/a.pdf",
                                  (rule,))
    assert not ms.granicus_authorized("https://granicus_production_attachments.s3.amazonaws.com/other/a.pdf",
                                      (rule,))
