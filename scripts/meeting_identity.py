"""Pin each meeting to its first-seen id for life.

I2 (adapters/meeting_ids.py) made ids stable across runs, but a meeting's
native key can still upgrade as it progresses through its lifecycle: a
Granicus meeting with no key yet gets a title-hash id, then ``event-N`` once
its agenda posts, then its clip id once the video posts. Each upgrade would
mint a new id, and since loads MERGE on id, a duplicate Meeting node.

This map links every id a meeting is ever seen under to the first one, through
the (source, date, category, normalized title) the ids share. Existing ids are
never rewritten: a meeting first seen with its clip id keeps it.

The key may only link ids when it is UNAMBIGUOUS. Adversarial review
(2026-09-28, P0) reproduced the failure otherwise: two distinct Marin BOS clips
on the same date with identical titles collapsed onto one id, and the
duplicate merge then dropped the second clip's minutes and video. So:
  * an id already known to the map keeps its own canonical, never re-linked;
  * a key shared by two or more meetings in one pull is marked ambiguous,
    permanently, and never links anything again;
  * a canonical id already claimed by another meeting in this pull is not
    handed out a second time.
Under ambiguity a meeting simply keeps its own id: at worst a lifecycle
upgrade yields a second node (recoverable by the operator dedupe step);
never a silent merge of two real meetings (unrecoverable data loss).

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
        self._ambiguous: set[str] = set(data.get("ambiguous_keys", []))

    @staticmethod
    def _key(source_id: str, meeting: dict) -> str | None:
        date = meeting.get("date")
        if not isinstance(date, str) or not date:
            return None
        category = normalize_title(meeting.get("category"))
        return f"{source_id}|{date[:10]}|{category}|{normalize_title(meeting.get('title'))}"

    def canonicalize(self, source_id: str, meetings: list[dict]) -> None:
        """Rewrite each meeting's ``meeting_id`` to its canonical id, in place."""
        keyed = [(m, m.get("meeting_id"), self._key(source_id, m)) for m in meetings]
        keyed = [(m, mid, key) for m, mid, key in keyed if mid and key is not None]

        # Keys shared by distinct ids in this pull are ambiguous for good.
        ids_per_key: dict[str, set[str]] = {}
        for _, mid, key in keyed:
            ids_per_key.setdefault(key, set()).add(mid)
        self._ambiguous.update(k for k, ids in ids_per_key.items() if len(ids) > 1)

        claimed: dict[str, str] = {}  # canonical -> the incoming id that took it
        for meeting, mid, key in keyed:
            id_key = f"{source_id}|{mid}"
            canonical = self._by_id.get(id_key)
            if canonical is None and key not in self._ambiguous:
                linked = self._by_key.get(key)
                if linked is not None and claimed.get(linked, mid) == mid:
                    canonical = linked
            if canonical is None or claimed.get(canonical, mid) != mid:
                canonical = mid
            claimed[canonical] = mid
            self._by_id[id_key] = canonical
            if key not in self._ambiguous:
                self._by_key.setdefault(key, canonical)
            meeting["meeting_id"] = canonical

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ids.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"by_id": self._by_id, "by_key": self._by_key,
                       "ambiguous_keys": sorted(self._ambiguous)}, fh, indent=1, sort_keys=True)
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
