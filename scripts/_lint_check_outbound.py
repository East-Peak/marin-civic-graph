"""Forbid direct OpenAI/Anthropic imports outside outbound_policy.py.

Run as part of CI: python scripts/_lint_check_outbound.py
Exits 1 with a list of offenders if any are found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ALLOWED = {
    "scripts/outbound_policy.py",
    "scripts/build_embeddings.py",   # imports openai SDK; must use the policy
    "scripts/name_clusters.py",      # imports anthropic SDK; must use the policy
}
PATTERN = re.compile(r"^\s*(?:import|from)\s+(openai|anthropic)\b", re.MULTILINE)


def main() -> int:
    offenders: list[tuple[Path, str]] = []
    for py in REPO.glob("scripts/**/*.py"):
        rel = py.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        text = py.read_text(encoding="utf-8")
        for m in PATTERN.finditer(text):
            offenders.append((py, m.group(0).strip()))
    if offenders:
        print("FAIL: direct vendor imports outside policy module:")
        for path, line in offenders:
            print(f"  {path.relative_to(REPO)}: {line}")
        return 1
    print("OK: no out-of-policy vendor imports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
