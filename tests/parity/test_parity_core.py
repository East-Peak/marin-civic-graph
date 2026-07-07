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


def test_load_deltas_and_apply_deltas_downgrades_matching_mismatches_to_warnings(tmp_path):
    delta_path = tmp_path / "approved-deltas.yml"
    delta_path.write_text(
        "- surface: entity\n"
        "  case: unstable-neighbor-order\n"
        "  reason: Known source-side ordering drift while endpoint is refactored\n"
    )

    deltas = load_deltas(delta_path)

    assert deltas == [
        {
            "surface": "entity",
            "case": "unstable-neighbor-order",
            "reason": "Known source-side ordering drift while endpoint is refactored",
        }
    ]

    errors, warnings = apply_deltas(
        "entity",
        "unstable-neighbor-order",
        ["$.neighbors[0].id: expected \"a\", got \"b\""],
        deltas,
    )
    assert errors == []
    assert warnings == [
        "approved delta for entity/unstable-neighbor-order "
        "(Known source-side ordering drift while endpoint is refactored): "
        '$.neighbors[0].id: expected "a", got "b"'
    ]

    errors, warnings = apply_deltas(
        "search",
        "unstable-neighbor-order",
        ["$.results[0].id: expected \"a\", got \"b\""],
        deltas,
    )
    assert errors == ['$.results[0].id: expected "a", got "b"']
    assert warnings == []
