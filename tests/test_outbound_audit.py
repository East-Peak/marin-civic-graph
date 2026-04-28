"""Tests for outbound audit logging."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from outbound_policy import audit_log


def test_audit_writes_jsonl_record(tmp_path, monkeypatch):
    log_file = tmp_path / "outbound_audit.jsonl"
    monkeypatch.setenv("OUTBOUND_AUDIT_PATH", str(log_file))
    audit_log(
        vendor="openai",
        node_id="person-kate-colin",
        node_type="Person",
        neighbor_ids_included=["decision-1", "decision-2"],
        neighbor_ids_dropped=["x-criminal-1"],
        prompt_hash="abc123",
    )
    line = log_file.read_text().strip()
    record = json.loads(line)
    assert record["vendor"] == "openai"
    assert record["node_id"] == "person-kate-colin"
    assert record["neighbor_ids_dropped"] == ["x-criminal-1"]
    assert "timestamp" in record
