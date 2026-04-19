# tests/scripts/test_build_signature_subgraphs.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_signature_subgraphs import (
    classify_edge_style,
    build_node_payload,
    expand_template,
)


def test_classify_money_edge():
    assert classify_edge_style("FROM_SOURCE") == "money"
    assert classify_edge_style("TO_TARGET") == "money"
    assert classify_edge_style("DISCLOSED_IN") == "money"
    assert classify_edge_style("UNDER_AGREEMENT") == "money"


def test_classify_legal_edge():
    assert classify_edge_style("CONSTRAINS") == "legal-constrains"


def test_classify_governance_default():
    assert classify_edge_style("AT_MEETING") == "governance"
    assert classify_edge_style("UNKNOWN_EDGE_TYPE") == "governance"


def test_node_payload_shape():
    node = {
        "id": "project-merrydale",
        "labels": ["Project"],
        "search_label": "Merrydale",
    }
    payload = build_node_payload(node, role="focus")
    assert payload["id"] == "project-merrydale"
    assert payload["type"] == "Project"
    assert payload["label"] == "Merrydale"
    assert payload["role"] == "focus"
    assert payload["route"] == "/graph?focus=project-merrydale"


def test_expand_template_replaces_placeholders():
    stats = {"money_total": "15,337,953", "decision_count": 6}
    tpl = "${{money_total}} · {{decision_count}} decisions"
    assert expand_template(tpl, stats) == "$15,337,953 · 6 decisions"


def test_expand_template_leaves_unknowns_blank():
    assert expand_template("{{missing}}", {}) == ""
