"""Contract tests for scripts/refresh_reconciliation.sh."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "refresh_reconciliation.sh"


def test_refresh_reconciliation_script_documents_cadence_and_operator_contract():
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "Usage:" in text
    assert "weekly" in text.lower()
    assert "Do not schedule" in text
    assert "NEO4J_URI" in text
    assert "NEO4J_USER" in text
    assert "NEO4J_PASSWORD" in text
    assert "export_existing_orgs.py" in text
    assert "--enriched" in text
    assert "--assertions" in text
    assert "reconciliation_read_model.py" in text
    assert "data/review/phaseB-ein-review/vendor-ein-candidates.jsonl" in text
    assert "data/review/research-adjudicated/scale-checkpoint/sos-exact-read-model-candidates.jsonl" in text
    assert "data/review/research-adjudicated/scale-checkpoint/verdicts-scale-wave2.jsonl" in text
    assert "--now" in text
    assert "date +%F" in text
    assert "data/identity/assertions.jsonl" in text
    assert "data/identity/dedup-assertions.jsonl" in text
    assert "identity_confidence.py" in text
    assert "confidence-context-*.json" in text
    assert "drift_report.py" in text
    assert "data/review/drift-reports" in text


def test_refresh_reconciliation_fails_before_export_when_neo4j_env_missing(tmp_path):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("NEO4J_")
    }
    env["TMPDIR"] = str(tmp_path)

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Missing required Neo4j environment variables" in result.stderr
    assert "NEO4J_URI" in result.stderr
    assert "NEO4J_USER" in result.stderr
    assert "NEO4J_PASSWORD" in result.stderr
    assert not list(tmp_path.iterdir())
