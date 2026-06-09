"""Python port of app/src/lib/canonical-type.ts. Single source of truth for
node-type resolution in the pipeline. MUST stay in sync with the TS version.

The mechanical contract (the 21 graph types, their id-prefixes, and the
Organization subtypes) is DERIVED from registry/node-types.json — the one
source of truth (spec §4.6). The TS mirror is codegen'd from the same file
(app/src/lib/node-types.generated.ts). Do not hand-edit ALL_TYPES /
TYPE_BY_ID_PREFIX / ORGANIZATION_SUBTYPES — edit the registry.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent / "registry" / "node-types.json"
)


def load_registry(path: Path | str | None = None) -> dict:
    """Load + validate registry/node-types.json (the mechanical type contract).

    Every graph node type MUST declare both required boolean flags
    (`searchable`, `outbound_eligible`) — a missing flag is REJECTED with no
    silent default. Sidecar / retired / support labels must stay disjoint from
    the graph node types (no sweeping non-graph names into ALL_TYPES).
    """
    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    with registry_path.open(encoding="utf-8") as f:
        registry = json.load(f)

    graph_types = registry["graph_node_types"]
    for type_name, spec in graph_types.items():
        for flag in ("searchable", "outbound_eligible"):
            if flag not in spec:
                raise ValueError(
                    f"registry: graph type {type_name!r} missing required "
                    f"boolean flag {flag!r}"
                )
            if not isinstance(spec[flag], bool):
                raise ValueError(
                    f"registry: graph type {type_name!r} flag {flag!r} must be "
                    f"a boolean, got {type(spec[flag]).__name__}"
                )

    graph = set(graph_types)
    for section in ("sidecar_artifacts", "retired_labels", "support_labels"):
        overlap = graph & set(registry.get(section, []))
        if overlap:
            raise ValueError(
                f"registry: {section} overlaps graph_node_types: {sorted(overlap)}"
            )

    return registry


_REGISTRY = load_registry()

ALL_TYPES = list(_REGISTRY["graph_node_types"].keys())

ORGANIZATION_SUBTYPES = set(_REGISTRY["organization_subtypes"])

TYPE_BY_ID_PREFIX = dict(_REGISTRY["id_prefixes"])


def canonical_type(labels: list[str], node_id: str) -> str | None:
    """Resolve a node's canonical NodeType. Mirrors canonicalType() in TS."""
    for prefix, t in TYPE_BY_ID_PREFIX.items():
        if node_id.startswith(prefix):
            return t
    base = next((lbl for lbl in labels if lbl in ALL_TYPES), None)
    if base:
        return base
    if any(lbl in ORGANIZATION_SUBTYPES for lbl in labels):
        return "Organization"
    return None
