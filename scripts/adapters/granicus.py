"""Granicus Publisher View adapter — stub."""

from __future__ import annotations
from pathlib import Path
from .base import BaseAdapter


class GranicusAdapter(BaseAdapter):
    def capture(self) -> dict:
        raise NotImplementedError("Granicus capture not yet implemented")
