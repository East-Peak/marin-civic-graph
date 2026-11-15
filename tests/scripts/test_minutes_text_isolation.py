"""The operator-local research indexes stay off every publication path: the bake, the snapshot push and every export
never reach the minutes text index or the actor index.

Each entry point's closure — the script plus every scripts/ module it imports, transitively — must neither import
the research modules nor name their files: the minutes text index; the actor index, the actor registry, the reviewed
case roles and the copied private inputs under ~/open-marin-research/inputs/. Shared upstream inputs (the public
substrate, the raw returns) are permitted."""
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
FORBIDDEN_MODULES = {"minutes_text_index", "fetch_indexed_documents", "actor_index"}
FORBIDDEN_TEXT = ("minutes-text", "minutes_text", "MINUTES_TEXT", "open-marin-research",
                  "actor_index", "actors.sqlite", "ACTORS_DB_PATH", "actors.yaml", "case-roles",
                  "board-ledger.jsonl", "inputs-manifest.json", "identity-candidates")


def closure(entry: Path, root: Path) -> dict[str, Path]:
    """{module name: path} for the entry script and every local module it reaches, transitively: absolute and
    relative imports, and scripts it launches by path (a string literal naming `<name>.py` or `<name>.sh` that
    exists under root, as the weekly run launches the bake and the exports)."""
    seen: dict[str, Path] = {}
    todo = [entry]
    while todo:
        path = todo.pop()
        name = path.parent.name if path.name == "__init__.py" else \
            path.relative_to(root).with_suffix("").as_posix().replace("/", ".")
        if name in seen:
            continue
        seen[name] = path
        if path.suffix != ".py":
            continue  # a shell script: its text is scanned, not parsed
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                mods = [(a.name, root) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [(node.module, root)]
            elif isinstance(node, ast.ImportFrom):  # relative: from the importing file's package
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                mods = [(node.module, base)] if node.module else [(a.name, base) for a in node.names]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                    node.value.endswith((".py", ".sh")) and "/" not in node.value.removeprefix("scripts/"):
                target = root / node.value.removeprefix("scripts/")
                if target.is_file():
                    todo.append(target)
                mods = []
            else:
                mods = []
            for mod, base in mods:
                top = mod.split(".")[0]
                for cand in (base / f"{top}.py", base / top / "__init__.py"):
                    if cand.is_file():
                        todo.append(cand)
                if base == root and top in FORBIDDEN_MODULES:  # the import itself is the leak
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
def test_bake_snapshot_and_export_paths_never_reference_the_research_indexes(entry):
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


def test_the_closure_follows_relative_imports_and_launched_scripts(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "entry.py").write_text("import pkg\nSTEP = ['python', 'scripts/launched.py']\n")
    (tmp_path / "pkg" / "__init__.py").write_text("from .inner import x\n")
    (tmp_path / "pkg" / "inner.py").write_text("P = 'MINUTES_TEXT_DB_PATH'\n")
    (tmp_path / "launched.py").write_text("P = 'open-marin-research'\n")
    assert leaks(tmp_path / "entry.py", tmp_path) == ["launched.py names 'open-marin-research'",
                                                      "inner.py names 'MINUTES_TEXT'"]


def test_the_actor_index_and_its_private_inputs_are_named_leaks(tmp_path):
    (tmp_path / "entry.py").write_text("import helper\n")
    (tmp_path / "helper.py").write_text("REG = 'actors.yaml'\nROLES = 'case-roles.yaml'\n")
    assert leaks(tmp_path / "entry.py", tmp_path) == ["helper.py names 'actors.yaml'", "helper.py names 'case-roles'"]
    (tmp_path / "helper.py").write_text("import actor_index\n")
    assert "the closure of entry.py imports actor_index" in leaks(tmp_path / "entry.py", tmp_path)
    (tmp_path / "helper.py").write_text("DB = os.environ.get('ACTORS_DB_PATH')\n")
    assert leaks(tmp_path / "entry.py", tmp_path) == ["helper.py names 'ACTORS_DB_PATH'"]


def test_the_weekly_run_reaches_the_bake_exports_and_adapters():
    """The closure really covers the publish path (a vacuous pass would prove nothing)."""
    names = closure(SCRIPTS / "refresh_weekly.py", SCRIPTS)
    for needed in ("bake_public_substrate", "export_live_graph", "ingest", "adapters.granicus",
                   "refresh_reconciliation"):
        assert needed in names, sorted(names)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
