import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.parity_core import save_case
from scripts.parity_run import run_parity


def _write_case(corpus_dir, surface, case_name, path, payload):
    save_case(
        corpus_dir,
        surface,
        case_name,
        {
            "request": {"method": "GET", "url_path": path, "params": {}},
            "http_status": 200,
            "payload": payload,
        },
    )


def test_run_parity_reports_pass_fail_and_delta_warning(tmp_path, capsys):
    corpus_dir = tmp_path / "corpus"
    _write_case(corpus_dir, "data", "passing", "/api/data/pass", {"value": 1})
    _write_case(corpus_dir, "data", "approved", "/api/data/approved", {"value": 1})
    _write_case(corpus_dir, "search", "failing", "/api/search", {"value": 1})
    _write_case(corpus_dir, "browse", "ignored", "/api/browse/person", {"value": 1})
    delta_path = tmp_path / "approved-deltas.yaml"
    delta_path.write_text(
        "- surface: data\n"
        "  case: approved\n"
        "  reason: fixture-approved drift\n"
    )
    actual_by_path = {
        "/api/data/pass": (200, {"value": 1}),
        "/api/data/approved": (200, {"value": 2}),
        "/api/search": (200, {"value": 3}),
        "/api/browse/person": (200, {"value": 999}),
    }
    calls = []

    def fetcher(base_url, request):
        calls.append((base_url, request["url_path"]))
        return actual_by_path[request["url_path"]]

    exit_code = run_parity(
        base_url="http://app.test",
        corpus_dir=corpus_dir,
        surfaces={"data", "search"},
        allow_delta=delta_path,
        fetcher=fetcher,
    )

    assert exit_code == 1
    assert calls == [
        ("http://app.test", "/api/data/approved"),
        ("http://app.test", "/api/data/pass"),
        ("http://app.test", "/api/search"),
    ]
    output = capsys.readouterr().out
    assert "WARN(delta) data/approved" in output
    assert "PASS data/passing" in output
    assert "FAIL search/failing" in output
    assert "browse/ignored" not in output


def test_run_parity_returns_zero_when_only_approved_deltas_remain(tmp_path, capsys):
    corpus_dir = tmp_path / "corpus"
    _write_case(corpus_dir, "status", "status", "/api/status", {"counts": {"edges": 1}})
    delta_path = tmp_path / "approved-deltas.yaml"
    delta_path.write_text(
        "- surface: status\n"
        "  case: status\n"
        "  reason: fixture-approved status drift\n"
    )

    def fetcher(_base_url, request):
        assert request["url_path"] == "/api/status"
        return 200, {"counts": {"edges": 2}}

    exit_code = run_parity(
        base_url="http://app.test",
        corpus_dir=corpus_dir,
        surfaces={"status"},
        allow_delta=delta_path,
        fetcher=fetcher,
    )

    assert exit_code == 0
    assert "WARN(delta) status/status" in capsys.readouterr().out
