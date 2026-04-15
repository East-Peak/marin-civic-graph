"""Adapter registry — maps adapter names to classes."""

from __future__ import annotations
from typing import Type
from .base import BaseAdapter


def get_adapter_class(name: str) -> Type[BaseAdapter]:
    from .granicus import GranicusAdapter
    from .civicplus import CivicPlusAdapter
    from .netfile import NetFileAdapter
    from .proudcity import ProudCityAdapter
    from .drupal_ross import DrupalRossAdapter
    registry: dict[str, Type[BaseAdapter]] = {
        "granicus": GranicusAdapter,
        "civicplus": CivicPlusAdapter,
        "netfile": NetFileAdapter,
        "proudcity": ProudCityAdapter,
        "drupal_ross": DrupalRossAdapter,
    }
    if name not in registry:
        raise KeyError(f"Unknown adapter: {name!r}. Available: {list(registry.keys())}")
    return registry[name]
