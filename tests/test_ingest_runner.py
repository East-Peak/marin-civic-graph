import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ingest import load_sources, resolve_sources


@pytest.fixture
def sample_registry(tmp_path):
    yaml_content = """sources:
  - id: test-source-1
    adapter: granicus
    url: https://example.com/1
    jurisdiction_id: place-test1
    institution_id: org-test1
    backfill_from: "2019-01-01"
    schedule: weekly
  - id: test-source-2
    adapter: granicus
    url: https://example.com/2
    jurisdiction_id: place-test2
    institution_id: org-test2
    backfill_from: "2020-01-01"
    schedule: monthly
"""
    path = tmp_path / "sources.yaml"
    path.write_text(yaml_content)
    return path


class TestLoadSources:
    def test_loads_all_sources(self, sample_registry):
        sources = load_sources(sample_registry)
        assert len(sources) == 2
        assert sources[0]["id"] == "test-source-1"

    def test_source_has_required_fields(self, sample_registry):
        sources = load_sources(sample_registry)
        s = sources[0]
        assert "id" in s
        assert "adapter" in s
        assert "url" in s
        assert "jurisdiction_id" in s
        assert "institution_id" in s


class TestResolveSources:
    def test_resolve_by_source_id(self, sample_registry):
        sources = load_sources(sample_registry)
        resolved = resolve_sources(sources, source="test-source-1")
        assert len(resolved) == 1
        assert resolved[0]["id"] == "test-source-1"

    def test_resolve_all(self, sample_registry):
        sources = load_sources(sample_registry)
        resolved = resolve_sources(sources, all_sources=True)
        assert len(resolved) == 2

    def test_resolve_unknown_raises(self, sample_registry):
        sources = load_sources(sample_registry)
        with pytest.raises(ValueError):
            resolve_sources(sources, source="nonexistent")

    def test_resolve_no_args_raises(self, sample_registry):
        sources = load_sources(sample_registry)
        with pytest.raises(ValueError):
            resolve_sources(sources)
