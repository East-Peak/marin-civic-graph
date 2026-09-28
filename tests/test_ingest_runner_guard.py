"""ingest.py judges each capture against its floors before writing it."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ingest  # noqa: E402
from ingest_guard import RunLedger  # noqa: E402

TODAY = date(2026, 9, 28)


def _fake_adapter(meetings, out_path):
    class Fake:
        def __init__(self, source_config, root):
            pass

        def capture(self):
            return {"meeting_count": len(meetings), "meetings": meetings, "errors": []}

        def extracted_path(self):
            return out_path

    return Fake


def _run(tmp_path, meetings, source_config=None):
    out = tmp_path / "extracted" / "src" / "2026-09-28.json"
    ledger = RunLedger(tmp_path / "ingest-runs" / "ledger.jsonl")
    cfg = {"id": "src", "adapter": "fake", **(source_config or {})}
    result, verdict = ingest.run_source(
        cfg, tmp_path, ledger=ledger, today=TODAY, adapter_cls=_fake_adapter(meetings, out)
    )
    return out, ledger, result, verdict


def test_empty_capture_writes_nothing_and_is_ledgered_as_failed(tmp_path):
    out, ledger, _, verdict = _run(tmp_path, [])
    assert not verdict.ok
    assert not out.exists()
    entry = json.loads(ledger.path.read_text().splitlines()[-1])
    assert entry["ok"] is False and entry["rows"] == 0


def test_good_capture_writes_and_becomes_the_new_baseline(tmp_path):
    out, ledger, _, verdict = _run(tmp_path, [{"date": "2026-09-22"}] * 10)
    assert verdict.ok, verdict.reasons
    assert json.loads(out.read_text())["meeting_count"] == 10
    assert ledger.last_good("src")["rows"] == 10


def test_sharp_drop_after_a_good_run_keeps_the_good_output(tmp_path):
    out, ledger, _, _ = _run(tmp_path, [{"date": "2026-09-22"}] * 100)
    good = out.read_text()
    out2, _, _, verdict = _run(tmp_path, [{"date": "2026-09-22"}] * 5)
    assert out2 == out and not verdict.ok
    assert out.read_text() == good


def test_registry_floors_are_honored(tmp_path):
    _run(tmp_path, [{"date": "2026-09-22"}] * 20)
    _, _, _, verdict = _run(tmp_path, [{"date": "2026-09-22"}] * 12, {"floors": {"min_ratio": 0.5}})
    assert verdict.ok, verdict.reasons


def test_main_exits_nonzero_when_any_source_fails(tmp_path, monkeypatch):
    registry = tmp_path / "reg.yaml"
    registry.write_text("sources:\n  - {id: a, adapter: fake, url: u, schedule: weekly}\n")
    monkeypatch.setattr(ingest, "ROOT", tmp_path)
    monkeypatch.setattr(
        ingest, "run_source",
        lambda cfg, root, **kw: ({"meeting_count": 0, "meetings": [], "errors": []},
                                 ingest.Verdict(ok=False, reasons=["pull returned 0 rows"])),
    )
    assert ingest.main(["--all", "--registry", str(registry)]) == 1


def test_accepted_capture_is_written_with_canonical_meeting_ids(tmp_path):
    from meeting_identity import MeetingIdentityMap

    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    out = tmp_path / "extracted" / "src" / "w1.json"
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    week1 = [{"meeting_id": "m-hash", "date": "2026-09-22", "title": "Council"}] * 3
    ingest.run_source({"id": "src", "adapter": "f"}, tmp_path, ledger=ledger, today=TODAY,
                      adapter_cls=_fake_adapter(week1, out), identity=idmap)
    week2 = [{"meeting_id": "m-clip-99", "date": "2026-09-22", "title": "Council"}] * 3
    _, verdict = ingest.run_source({"id": "src", "adapter": "f"}, tmp_path, ledger=ledger, today=TODAY,
                                   adapter_cls=_fake_adapter(week2, out), identity=idmap)
    assert verdict.ok
    assert {m["meeting_id"] for m in json.loads(out.read_text())["meetings"]} == {"m-hash"}
    assert (tmp_path / "ids.json").exists()


def test_rejected_capture_does_not_touch_the_identity_map(tmp_path):
    from meeting_identity import MeetingIdentityMap

    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    out = tmp_path / "extracted" / "src" / "w1.json"
    ingest.run_source({"id": "src", "adapter": "f"}, tmp_path, ledger=RunLedger(tmp_path / "l.jsonl"),
                      today=TODAY, adapter_cls=_fake_adapter([], out), identity=idmap)
    assert not (tmp_path / "ids.json").exists()


def test_adapter_errors_reject_an_otherwise_full_capture(tmp_path):
    class Partial:
        def __init__(self, source_config, root):
            pass

        def capture(self):
            meetings = [{"date": "2026-09-22"}] * 10
            return {"meeting_count": 10, "meetings": meetings,
                    "errors": ["Failed to fetch https://example.gov/meetings/m1/: timeout"]}

        def extracted_path(self):
            return tmp_path / "out.json"

    ledger = RunLedger(tmp_path / "ledger.jsonl")
    _, verdict = ingest.run_source({"id": "src", "adapter": "f"}, tmp_path, ledger=ledger,
                                   today=TODAY, adapter_cls=Partial)
    assert not verdict.ok
    assert not (tmp_path / "out.json").exists()
    assert ledger.last_good("src") is None
