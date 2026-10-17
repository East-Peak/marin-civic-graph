"""Pre-push gate: the committed-text tripwire runs, and passes, for every commit being pushed.

Called by ops/git-hooks/pre-push with git's pre-push lines on stdin
(`<local ref> <local sha> <remote ref> <remote sha>`). The tripwire
(tests/scripts/test_extract_form700_interiors.py -k committed_diff) skips wherever its
local-only strings file is absent — every worktree — so it always runs in the main checkout,
once for every commit the push makes newly reachable (`OPEN_MARIN_TRIPWIRE_REV`), so a leak
added and later removed is still caught. Only a report of the one tripwire testcase, executed,
passing and naming the commit it scanned (`tripwire_rev`), is accepted; anything else — a skip,
a failure, an error, an older scanner, a missing report, a nonzero exit — blocks the push.
Install once per clone, with the main checkout's ABSOLUTE path so worktrees on older revisions
cannot miss the hook: `git config core.hooksPath "$PWD/ops/git-hooks"` (run in the main checkout).
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
TESTCASE = "test_no_forbidden_string_or_shape_in_committed_diff_or_evidence"
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


def new_commits(tips, git):
    """Every commit the push makes newly reachable (not on any known remote ref), oldest first."""
    if not tips:
        return []
    return git("rev-list", "--reverse", *tips, "--not", "--remotes").split()


def verdict(junit_xml, sha):
    """None when the report holds exactly the tripwire testcase, executed and passing on `sha`."""
    try:
        root = ET.fromstring(junit_xml)
    except ET.ParseError:
        return "tripwire report unreadable"
    cases = root.findall(".//testcase")
    if len(cases) != 1 or cases[0].get("name") != TESTCASE:
        return f"expected exactly 1 tripwire testcase, report shows {[c.get('name') for c in cases]}"
    for outcome in ("skipped", "failure", "error"):
        if cases[0].find(outcome) is not None:
            return f"tripwire {outcome}"
    scanned = next((p.get("value") for p in cases[0].iter("property") if p.get("name") == "tripwire_rev"), None)
    if scanned != sha:
        return f"tripwire scanned {(scanned or 'none')[:12]}, not the pushed commit"
    return None


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def main_checkout():
    """The main checkout: the parent of the repository's common git directory."""
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(common).parent


def main(lines, run=subprocess.run, checkout=main_checkout, commits=lambda tips: new_commits(tips, _git)):
    try:
        shas = commits(pushed_shas(lines))
    except Exception as exc:  # any doubt about what is being pushed refuses the push
        print(f"pre-push: cannot list the pushed commits ({exc}) — push refused.", file=sys.stderr)
        return 1
    if not shas:
        return 0
    root = checkout()
    python = str(root / ".venv" / "bin" / "python")
    for sha in shas:
        with tempfile.TemporaryDirectory() as tmp:
            junit = Path(tmp) / "tripwire.xml"
            argv = [python, "-m", "pytest", TRIPWIRE, "-k", "committed_diff", "-q",
                    "-p", "no:cacheprovider", "-o", "junit_family=xunit1", f"--junitxml={junit}"]
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            env["OPEN_MARIN_TRIPWIRE_REV"] = sha
            done = run(argv, cwd=root, env=env, capture_output=True, text=True)
            report = junit.read_text() if junit.is_file() else ""
            reason = verdict(report, sha) or (f"pytest exited {done.returncode}" if done.returncode else None)
        if reason:
            print(f"pre-push: {reason} for {sha[:12]} — push refused.\n{done.stdout}", file=sys.stderr)
            return 1
    print(f"pre-push: committed-text tripwire passed for {len(shas)} commit(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin.read().splitlines()))
