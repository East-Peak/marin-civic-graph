"""Pre-push gate: the committed-text tripwire runs, and passes, for every commit being pushed.

Called by ops/git-hooks/pre-push with git's pre-push lines on stdin
(`<local ref> <local sha> <remote ref> <remote sha>`). The tripwire
(tests/scripts/test_extract_form700_interiors.py -k committed_diff) skips wherever its
local-only strings file is absent — every worktree — so it always runs in the main checkout,
once per pushed commit (`OPEN_MARIN_TRIPWIRE_REV`), and only one executed, passing test is
accepted: a skip, a failure, an error, a missing report or a nonzero exit blocks the push.
Install once per clone: `git config core.hooksPath ops/git-hooks`.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

TRIPWIRE = "tests/scripts/test_extract_form700_interiors.py"
_SHA = re.compile(r"[0-9a-f]{40}")


def pushed_shas(lines):
    """The local commits named by git's pre-push lines, in order, without deletes or repeats."""
    shas = []
    for line in lines:
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 4 or not _SHA.fullmatch(fields[1]):
            raise ValueError(f"unexpected pre-push line: {line!r}")
        sha = fields[1]
        if sha != "0" * 40 and sha not in shas:
            shas.append(sha)
    return shas


def verdict(junit_xml):
    """None when the report shows exactly one executed, passing test; otherwise the reason."""
    try:
        root = ET.fromstring(junit_xml)
    except ET.ParseError:
        return "tripwire report unreadable"
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return "tripwire report unreadable"
    count = {k: int(suite.get(k, 0)) for k in ("tests", "skipped", "failures", "errors")}
    if count["skipped"]:
        return "tripwire skipped (local-only strings file absent?)"
    if count["failures"]:
        return "tripwire failed"
    if count["errors"]:
        return "tripwire error"
    if count["tests"] != 1:
        return f"expected exactly 1 tripwire test, report shows {count['tests']}"
    return None


def main_checkout():
    """The main checkout: the parent of the repository's common git directory."""
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(common).parent


def main(lines, run=subprocess.run, checkout=main_checkout):
    shas = pushed_shas(lines)
    if not shas:
        return 0
    root = checkout()
    python = str(root / ".venv" / "bin" / "python")
    for sha in shas:
        with tempfile.TemporaryDirectory() as tmp:
            junit = Path(tmp) / "tripwire.xml"
            argv = [python, "-m", "pytest", TRIPWIRE, "-k", "committed_diff", "-q",
                    "-p", "no:cacheprovider", f"--junitxml={junit}"]
            env = {**os.environ, "OPEN_MARIN_TRIPWIRE_REV": sha}
            done = run(argv, cwd=root, env=env, capture_output=True, text=True)
            report = junit.read_text() if junit.is_file() else ""
            reason = verdict(report) or (f"pytest exited {done.returncode}" if done.returncode else None)
        if reason:
            print(f"pre-push: {reason} for {sha[:12]} — push refused.\n{done.stdout}", file=sys.stderr)
            return 1
    print(f"pre-push: committed-text tripwire passed for {len(shas)} commit(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin.read().splitlines()))
