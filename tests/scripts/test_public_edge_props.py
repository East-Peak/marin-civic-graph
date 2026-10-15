"""The relationship-property allowlist shared by the bake and the app (registry/edge-properties.json)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from public_edge_props import (  # noqa: E402
    DEFAULT_EDGE_PROPERTIES_PATH,
    EdgePropStats,
    load_edge_allowlist,
    public_edge_props,
)

SENTINEL = "ledger_secret_code"


def _write(tmp_path: Path, relationships: dict) -> Path:
    path = tmp_path / "edge-properties.json"
    path.write_text(json.dumps({"relationships": relationships}), encoding="utf-8")
    return path


def test_the_shared_allowlist_admits_only_the_vote_on_cast_vote() -> None:
    allowlist = load_edge_allowlist(DEFAULT_EDGE_PROPERTIES_PATH)

    assert allowlist == {"CAST_VOTE": {"vote": ("aye", "no", "abstain", "absent", "recused")}}


@pytest.mark.parametrize(
    "relationships",
    [
        {"cast_vote": {"vote": ["aye"]}},
        {"CAST_VOTE": {"Vote": ["aye"]}},
        {"CAST_VOTE": {"vote}) RETURN 1 //": ["aye"]}},
        {"CAST_VOTE": {"vote": []}},
        {"CAST_VOTE": {"vote": ["aye", 1]}},
        {"CAST_VOTE": {"vote": ["aye", "aye"]}},
        {"CAST_VOTE": {"vote": ["it's"]}},
    ],
)
def test_a_malformed_allowlist_is_refused(tmp_path: Path, relationships: dict) -> None:
    with pytest.raises(ValueError):
        load_edge_allowlist(_write(tmp_path, relationships))


def test_only_allowlisted_in_vocabulary_values_survive_and_drops_are_counted() -> None:
    allowlist = load_edge_allowlist(DEFAULT_EDGE_PROPERTIES_PATH)
    stats = EdgePropStats()

    kept = public_edge_props(
        "CAST_VOTE",
        {"vote": "no", "seat_id": "seat-x", "seat_service_id": "ss-x", SENTINEL: "s3cret"},
        allowlist,
        stats,
    )
    invalid = public_edge_props("CAST_VOTE", {"vote": "maybe-later", SENTINEL: "s3cret"}, allowlist, stats)
    folded = public_edge_props("CAST_VOTE", {"vote": "AYE"}, allowlist, stats)
    other_rel = public_edge_props("SAME_AS", {"assertion_id": "a-1", "vote": "aye"}, allowlist, stats)
    nothing = public_edge_props("CAST_VOTE", {}, allowlist, stats)

    assert kept == {"vote": "no"}
    assert invalid is None
    assert folded is None
    assert other_rel is None
    assert nothing is None
    assert stats.as_report() == {
        "CAST_VOTE": {
            "kept": {"vote": 1},
            "dropped_out_of_vocabulary": {"vote": 2},
            "dropped_non_allowlisted": 4,
        },
        "SAME_AS": {"kept": {}, "dropped_out_of_vocabulary": {}, "dropped_non_allowlisted": 2},
    }
    report_text = json.dumps(stats.as_report())
    for leaked in ("maybe-later", "AYE", "s3cret", SENTINEL, "seat_id", "seat-x", "assertion_id"):
        assert leaked not in report_text


def test_a_non_string_vote_is_out_of_vocabulary_and_null_is_absent() -> None:
    # Neo4j cannot store null, so null only ever means "not set" (a live projection of a missing property).
    allowlist = load_edge_allowlist(DEFAULT_EDGE_PROPERTIES_PATH)
    stats = EdgePropStats()

    assert public_edge_props("CAST_VOTE", {"vote": ["aye"]}, allowlist, stats) is None
    assert public_edge_props("CAST_VOTE", {"vote": None}, allowlist, stats) is None
    assert stats.as_report()["CAST_VOTE"] == {
        "kept": {},
        "dropped_out_of_vocabulary": {"vote": 1},
        "dropped_non_allowlisted": 0,
    }
