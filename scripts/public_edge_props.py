"""Which relationship properties are public: registry/edge-properties.json, shared with the app.

A property survives only when its relationship type allowlists it and its value is one of the listed strings (exact
match). Everything else is dropped and counted; the counts never carry a value or an unlisted property's name. When
several relationships share one (source, type, target), their public properties are kept only if they all agree:
disagreeing duplicates show nothing (and are counted) rather than an arbitrary one of them.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_EDGE_PROPERTIES_PATH = Path(__file__).resolve().parent.parent / "registry" / "edge-properties.json"

# The app builds Cypher from these names, so they are held to identifier shapes here and there.
REL_NAME = re.compile(r"^[A-Z][A-Z_]*$")
PROP_NAME = re.compile(r"^[a-z][a-z_]*$")
VALUE = re.compile(r"^[a-z][a-z_-]*$")

EdgeAllowlist = dict[str, dict[str, tuple[str, ...]]]


def load_edge_allowlist(path: Path | str = DEFAULT_EDGE_PROPERTIES_PATH) -> EdgeAllowlist:
    relationships = json.loads(Path(path).read_text(encoding="utf-8"))["relationships"]
    allowlist: EdgeAllowlist = {}
    for rel, props in relationships.items():
        if not REL_NAME.fullmatch(rel) or not isinstance(props, dict) or not props:
            raise ValueError(f"edge-properties: bad relationship entry {rel!r}")
        allowlist[rel] = {}
        for prop, values in props.items():
            if not PROP_NAME.fullmatch(prop):
                raise ValueError(f"edge-properties: bad property name {prop!r} on {rel}")
            if (
                not isinstance(values, list)
                or not values
                or not all(isinstance(value, str) and VALUE.fullmatch(value) for value in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError(f"edge-properties: {rel}.{prop} needs a list of distinct lowercase words")
            allowlist[rel][prop] = tuple(values)
    return allowlist


class EdgePropStats:
    def __init__(self) -> None:
        self._kept: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self._out_of_vocabulary: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self._non_allowlisted: Counter[str] = Counter()
        self._conflicts: Counter[str] = Counter()
        self._rels: set[str] = set()

    def note(self, rel: str, prop: str, outcome: str) -> None:
        """outcome: "kept", "out_of_vocabulary" or "non_allowlisted" (whose property name is never kept)."""
        self._rels.add(rel)
        if outcome == "kept":
            self._kept[rel][prop] += 1
        elif outcome == "out_of_vocabulary":
            self._out_of_vocabulary[rel][prop] += 1
        else:
            self._non_allowlisted[rel] += 1

    def note_conflict(self, rel: str) -> None:
        self._rels.add(rel)
        self._conflicts[rel] += 1

    def as_report(self) -> dict:
        return {
            rel: {
                "kept": dict(sorted(self._kept[rel].items())),
                "dropped_out_of_vocabulary": dict(sorted(self._out_of_vocabulary[rel].items())),
                "dropped_non_allowlisted": self._non_allowlisted[rel],
                "suppressed_conflicting_duplicates": self._conflicts[rel],
            }
            for rel in sorted(self._rels)
        }


def public_edge_props(
    rel: str,
    props: dict | None,
    allowlist: EdgeAllowlist,
    stats: EdgePropStats,
) -> dict[str, str] | None:
    """The public subset of one edge's properties, or None when nothing survives (the one "no property" form)."""
    if not props:
        return None
    allowed = allowlist.get(rel, {})
    kept: dict[str, str] = {}
    for prop, value in props.items():
        if value is None:
            continue
        if prop not in allowed:
            stats.note(rel, prop, "non_allowlisted")
        elif isinstance(value, str) and value in allowed[prop]:
            kept[prop] = value
            stats.note(rel, prop, "kept")
        else:
            stats.note(rel, prop, "out_of_vocabulary")
    return kept or None


Triple = tuple[str, str, str]


def public_props_by_triple(
    rows: list[dict],
    allowlist: EdgeAllowlist,
    stats: EdgePropStats,
) -> dict[Triple, dict[str, str] | None]:
    """Public properties per (source, rel, target) over normalized edge rows; disagreeing duplicates give None."""
    seen: dict[Triple, set[str]] = {}
    for row in rows:
        triple = (str(row["source_id"]), str(row["relationship_type"]), str(row["target_id"]))
        public = public_edge_props(triple[1], row.get("properties"), allowlist, stats)
        seen.setdefault(triple, set()).add(json.dumps(public, sort_keys=True))
    result: dict[Triple, dict[str, str] | None] = {}
    for triple, variants in seen.items():
        if len(variants) > 1:
            stats.note_conflict(triple[1])
            result[triple] = None
        else:
            result[triple] = json.loads(next(iter(variants)))
    return result
