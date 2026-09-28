"""Stable meeting ids shared by the meeting adapters (spec I2).

Loads MERGE Meeting nodes on ``id``, so an id must name the same meeting on
every run. The rule, applied in document order by :func:`assign_meeting_ids`:

1. **Source-native key.** When the row carries one, the id is
   ``meeting-{source_id}-{key}``. Each adapter defines its own key
   (``native_meeting_key``): Granicus ``clip_id`` (the historical id, kept
   verbatim) then ``event-{event_id}``; CivicPlus ``agenda_id``; Ross the
   meeting's detail-page path. Rows that share a native key are one meeting
   and share one id.
2. **Date + title hash.** Otherwise the id is
   ``meeting-{source_id}-{date|undated}-{title_hash}``, where the hash is
   the first 8 hex chars of SHA-1 over :func:`normalize_title`. Rows that
   collide exactly (same date, same normalized title) are suffixed ``-2``,
   ``-3`` … in document order; such twins are indistinguishable, so their
   relative order is the only positional input left.

An id never derives from a row's position on the page.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Callable

_NON_ALNUM_RE = re.compile(r"[\W_]+")


def normalize_title(title: str | None) -> str:
    """Lowercase, replace punctuation with spaces, and collapse whitespace."""
    return " ".join(_NON_ALNUM_RE.sub(" ", (title or "").lower()).split())


def title_hash(title: str | None) -> str:
    """Return the 8-hex-char SHA-1 of the normalized *title*."""
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:8]


def assign_meeting_ids(
    meetings: list[dict],
    source_id: str,
    native_key: Callable[[dict], str | None],
    name: Callable[[dict], str | None] = lambda m: m.get("title"),
) -> None:
    """Stamp ``meeting_id`` onto each meeting dict, in place, per the module rule.

    *name* picks the text hashed for the fallback (default: the title).
    """
    fallbacks: Counter[str] = Counter()
    for m in meetings:
        key = native_key(m)
        if key:
            m["meeting_id"] = f"meeting-{source_id}-{key}"
            continue
        base = f"meeting-{source_id}-{m.get('date') or 'undated'}-{title_hash(name(m))}"
        fallbacks[base] += 1
        n = fallbacks[base]
        m["meeting_id"] = base if n == 1 else f"{base}-{n}"
