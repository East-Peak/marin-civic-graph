import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_embeddings import (
    EMBEDDING_VERSION,
    synth_text_for_node,
    synthesis_hash,
    needs_embed,
)


class TestSynthText:
    def test_eligible_person_with_neighbors(self):
        text = synth_text_for_node(
            {"id": "person-kate-colin", "type": "Person",
             "label": "Kate Colin", "role": "Council member",
             "jurisdiction_name": "San Rafael"},
            neighbors=[
                {"id": "decision-1", "type": "Decision", "label": "Approve permit"},
            ],
        )
        assert "Kate Colin" in text
        assert "San Rafael" in text
        assert "Approve permit" in text

    def test_ineligible_anchor_returns_empty(self):
        text = synth_text_for_node(
            {"id": "x-1", "type": "CriminalRecord", "label": "x"},
            neighbors=[],
        )
        assert text == ""


class TestSynthesisHash:
    def test_deterministic(self):
        node = {"id": "person-kate-colin", "type": "Person", "label": "Kate"}
        h1 = synthesis_hash(synth_text_for_node(node, []), [])
        h2 = synthesis_hash(synth_text_for_node(node, []), [])
        assert h1 == h2

    def test_neighbor_id_changes_hash(self):
        node = {"id": "p-1", "type": "Person", "label": "X"}
        h_a = synthesis_hash(
            synth_text_for_node(node, [{"id": "d-1", "type": "Decision", "label": "A"}]),
            ["d-1"],
        )
        h_b = synthesis_hash(
            synth_text_for_node(node, [{"id": "d-2", "type": "Decision", "label": "A"}]),
            ["d-2"],
        )
        assert h_a != h_b

    def test_text_change_changes_hash(self):
        node_a = {"id": "p-1", "type": "Person", "label": "Kate"}
        node_b = {"id": "p-1", "type": "Person", "label": "Kathleen"}
        h_a = synthesis_hash(synth_text_for_node(node_a, []), [])
        h_b = synthesis_hash(synth_text_for_node(node_b, []), [])
        assert h_a != h_b


class TestNeedsEmbed:
    def test_no_existing_embedding(self):
        assert needs_embed({"embedding_hash": None}, current_hash="abc")

    def test_hash_match_skips(self):
        assert not needs_embed({"embedding_hash": "abc"}, current_hash="abc")

    def test_hash_mismatch_re_embeds(self):
        assert needs_embed({"embedding_hash": "old"}, current_hash="new")

    def test_version_bump_re_embeds(self):
        # If EMBEDDING_VERSION is bumped, existing embeddings stale even with matching hash.
        node = {"embedding_hash": "abc", "embedding_version": EMBEDDING_VERSION - 1}
        assert needs_embed(node, current_hash="abc")
