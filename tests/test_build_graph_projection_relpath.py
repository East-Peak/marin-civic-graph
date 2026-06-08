"""Regression test for build_graph_projection report-path computation.

The normalized data lives in a *sibling* private repo (`data/normalized` is a
gitignored symlink to `../../marin-civic-graph-data/normalized`).  Resolving a
bundle path therefore lands OUTSIDE the code-repo ROOT, and the old
`bundle_path.relative_to(ROOT)` raised ValueError, aborting the projection
before any nodes/edges were written.  `relpath_for_report` must be robust to
that: identical to `relative_to` when the path is inside ROOT, and a valid
non-throwing relative path when it is outside.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_graph_projection import relpath_for_report


def test_relpath_inside_root_matches_relative_to():
    root = Path("/repo")
    p = Path("/repo/data/normalized/x.json")
    # Behavior-preserving: same string Path.relative_to would have produced.
    assert relpath_for_report(p, root) == str(p.relative_to(root))


def test_relpath_outside_root_does_not_raise():
    root = Path("/repo")
    p = Path("/elsewhere/marin-civic-graph-data/normalized/x.json")
    result = relpath_for_report(p, root)
    assert isinstance(result, str)
    assert result.endswith("normalized/x.json")
