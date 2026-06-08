"""C5 — registry/neo4j-schema.cypher matches the settled ontology.

The unique-constraint labels must be exactly canonical_type.ALL_TYPES plus
ValidationCheck — the canonical node types only, NOT per-Organization subtypes
(Government/Nonprofit/Business/...). And no retired graph-v1 labels (Actor,
Institution, EconomicInterestDisclosure, CaseParticipation) may appear anywhere
in the schema.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from canonical_type import ALL_TYPES, ORGANIZATION_SUBTYPES

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "registry" / "neo4j-schema.cypher"

RETIRED_LABELS = {"Actor", "Institution", "EconomicInterestDisclosure", "CaseParticipation"}


def _constraint_labels(text: str) -> set[str]:
    return set(re.findall(r"CREATE CONSTRAINT \w+ IF NOT EXISTS FOR \(n:(\w+)\)", text))


def _all_referenced_labels(text: str) -> set[str]:
    labels: set[str] = set()
    for group in re.findall(r"FOR \(n:([\w|]+)\)", text):
        labels.update(group.split("|"))
    return labels


def test_unique_constraints_match_all_types_plus_validationcheck():
    labels = _constraint_labels(SCHEMA.read_text())
    assert labels == set(ALL_TYPES) | {"ValidationCheck"}


def test_constraints_are_not_per_organization_subtype():
    labels = _constraint_labels(SCHEMA.read_text())
    assert not (labels & ORGANIZATION_SUBTYPES), (
        "constraints must be on canonical Organization, not its subtypes"
    )


def test_schema_has_no_retired_labels():
    leaked = _all_referenced_labels(SCHEMA.read_text()) & RETIRED_LABELS
    assert not leaked, f"retired graph-v1 labels present in schema: {sorted(leaked)}"
