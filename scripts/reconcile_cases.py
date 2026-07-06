"""Deprecated shim for reconcile_cases.py; remove after routes migrate (R3)."""
from __future__ import annotations

from reconciliation_overlay import *  # noqa: F401,F403
from reconciliation_overlay import main


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
