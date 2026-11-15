"""Minutes text is operator-local: the bake, the snapshot push and every export never reach the index.

Each entry point's closure — the script plus every scripts/ module it imports, transitively — must neither import
the minutes-text modules nor name the index (its path, env var or file name)."""
import ast
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
ENTRY_POINTS = (
    "bake_public_substrate.py",  # the public substrate bake
    "scan_public_substrate.py",  # the bake's privacy scan
    "refresh_weekly.py",  # stage → load → publish → snapshot push of the private data repo
    "export_live_graph.py",
    "export_graph_baseline.py",
    "export_existing_orgs.py",
    "publish_constellation.py",
)
FORBIDDEN_MODULES = {"minutes_text_index", "fetch_indexed_documents"}
FORBIDDEN_TEXT = ("minutes-text", "minutes_text", "MINUTES_TEXT", "open-marin-research")


def closure(entry: Path, root: Path) -> dict[str, Path]:
    """{module name: path} for the entry script and every local module it imports, transitively."""
    seen: dict[str, Path] = {}
    todo = [entry]
    while todo:
        path = todo.pop()
        name = path.stem if path.name != "__init__.py" else path.parent.name
        if name in seen:
            continue
        seen[name] = path
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else []
            for mod in mods:
                top = mod.split(".")[0]
                for cand in (root / f"{top}.py", root / top / "__init__.py"):
                    if cand.is_file():
                        todo.append(cand)
                if top in FORBIDDEN_MODULES:  # even if the file were missing, the import itself is the leak
                    seen.setdefault(top, root / f"{top}.py")
    return seen


def leaks(entry: Path, root: Path) -> list[str]:
    out = []
    for name, path in sorted(closure(entry, root).items()):
        if name in FORBIDDEN_MODULES:
            out.append(f"the closure of {entry.name} imports {name}")
        elif path.is_file():
            text = path.read_text(encoding="utf-8")
            out += [f"{path.name} names {t!r}" for t in FORBIDDEN_TEXT if t in text]
    return out


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_bake_snapshot_and_export_paths_never_reference_the_minutes_index(entry):
    assert (SCRIPTS / entry).is_file(), f"entry point moved: {entry}"
    assert leaks(SCRIPTS / entry, SCRIPTS) == []


def test_the_closure_reaches_through_imports(tmp_path):
    (tmp_path / "entry.py").write_text("import middle\n")
    (tmp_path / "middle.py").write_text("from deep import thing\n")
    (tmp_path / "deep.py").write_text("PATH = '~/open-marin-research/minutes-text.sqlite'\n")
    assert leaks(tmp_path / "entry.py", tmp_path) == ["deep.py names 'minutes-text'",
                                                      "deep.py names 'open-marin-research'"]
    (tmp_path / "middle.py").write_text("import minutes_text_index\n")
    assert "the closure of entry.py imports minutes_text_index" in leaks(tmp_path / "entry.py", tmp_path)


def test_the_weekly_run_reaches_the_bake():
    """The closure really covers the publish path (a vacuous pass would prove nothing)."""
    names = closure(SCRIPTS / "refresh_weekly.py", SCRIPTS)
    assert len(names) > 3, sorted(names)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
