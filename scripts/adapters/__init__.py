"""Adapter registry — maps adapter names to classes."""

from __future__ import annotations
from typing import Type
from .base import BaseAdapter


def get_adapter_class(name: str) -> Type[BaseAdapter]:
    from .granicus import GranicusAdapter
    registry: dict[str, Type[BaseAdapter]] = {
        "granicus": GranicusAdapter,
    }
    if name not in registry:
        raise KeyError(f"Unknown adapter: {name!r}. Available: {list(registry.keys())}")
    return registry[name]
