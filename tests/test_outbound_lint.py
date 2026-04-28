"""Smoke test: the outbound-policy lint script runs and reports cleanly today."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_lint_script_passes_on_current_repo():
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "_lint_check_outbound.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
