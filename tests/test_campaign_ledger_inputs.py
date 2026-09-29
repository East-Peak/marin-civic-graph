"""Inputs and outputs of the campaign-finance ledger: the hashed input manifest and the output-root guard."""
import hashlib
import sys
import zipfile
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from campaign_ledger import InputError, UnsafeOutputError, inventory_inputs, resolve_output_root

HTML_PAGE = b"\r\n\r\n<!DOCTYPE html PUBLIC \"-//W3C//DTD XHTML 1.0 Transitional//EN\">\n<html></html>\n"


def _workbook_zip(path: Path, sheets=("A-Contributions", "E-Expenditure", "Summary")) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.active.title = sheets[0]
    for name in sheets[1:]:
        wb.create_sheet(name)
    xlsx = path.with_suffix(".xlsx")
    wb.save(xlsx)
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(xlsx, "efile_newest_TEST.xlsx")
    xlsx.unlink()
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _capture(root: Path, years=("2022", "2023")) -> Path:
    capture = root / "src" / "2026-04-14"
    for year in years:
        _workbook_zip(capture / f"{year}.zip")
    return capture


class TestInventoryInputs:
    def test_lists_every_workbook_with_its_hash(self, tmp_path):
        capture = _capture(tmp_path)
        entries = inventory_inputs(tmp_path, "src", "2026-04-14", years=["2022", "2023"], unavailable=[])
        assert [e["path"] for e in entries] == ["src/2026-04-14/2022.zip", "src/2026-04-14/2023.zip"]
        assert entries[0]["sha256"] == _sha(capture / "2022.zip")
        assert entries[0]["bytes"] == (capture / "2022.zip").stat().st_size
        assert {e["coverage"] for e in entries} == {"workbook"}

    def test_pinned_html_page_is_unavailable_coverage_not_an_empty_year(self, tmp_path):
        capture = _capture(tmp_path, years=("2022",))
        (capture / "2021.zip").write_bytes(HTML_PAGE)
        pin = {"file": "2021.zip", "sha256": _sha(capture / "2021.zip")}
        entries = inventory_inputs(tmp_path, "src", "2026-04-14", years=["2021", "2022"], unavailable=[pin])
        by_year = {e["year"]: e for e in entries}
        assert by_year["2021"]["coverage"] == "unavailable"
        assert by_year["2021"]["reason"] == "html_page_not_export"
        assert by_year["2021"]["sha256"] == pin["sha256"]
        assert by_year["2022"]["coverage"] == "workbook"

    def test_unpinned_html_page_fails(self, tmp_path):
        capture = _capture(tmp_path, years=("2022",))
        (capture / "2023.zip").write_bytes(HTML_PAGE)
        with pytest.raises(InputError, match="2023.zip"):
            inventory_inputs(tmp_path, "src", "2026-04-14", years=["2022", "2023"], unavailable=[])

    def test_pinned_file_whose_hash_changed_fails(self, tmp_path):
        capture = _capture(tmp_path, years=("2022",))
        (capture / "2021.zip").write_bytes(HTML_PAGE + b"changed")
        pin = {"file": "2021.zip", "sha256": hashlib.sha256(HTML_PAGE).hexdigest()}
        with pytest.raises(InputError, match="2021.zip"):
            inventory_inputs(tmp_path, "src", "2026-04-14", years=["2021", "2022"], unavailable=[pin])

    def test_corrupt_zip_fails(self, tmp_path):
        capture = _capture(tmp_path, years=("2022",))
        (capture / "2023.zip").write_bytes(b"PK\x03\x04 truncated")
        with pytest.raises(InputError, match="2023.zip"):
            inventory_inputs(tmp_path, "src", "2026-04-14", years=["2022", "2023"], unavailable=[])

    def test_workbook_missing_a_required_sheet_fails(self, tmp_path):
        capture = _capture(tmp_path, years=("2022",))
        _workbook_zip(capture / "2023.zip", sheets=("A-Contributions", "Summary"))
        with pytest.raises(InputError, match="E-Expenditure"):
            inventory_inputs(tmp_path, "src", "2026-04-14", years=["2022", "2023"], unavailable=[])

    def test_missing_year_fails(self, tmp_path):
        _capture(tmp_path, years=("2022",))
        with pytest.raises(InputError, match="2023.zip"):
            inventory_inputs(tmp_path, "src", "2026-04-14", years=["2022", "2023"], unavailable=[])

    def test_unexpected_extra_file_fails(self, tmp_path):
        capture = _capture(tmp_path, years=("2022",))
        _workbook_zip(capture / "2030.zip")
        with pytest.raises(InputError, match="2030.zip"):
            inventory_inputs(tmp_path, "src", "2026-04-14", years=["2022"], unavailable=[])


class TestResolveOutputRoot:
    @pytest.fixture
    def repo(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        data_repo = tmp_path / "repo-data"
        (data_repo / ".git").mkdir(parents=True)
        (data_repo / "normalized").mkdir()
        (repo / "data").mkdir()
        (repo / "data" / "normalized").symlink_to(data_repo / "normalized")
        return repo

    def test_accepts_an_empty_dir_outside_both_repos(self, tmp_path, repo):
        out = tmp_path / "staging" / "run-1"
        assert resolve_output_root(out, repo) == out.resolve()

    @pytest.mark.parametrize("rel", ["data/normalized/cf", "data/exports/x", "data/ingest-runs/x", "scratch"])
    def test_refuses_anywhere_inside_the_repo(self, repo, rel):
        with pytest.raises(UnsafeOutputError):
            resolve_output_root(repo / rel, repo)

    def test_refuses_the_private_data_repo_reached_through_the_symlink(self, tmp_path, repo):
        link = tmp_path / "innocent"
        link.symlink_to(repo / "data" / "normalized")
        with pytest.raises(UnsafeOutputError, match="repo-data"):
            resolve_output_root(link / "cf", repo)

    def test_refuses_the_private_data_repo_even_when_not_a_git_checkout(self, tmp_path, repo):
        other = tmp_path / "repo-data"
        import shutil
        shutil.rmtree(other / ".git")
        with pytest.raises(UnsafeOutputError):
            resolve_output_root(other / "normalized" / "cf", repo)

    def test_refuses_a_non_empty_dir(self, tmp_path, repo):
        out = tmp_path / "staging"
        out.mkdir()
        (out / "old.json").write_text("{}")
        with pytest.raises(UnsafeOutputError, match="not empty"):
            resolve_output_root(out, repo)


class TestCli:
    """normalize_campaign_finance.main: explicit roots, pinned coverage, no load path."""

    def _registry(self, tmp_path, pins=()):
        import yaml
        reg = tmp_path / "netfile-sources.yaml"
        reg.write_text(yaml.safe_dump({"sources": [{
            "id": "src", "jurisdiction_id": "place-test", "institution_id": "org-test",
            "backfill_from": "2021-01-01",
            "unavailable_inputs": [{"capture": "2026-04-14", **p} for p in pins],
        }]}))
        return reg

    def test_writes_the_input_manifest_under_the_output_root(self, tmp_path):
        import json
        from normalize_campaign_finance import main
        capture = _capture(tmp_path / "raw", years=("2022", "2023", "2024", "2025", "2026"))
        (capture / "2021.zip").write_bytes(HTML_PAGE)
        reg = self._registry(tmp_path, pins=[{"file": "2021.zip", "sha256": _sha(capture / "2021.zip")}])
        out = tmp_path / "staging"
        assert main(["--all", "--registry", str(reg), "--input-root", str(tmp_path / "raw"),
                     "--output-root", str(out)]) == 0
        manifest = json.loads((out / "src" / "manifest.json").read_text())
        assert manifest["capture_id"] == "src__2026-04-14"
        assert [i["coverage"] for i in manifest["inputs"]] == ["unavailable"] + ["workbook"] * 5
        assert "normalized_at" not in (out / "src" / "manifest.json").read_text()
        assert "started_at" in json.loads((out / "run-manifest.json").read_text())

    def test_unreadable_input_fails_without_writing(self, tmp_path, capsys):
        from normalize_campaign_finance import main
        capture = _capture(tmp_path / "raw", years=("2022", "2023", "2024", "2025", "2026"))
        (capture / "2021.zip").write_bytes(HTML_PAGE)
        out = tmp_path / "staging"
        assert main(["--all", "--registry", str(self._registry(tmp_path)), "--input-root",
                     str(tmp_path / "raw"), "--output-root", str(out)]) == 1
        assert "2021.zip" in capsys.readouterr().err
        assert not (out / "src").exists()

    def test_output_root_is_required(self, tmp_path):
        from normalize_campaign_finance import main
        with pytest.raises(SystemExit):
            main(["--all"])

    def test_refuses_the_repo_normalized_dir(self, tmp_path, capsys):
        from normalize_campaign_finance import ROOT, main
        assert main(["--all", "--output-root", str(ROOT / "data" / "normalized" / "x")]) == 1
        assert "refusing" in capsys.readouterr().err

    def test_there_is_no_load_flag(self, tmp_path):
        from normalize_campaign_finance import main
        with pytest.raises(SystemExit):
            main(["--all", "--output-root", str(tmp_path / "o"), "--load"])
