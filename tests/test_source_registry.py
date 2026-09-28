"""Contract for the meeting-source registries the weekly runner schedules.

`ingest.py --all` runs only `schedule: weekly` sources; `manual` and
`retired` sources stay in the registry (for history and one-off runs via
--source) but never run on the schedule. See
docs/specs/2026-09-28-persistent-ingestion-design.md (I3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ingest import SCHEDULES, resolve_sources  # noqa: E402

MEETING_REGISTRIES = [
    ROOT / "registry" / name
    for name in (
        "granicus-sources.yaml",
        "civicplus-sources.yaml",
        "proudcity-sources.yaml",
        "drupal-sources.yaml",
    )
]
REQUIRED = ("id", "adapter", "url", "jurisdiction_id", "institution_id", "schedule")


def _sources(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text()).get("sources", [])


def _all_sources() -> dict[str, dict]:
    return {s["id"]: s for p in MEETING_REGISTRIES for s in _sources(p)}


def test_all_runs_only_weekly_sources():
    sources = [
        {"id": "a", "schedule": "weekly"},
        {"id": "b", "schedule": "manual"},
        {"id": "c", "schedule": "retired"},
    ]
    assert [s["id"] for s in resolve_sources(sources, all_sources=True)] == ["a"]
    # --source still reaches a non-weekly source explicitly.
    assert resolve_sources(sources, source="b")[0]["id"] == "b"


@pytest.mark.parametrize("path", MEETING_REGISTRIES, ids=lambda p: p.name)
def test_every_source_is_well_formed(path):
    for s in _sources(path):
        missing = [k for k in REQUIRED if not s.get(k)]
        assert not missing, f"{s.get('id')}: missing {missing}"
        assert s["schedule"] in SCHEDULES, f"{s['id']}: schedule {s['schedule']!r}"
        if s["schedule"] != "weekly":
            assert s.get("schedule_note"), f"{s['id']}: non-weekly sources must say why"


def test_source_ids_are_unique_across_registries():
    ids = [s["id"] for p in MEETING_REGISTRIES for s in _sources(p)]
    assert len(ids) == len(set(ids))


def test_san_rafael_case_study_city_is_registered_pending_id_reconciliation():
    # Registered so it can be captured with --source. Held off the weekly
    # schedule until its meeting ids are reconciled with the hand-built
    # wave-01 ids already in the graph (meeting-{date}-san-rafael-city-council),
    # otherwise the first scheduled load would duplicate every meeting.
    sr = _all_sources()["san-rafael-city-council"]
    assert sr["adapter"] == "proudcity"
    assert sr["institution_id"] == "org-san-rafael-city-council"
    assert sr["jurisdiction_id"] == "place-san-rafael"
    assert sr["schedule"] == "manual"
    assert "id" in sr["schedule_note"].lower()


def test_fairfax_covers_2025_onward():
    ff = _all_sources()["fairfax-town-council"]
    assert "https://townoffairfaxca.gov/agendas-town-council/" in ff["archive_pages"]


def test_dead_civicplus_tiburon_is_retired_not_scheduled():
    assert _all_sources()["tiburon-town-council"]["schedule"] == "retired"


def test_mill_valley_uses_current_domain():
    for sid in ("mill-valley-planning-commission", "mill-valley-parks-recreation"):
        assert _all_sources()[sid]["url"].startswith("https://www.cityofmillvalley.gov/")


def test_corte_madera_planning_commission_is_held_until_reconciled():
    # 182 of its 193 meetings already sit in the April corte-madera-town-council
    # capture under that source's ids; scheduling it would load them twice.
    pc = _all_sources()["corte-madera-planning-commission"]
    assert pc["schedule"] == "manual"
    assert "corte-madera-town-council" in pc["schedule_note"]


def test_corte_madera_town_council_says_its_first_run_needs_a_baseline_reset():
    note = _all_sources()["corte-madera-town-council"]["floors"]["note"]
    assert "ingest_baseline.py --reset corte-madera-town-council" in note


@pytest.mark.parametrize("path", MEETING_REGISTRIES + [ROOT / "registry" / "netfile-sources.yaml"],
                         ids=lambda p: p.name)
def test_every_floors_block_parses(path):
    from ingest_guard import Floors

    for s in _sources(path):
        Floors.from_config(s)
