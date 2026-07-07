#!/usr/bin/env bash
# Open Marin reconciliation refresh.
#
# Usage:
#   NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... scripts/refresh_reconciliation.sh
#
# Recommended cadence: weekly operator refresh, or after a deliberate ledger /
# verdict-feed update. Do not schedule this script here; scheduling is the
# operator's call.
#
# What it does:
#   1. Read-only enriched Organization export from Neo4j.
#   2. Rebuild the reconciliation read model with current verdicts, ledgers, and
#      --now $(date +%F) so fingerprint/review-after requeue derivation runs.
#   3. Rebuild derived identity confidence with the freshest context artifact
#      if present, warning when that context is older than 7 days.
#   4. Append a counts-only drift report under data/review/drift-reports/.
#
# It does not mutate the live graph and must not change data/identity/assertions.jsonl.
set -euo pipefail

missing=()
for var in NEO4J_URI NEO4J_USER NEO4J_PASSWORD; do
  if [[ -z "${!var:-}" ]]; then
    missing+=("$var")
  fi
done
if (( ${#missing[@]} > 0 )); then
  printf "Missing required Neo4j environment variables: %s\n" "${missing[*]}" >&2
  printf "Set NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD before running the weekly refresh.\n" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-.venv/bin/python}"
TODAY="$(date +%F)"
COMPUTED_AT="$(date -u +%FT%TZ)"

EXPORT_PATH="data/exports/existing-orgs-enriched.json"
READ_MODEL_PATH="data/review/reconciliation/read-model.jsonl"
CONFIDENCE_PATH="data/identity/confidence.jsonl"
ATTACH_LEDGER="data/identity/assertions.jsonl"
DEDUP_LEDGER="data/identity/dedup-assertions.jsonl"
VERDICTS="data/review/research-adjudicated/scale-checkpoint/verdicts-scale-wave2.jsonl"
EIN_CANDIDATES="data/review/phaseB-ein-review/vendor-ein-candidates.jsonl"
SOS_CANDIDATES="data/review/research-adjudicated/scale-checkpoint/sos-exact-read-model-candidates.jsonl"
REPORT_DIR="data/review/drift-reports"
REPORT_PATH="$REPORT_DIR/$TODAY.md"

mkdir -p "$REPORT_DIR"
BEFORE_READ_MODEL="$(mktemp "${TMPDIR:-/tmp}/openmarin-read-model-before.XXXXXX")"
if [[ -f "$READ_MODEL_PATH" ]]; then
  cp "$READ_MODEL_PATH" "$BEFORE_READ_MODEL"
else
  : > "$BEFORE_READ_MODEL"
fi

ASSERTIONS_SHA_BEFORE="$(shasum -a 256 "$ATTACH_LEDGER")"

"$PYTHON" scripts/export_existing_orgs.py \
  --enriched \
  --assertions "$ATTACH_LEDGER" \
  --out "$EXPORT_PATH"

"$PYTHON" scripts/reconciliation_read_model.py \
  --candidates "$EIN_CANDIDATES" "$SOS_CANDIDATES" \
  --ledger "$ATTACH_LEDGER" \
  --ledger "$DEDUP_LEDGER" \
  --verdicts "$VERDICTS" \
  --out "$READ_MODEL_PATH" \
  --now "$TODAY"

latest_context="$("$PYTHON" - <<'PY'
from pathlib import Path

paths = sorted(
    Path("data/review/research-adjudicated/scale-checkpoint").glob("confidence-context-*.json"),
    key=lambda p: p.stat().st_mtime,
)
print(paths[-1] if paths else "")
PY
)"

context_args=()
if [[ -n "$latest_context" ]]; then
  context_age_days="$("$PYTHON" - "$latest_context" <<'PY'
import sys
import time
from pathlib import Path

mtime = Path(sys.argv[1]).stat().st_mtime
print(int((time.time() - mtime) // 86400))
PY
)"
  if (( context_age_days > 7 )); then
    printf "WARNING: identity confidence context is %s days old: %s\n" "$context_age_days" "$latest_context" >&2
  fi
  context_args=(--context "$latest_context")
else
  printf "WARNING: no identity confidence context artifact found; rebuilding with no-collision-info context.\n" >&2
fi

"$PYTHON" scripts/identity_confidence.py \
  --verdicts "$VERDICTS" \
  --read-model "$READ_MODEL_PATH" \
  --ledger "$ATTACH_LEDGER" \
  "${context_args[@]}" \
  --out "$CONFIDENCE_PATH" \
  --computed-at "$COMPUTED_AT"

ASSERTIONS_SHA_AFTER="$(shasum -a 256 "$ATTACH_LEDGER")"
if [[ "$ASSERTIONS_SHA_BEFORE" != "$ASSERTIONS_SHA_AFTER" ]]; then
  printf "ERROR: %s changed during refresh; aborting.\n" "$ATTACH_LEDGER" >&2
  exit 1
fi

"$PYTHON" scripts/drift_report.py \
  --before-read-model "$BEFORE_READ_MODEL" \
  --after-read-model "$READ_MODEL_PATH" \
  --confidence "$CONFIDENCE_PATH" \
  --out "$REPORT_PATH" \
  --date "$TODAY"

printf "Refresh complete. Drift report appended to %s\n" "$REPORT_PATH"
