import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.parity_core import (
    apply_deltas,
    diff_case,
    iter_corpus,
    load_case,
    load_deltas,
    normalize_payload,
    save_case,
)


@pytest.mark.parametrize("surface", ["search", "browse", "data", "path"])
def test_normalize_payload_strips_drift_keys_and_preserves_contractual_list_order(surface):
    payload = {
        "built_at": "2026-07-07T12:00:00Z",
        "results": [
            {
                "id": "b",
                "signed_url": "https://example.test/b?sig=1",
                "nested": {"expires_at": "later", "value": 2},
            },
            {"id": "a", "value": 1},
        ],
    }

    normalized = normalize_payload(surface, payload)

    assert normalized == {
        "results": [
            {"id": "b", "nested": {"value": 2}},
            {"id": "a", "value": 1},
        ]
    }
    assert payload["results"][0]["signed_url"] == "https://example.test/b?sig=1"


def test_normalize_payload_sorts_entity_neighbors_and_edges_but_keeps_total():
    payload = {
        "neighbor_total": 2,
        "neighbors": [
            {"id": "org:z", "label": "Zed", "built_at": "now"},
            {"id": "org:a", "label": "Alpha"},
        ],
        "edges": [
            {"source": "p:2", "target": "org:z", "type": "MEMBER_OF"},
            {"source": "p:1", "target": "org:a", "type": "FUNDS"},
            {"source": "p:1", "target": "org:a", "type": "ADVISES"},
        ],
    }

    normalized = normalize_payload("entity", payload)

    assert [neighbor["id"] for neighbor in normalized["neighbors"]] == ["org:a", "org:z"]
    assert [
        (edge["source"], edge["target"], edge["type"]) for edge in normalized["edges"]
    ] == [
        ("p:1", "org:a", "ADVISES"),
        ("p:1", "org:a", "FUNDS"),
        ("p:2", "org:z", "MEMBER_OF"),
    ]
    assert normalized["neighbor_total"] == 2
    assert "built_at" not in normalized["neighbors"][1]


def test_normalize_payload_sorts_expand_nodes_and_edges_but_keeps_counts():
    payload = {
        "new_count": 2,
        "cap": 10,
        "nodes": [{"id": "node:b"}, {"id": "node:a"}],
        "edges": [
            {"source": "node:b", "target": "node:c", "type": "LINKED_TO"},
            {"source": "node:a", "target": "node:c", "type": "FUNDS"},
        ],
    }

    normalized = normalize_payload("expand", payload)

    assert [node["id"] for node in normalized["nodes"]] == ["node:a", "node:b"]
    assert [
        (edge["source"], edge["target"], edge["type"]) for edge in normalized["edges"]
    ] == [
        ("node:a", "node:c", "FUNDS"),
        ("node:b", "node:c", "LINKED_TO"),
    ]
    assert normalized["new_count"] == 2
    assert normalized["cap"] == 10


def test_normalize_payload_status_drops_ingest_at_but_keeps_counts():
    payload = {
        "ingest_at": "2026-07-07",
        "counts": {"nodes": 7, "edges": 11},
        "source": {"ingest_at": "2026-07-06", "counts": {"records": 3}},
    }

    normalized = normalize_payload("status", payload)

    assert normalized == {
        "counts": {"nodes": 7, "edges": 11},
        "source": {"counts": {"records": 3}},
    }


def test_corpus_io_round_trips_normalized_cases_with_sorted_keys_and_newline(tmp_path):
    corpus_dir = tmp_path / "corpus"
    case = {
        "request": {
            "method": "GET",
            "url_path": "/api/search",
            "params": {"q": "housing"},
        },
        "http_status": 200,
        "payload": {
            "built_at": "2026-07-07T12:00:00Z",
            "results": [{"id": "b"}, {"id": "a"}],
        },
    }

    path = save_case(corpus_dir, "search", "housing-basic", case)

    assert path == corpus_dir / "search" / "housing-basic.json"
    text = path.read_text()
    assert text.endswith("\n")
    assert text.splitlines()[1] == '  "http_status": 200,'
    stored = json.loads(text)
    assert stored["payload"] == {"results": [{"id": "b"}, {"id": "a"}]}

    loaded = load_case(corpus_dir, "search", "housing-basic")
    assert loaded["_surface"] == "search"
    assert loaded["_case"] == "housing-basic"
    assert loaded["payload"] == stored["payload"]
    assert list(iter_corpus(corpus_dir)) == [("search", "housing-basic", loaded)]


def test_diff_case_reports_status_keys_values_paths_and_caps_mismatches():
    expected_case = {
        "_surface": "search",
        "http_status": 200,
        "payload": {
            "kept": True,
            "results": [{"id": "a", "value": 1}],
        },
    }

    mismatches = diff_case(
        expected_case,
        {
            "other": "unexpected",
            "results": [{"id": "a", "value": 2, "extra": "field"}],
        },
        500,
    )

    assert "status mismatch: expected 200, got 500" in mismatches
    assert "$.kept: missing key" in mismatches
    assert "$.other: extra key" in mismatches
    assert "$.results[0].extra: extra key" in mismatches
    assert "$.results[0].value: expected 1, got 2" in mismatches

    too_many = diff_case(
        {
            "_surface": "search",
            "http_status": 200,
            "payload": {f"k{i:02d}": i for i in range(25)},
        },
        {},
        200,
    )
    assert len(too_many) == 20
    assert too_many[-1] == "... truncated after 20 mismatches"


def test_diff_case_normalizes_actual_payload_for_expected_surface():
    expected_case = {
        "_surface": "entity",
        "http_status": 200,
        "payload": {
            "neighbors": [{"id": "a"}, {"id": "b"}],
            "edges": [
                {"source": "a", "target": "b", "type": "FIRST"},
                {"source": "b", "target": "a", "type": "SECOND"},
            ],
        },
    }

    mismatches = diff_case(
        expected_case,
        {
            "neighbors": [{"id": "b"}, {"id": "a"}],
            "edges": [
                {"source": "b", "target": "a", "type": "SECOND"},
                {"source": "a", "target": "b", "type": "FIRST"},
            ],
        },
        200,
    )

    assert mismatches == []


DELTA_YAML = (
    "- surface: data\n"
    "  case: campaign-money-30d\n"
    "  paths:\n"
    "    - $.rows[*].decision_title\n"
    "    - $.meta.*.built\n"
    "  reason: tie order across decisions\n"
)


@pytest.mark.parametrize("use_yaml", [True, False])
def test_load_deltas_reads_field_level_paths(tmp_path, monkeypatch, use_yaml):
    if not use_yaml:
        monkeypatch.setitem(sys.modules, "yaml", None)  # force the tiny parser
    delta_path = tmp_path / "approved-deltas.yaml"
    delta_path.write_text(DELTA_YAML)

    assert load_deltas(delta_path) == [
        {
            "surface": "data",
            "case": "campaign-money-30d",
            "paths": ["$.rows[*].decision_title", "$.meta.*.built"],
            "reason": "tie order across decisions",
        }
    ]


@pytest.mark.parametrize(
    "entry",
    [
        "- surface: data\n  case: c\n  reason: whole-case exemptions are gone\n",
        "- surface: data\n  case: c\n  paths: []\n  reason: empty\n",
        "- surface: data\n  case: c\n  paths:\n    - $\n  reason: root is a whole case\n",
        "- surface: data\n  case: c\n  paths:\n    - rows[0]\n  reason: not a path\n",
    ],
)
def test_load_deltas_rejects_case_wide_or_malformed_paths(tmp_path, entry):
    delta_path = tmp_path / "approved-deltas.yaml"
    delta_path.write_text(entry)
    with pytest.raises(ValueError):
        load_deltas(delta_path)


def test_apply_deltas_excuses_only_named_paths(tmp_path):
    delta_path = tmp_path / "approved-deltas.yaml"
    delta_path.write_text(DELTA_YAML)
    deltas = load_deltas(delta_path)
    excused = [
        '$.rows[0].decision_title: expected "a", got "b"',
        '$.rows[17].decision_title: expected "b", got "a"',
        "$.meta.corpus.built: missing key",
    ]
    unrelated = [
        '$.rows[0].money_amount: expected 1, got 2',
        '$.rows[0].decision_title_extra: expected "a", got "b"',
        "$.rows: length mismatch: expected 2, got 3",
        "$.meta.corpus.nested.built: missing key",
        "status mismatch: expected 200, got 500",
    ]

    errors, warnings = apply_deltas("data", "campaign-money-30d", excused + unrelated, deltas)

    assert errors == unrelated
    assert warnings == [
        "approved delta for data/campaign-money-30d (tie order across decisions): " + m
        for m in excused
    ]
    # Another case (or surface) with the same paths gets no exemption.
    assert apply_deltas("data", "money-default", excused, deltas) == (excused, [])
    assert apply_deltas("search", "campaign-money-30d", excused, deltas) == (excused, [])


def test_apply_deltas_path_covers_its_subtree():
    deltas = [{"surface": "status", "case": "status", "paths": ["$.counts"], "reason": "r"}]
    errors, warnings = apply_deltas(
        "status", "status",
        ["$.counts.edges: expected 1, got 2", '$.counts["Org X"]: extra key', "$.countsx: missing key"],
        deltas,
    )
    assert errors == ["$.countsx: missing key"]
    assert len(warnings) == 2


def test_committed_approved_deltas_pin_known_replay_drift():
    deltas = load_deltas(Path(__file__).parent / "approved-deltas.yaml")

    assert deltas == [
        {
            "surface": "data",
            "case": "campaign-money-30d",
            "paths": ["$.rows[*].decision_title"],
            "reason": (
                "live tie order underdetermined for pairs sharing abs delta + decided_at "
                "\u2014 same flow id ties across decisions"
            ),
        },
        {
            "surface": "data",
            "case": "campaign-money-90d",
            "paths": ["$.rows[*].decision_title"],
            "reason": (
                "live tie order underdetermined for pairs sharing abs delta + decided_at "
                "\u2014 same flow id ties across decisions"
            ),
        },
        {
            "surface": "status",
            "case": "status",
            "paths": ["$.edge_count", "$.node_count"],
            "reason": (
                "composed artifact is overlay-authoritative \u2014 carries 21 stamped "
                "SAME_AS edges + anchor nodes live lags"
            ),
        },
        {
            "surface": "data",
            "case": "money-default",
            "paths": ["$.rows[*].target_name"],
            "reason": (
                "live carries duplicate-id vendor stub nodes (59 pairs, ingestion bug "
                "per spec 4.2); the bake MERGEs them, so target_name resolves to the "
                "enriched node while live binds the bare stub"
            ),
        },
        {
            "surface": "data",
            "case": "proceedings-default",
            "paths": ["$.rows[*].affected_program"],
            "reason": (
                "link order within a proceeding group is underdetermined on live (no "
                "ORDER BY on link in the Cypher); row COUNTS and all values match"
            ),
        },
        {
            "surface": "data",
            "case": "proceedings-boyd",
            "paths": ["$.rows[*].affected_program"],
            "reason": (
                "link order within a proceeding group is underdetermined on live (no "
                "ORDER BY on link in the Cypher); row COUNTS and all values match"
            ),
        },
    ]
