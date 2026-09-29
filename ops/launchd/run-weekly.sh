#!/bin/bash
# What the weekly LaunchAgent runs: rotate the logs, source the operator-local env file,
# then `refresh_weekly.py weekly` (stage, load, publish, snapshot, heartbeat) from the repo,
# passing its exit code back to launchd.
#
# weekly.env (gitignored; see weekly.env.example) holds secrets: the heartbeat URL and the
# graph's credentials. It is sourced only when no one but its owner can read or write it
# (chmod 600), and its contents are never echoed. A missing or exposed env file is reported,
# and the run still starts, without a heartbeat or credentials, so it stops at its load and
# the external monitor's missed-heartbeat email points here.
#
# Test seams (defaults in brackets): OPEN_MARIN_ENV_FILE [ops/launchd/weekly.env],
# OPEN_MARIN_LOG_DIR [data/ingest-runs/launchd], OPEN_MARIN_PYTHON [.venv/bin/python],
# OPEN_MARIN_LOG_MAX_BYTES [5 MiB].
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
env_file="${OPEN_MARIN_ENV_FILE:-$here/weekly.env}"
log_dir="${OPEN_MARIN_LOG_DIR:-$repo/data/ingest-runs/launchd}"
python="${OPEN_MARIN_PYTHON:-$repo/.venv/bin/python}"
max_bytes="${OPEN_MARIN_LOG_MAX_BYTES:-5242880}"
keep=3  # log.1 .. log.3; the oldest falls off

rotate() {  # <log>: once it reaches max_bytes, shift log -> log.1 -> ... -> log.$keep
  local log="$1" i
  [ -f "$log" ] && [ "$(wc -c <"$log")" -ge "$max_bytes" ] || return 0
  for ((i = keep - 1; i >= 1; i--)); do
    [ -f "$log.$i" ] && mv -f "$log.$i" "$log.$((i + 1))"
  done
  mv -f "$log" "$log.1"
}

mkdir -p "$log_dir"
for log in "$log_dir"/*.log; do rotate "$log"; done
exec >>"$log_dir/weekly.log" 2>&1
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) weekly run starting"

private() {  # no permission bits for group or other: -rw------- or stricter
  local mode
  mode="$(ls -ld "$1" | cut -c5-10)"
  [ "$mode" = "------" ]
}

if [ ! -f "$env_file" ]; then
  echo "WARNING: $env_file is missing (copy weekly.env.example); running stage without it, so no heartbeat."
elif ! private "$env_file"; then
  echo "WARNING: $env_file is readable or writable by others; not sourcing it. Fix: chmod 600 $env_file"
else
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
fi

cd "$repo" || exit 1
"$python" scripts/refresh_weekly.py weekly
status=$?
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) weekly run exited $status"
exit "$status"
