"""Pin each meeting to its first-seen id for life.

I2 (adapters/meeting_ids.py) made ids stable across runs, but a meeting's
native key can still upgrade as it progresses through its lifecycle: a
Granicus meeting with no key yet gets a title-hash id, then ``event-N`` once
its agenda posts, then its clip id once the video posts. Each upgrade would
mint a new id, and since loads MERGE on id, a duplicate Meeting node.

This map links every id a meeting is ever seen under to the first one, through
the (source, date, normalized title) the ids share. Existing ids are never
rewritten: a meeting first seen with its clip id keeps it.

Limitation: a meeting renamed by its city on the same date gets a new
identity (there is nothing shared left to link on).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from adapters.meeting_ids import normalize_title


class MeetingIdentityMap:
    def __init__(self, path: Path):
        self.path = Path(path)
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        self._by_id: dict[str, str] = data.get("by_id", {})
        self._by_key: dict[str, str] = data.get("by_key", {})

    @staticmethod
    def _key(source_id: str, meeting: dict) -> str | None:
        date = meeting.get("date")
        if not isinstance(date, str) or not date:
            return None
        return f"{source_id}|{date[:10]}|{normalize_title(meeting.get('title'))}"

    def canonicalize(self, source_id: str, meetings: list[dict]) -> None:
        """Rewrite each meeting's ``meeting_id`` to its canonical id, in place."""
        for meeting in meetings:
            mid = meeting.get("meeting_id")
            key = self._key(source_id, meeting)
            if not mid or key is None:
                continue
            id_key = f"{source_id}|{mid}"
            canonical = self._by_id.get(id_key) or self._by_key.get(key) or mid
            self._by_id[id_key] = canonical
            self._by_key.setdefault(key, canonical)
            meeting["meeting_id"] = canonical

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ids.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"by_id": self._by_id, "by_key": self._by_key}, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.path)


def merge_duplicate_meetings(meetings: list[dict]) -> list[dict]:
    """Collapse rows sharing a meeting_id into one, keeping every available artifact.

    Sites list the same meeting more than once (Fairfax's archive lists
    2022-06-01 twice, only one copy with minutes; Ross repeats upcoming
    subcommittee rows). First-seen order and fields win; artifacts union,
    preferring an available artifact over an unavailable one.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []
    passthrough: list[dict] = []
    for meeting in meetings:
        mid = meeting.get("meeting_id")
        if not mid:
            passthrough.append(meeting)
            continue
        if mid not in merged:
            merged[mid] = {**meeting, "artifacts": dict(meeting.get("artifacts") or {})}
            order.append(mid)
            continue
        artifacts = merged[mid]["artifacts"]
        for name, art in (meeting.get("artifacts") or {}).items():
            if not (artifacts.get(name) or {}).get("available") and (art or {}).get("available"):
                artifacts[name] = art
    return [merged[mid] for mid in order] + passthrough
