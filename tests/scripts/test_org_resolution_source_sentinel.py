"""Source-hash sentinel for the reconciliation resolver.

`org_resolution.py` is intentionally consumed as a stable shared resolver during
the reconciliation refactor. If an intentional edit is required, review the
never-edit discipline in the tranche spec, make the resolver change deliberately,
then rotate EXPECTED_SHA256 to the new file-byte hash in the same commit.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED_SHA256 = "36d095386a022e3ec33bbf491313ac8553d7c627e170a09b762bbf5c8f5ec15c"


def test_org_resolution_source_hash_is_pinned():
    path = Path(__file__).resolve().parents[2] / "scripts" / "org_resolution.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == EXPECTED_SHA256
