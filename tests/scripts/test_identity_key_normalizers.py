"""Goal 0 Unit 1 — byte-copied identity-key normalizers (stdlib-only).

The four key normalizers move into one home (`scripts/identity_key_normalizers.py`)
verbatim from their originals — `_normalize_ein`/`_normalize_uei` (org_resolution),
`_normalize_sos_id` (enrich_casos_keys), `_normalize_committee_id` (enrich_fppc_keys)
— so the IdentityKey registry can reference them without importing those modules
(which would create a registry -> lane -> org_resolution import cycle).

Parity battery (from the goal doc, Decision 4): output must match the BASE_SHA
callables across these inputs. The module must import stdlib ONLY.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import identity_key_normalizers as kn  # noqa: E402

_MODULE = Path(__file__).resolve().parents[2] / "scripts" / "identity_key_normalizers.py"

EIN = [(None, None), ("", None), ("---", None), ("94-3007979", "943007979"), ("JZ9FLAVMPEB9", "99")]
UEI = [(None, None), ("", None), ("---", None), ("jz9flavmpeb9", "JZ9FLAVMPEB9"),
       (" jz9-flavmpeb9 ", "JZ9FLAVMPEB9")]
SOS = [(None, None), ("", None), ("   ", None), ("C", None), ("1819837", "1819837"),
       ("0257045", "0257045"), ("202118310837", "202118310837"), ("C0254285", "0254285"),
       ("c2968448", "2968448"), ("B20260076487", "B20260076487"), ("C123-456", "123456")]
COMMITTEE = [(None, None), ("", None), ("Pending", None), ("Unknown", None), ("1352318", "1352318"),
             (1419944, "1419944"), ("123456789", "123456789"), ("1234567890", None), ("abc123", None),
             ("C1352318", None), ("1352318.0", None)]


@pytest.mark.parametrize("raw,expected", EIN)
def test_normalize_ein(raw, expected):
    assert kn._normalize_ein(raw) == expected


@pytest.mark.parametrize("raw,expected", UEI)
def test_normalize_uei(raw, expected):
    assert kn._normalize_uei(raw) == expected


@pytest.mark.parametrize("raw,expected", SOS)
def test_normalize_sos_id(raw, expected):
    assert kn._normalize_sos_id(raw) == expected


@pytest.mark.parametrize("raw,expected", COMMITTEE)
def test_normalize_committee_id(raw, expected):
    assert kn._normalize_committee_id(raw) == expected


def test_stdlib_only_imports():
    """The normalizer module must import stdlib only — never a project-local
    module (that is what keeps the registry import DAG acyclic)."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    for mod in imported:
        top = mod.split(".")[0]
        assert top in {"re", "typing", "__future__", ""}, f"unexpected non-stdlib import: {mod!r}"
