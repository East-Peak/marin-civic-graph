import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from adapters import get_adapter_class
from adapters.base import BaseAdapter


class TestAdapterRegistry:
    def test_get_granicus_adapter(self):
        cls = get_adapter_class("granicus")
        assert cls is not None
        assert issubclass(cls, BaseAdapter)

    def test_unknown_adapter_raises(self):
        with pytest.raises(KeyError):
            get_adapter_class("nonexistent")


class TestBaseAdapterContract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseAdapter({}, Path("."))
