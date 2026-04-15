"""Base adapter contract for all ingestion adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path


class BaseAdapter(ABC):
    def __init__(self, source_config: dict, root_dir: Path):
        self.config = source_config
        self.root = root_dir
        self.source_id: str = source_config["id"]
        self.url: str = source_config["url"]
        self.jurisdiction_id: str = source_config["jurisdiction_id"]
        self.institution_id: str = source_config["institution_id"]
        self.backfill_from: str = source_config.get("backfill_from", "2019-01-01")

    @abstractmethod
    def capture(self) -> dict:
        """Fetch and parse the source. Returns the extracted JSON dict."""

    def raw_dir(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.root / "data" / "raw" / self.source_id / today

    def extracted_path(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.root / "data" / "extracted" / self.source_id / f"{today}.json"

    def capture_id(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{self.source_id}__{today}"

    def utc_now_iso(self) -> str:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
