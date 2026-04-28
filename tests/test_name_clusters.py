import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from name_clusters import (
    deterministic_candidate,
    validate_llm_name,
    BANNED_TERMS,
    apply_override,
)


class TestDeterministicCandidate:
    def test_uses_dominant_jurisdiction_and_type(self):
        members = [
            {"label": "Approve housing", "type": "Decision", "jurisdiction_name": "San Rafael"},
            {"label": "Reject housing", "type": "Decision", "jurisdiction_name": "San Rafael"},
            {"label": "Approve housing", "type": "Decision", "jurisdiction_name": "San Rafael"},
        ]
        c = deterministic_candidate(members)
        assert "San Rafael" in c
        assert "Decision" in c

    def test_falls_back_when_no_jurisdiction(self):
        members = [{"label": "X", "type": "Issue"}, {"label": "Y", "type": "Issue"}]
        c = deterministic_candidate(members)
        assert "Issue" in c

    def test_includes_top_tokens(self):
        members = [
            {"label": "housing reform measure", "type": "Decision",
             "jurisdiction_name": "Marin"},
            {"label": "housing affordability act", "type": "Decision",
             "jurisdiction_name": "Marin"},
            {"label": "housing zoning update", "type": "Decision",
             "jurisdiction_name": "Marin"},
        ]
        c = deterministic_candidate(members)
        assert "housing" in c.lower()


class TestValidateLLMName:
    def test_accepts_clean_factual(self):
        assert validate_llm_name(
            "San Rafael housing decisions",
            cluster_tokens={"san", "rafael", "housing"},
        )

    def test_rejects_banned_terms(self):
        for banned in BANNED_TERMS:
            assert not validate_llm_name(
                f"San Rafael {banned} decisions",
                cluster_tokens={"san", "rafael"},
            ), f"{banned} should be rejected"

    def test_rejects_too_short(self):
        assert not validate_llm_name("housing", cluster_tokens={"housing"})

    def test_rejects_too_long(self):
        assert not validate_llm_name(
            "one two three four five six seven eight",
            cluster_tokens={"one"},
        )

    def test_rejects_when_no_cluster_token_overlap(self):
        # LLM hallucinated a name that has nothing to do with the cluster.
        assert not validate_llm_name(
            "marine biology research",
            cluster_tokens={"san", "rafael", "housing"},
        )


class TestApplyOverride:
    def test_override_wins(self, tmp_path, monkeypatch):
        registry = tmp_path / "overrides.json"
        registry.write_text(json.dumps({"7": "Stuart's pinned name"}))
        monkeypatch.setenv("CLUSTER_NAME_OVERRIDES_PATH", str(registry))
        # Even with a polished LLM name, an override forces it.
        result = apply_override(cluster_id=7,
                                deterministic="Marin · Decision · housing",
                                llm_proposed="San Rafael housing decisions")
        assert result == "Stuart's pinned name"

    def test_no_override_falls_through_to_llm(self, tmp_path, monkeypatch):
        registry = tmp_path / "overrides.json"
        registry.write_text("{}")
        monkeypatch.setenv("CLUSTER_NAME_OVERRIDES_PATH", str(registry))
        result = apply_override(cluster_id=7,
                                deterministic="X",
                                llm_proposed="Y")
        assert result == "Y"

    def test_no_override_no_llm_uses_deterministic(self, tmp_path, monkeypatch):
        registry = tmp_path / "overrides.json"
        registry.write_text("{}")
        monkeypatch.setenv("CLUSTER_NAME_OVERRIDES_PATH", str(registry))
        result = apply_override(cluster_id=7,
                                deterministic="X",
                                llm_proposed=None)
        assert result == "X"
