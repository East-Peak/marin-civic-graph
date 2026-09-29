#!/bin/bash
# Install (or, with --uninstall, remove) the weekly Open Marin LaunchAgent. The OPERATOR runs this.
#
#   ops/launchd/install.sh              # verify, lint, copy to ~/Library/LaunchAgents, bootstrap
#   ops/launchd/install.sh --uninstall  # bootout and remove the installed copy (weekly.env and logs stay)
#
# Run it from the checkout the plist names (its WorkingDirectory). Test seams: LAUNCHCTL,
# PLUTIL, OPEN_MARIN_LAUNCH_AGENTS_DIR.
set -euo pipefail

label="cc.eastpeak.openmarin-refresh-weekly"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
plist="$here/$label.plist"
env_file="$here/weekly.env"
log_dir="$repo/data/ingest-runs/launchd"
agents="${OPEN_MARIN_LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
installed="$agents/$label.plist"
launchctl="${LAUNCHCTL:-launchctl}"
plutil="${PLUTIL:-plutil}"
domain="gui/$(id -u)"

die() { echo "install.sh: $*" >&2; exit 1; }

bootout_if_loaded() {
  if "$launchctl" print "$domain/$label" >/dev/null 2>&1; then
    "$launchctl" bootout "$domain/$label"
  fi
}

if [ "${1:-}" = "--uninstall" ]; then
  bootout_if_loaded
  rm -f "$installed"
  echo "Removed $label. $env_file and $log_dir are untouched."
  exit 0
fi
[ $# -eq 0 ] || die "usage: install.sh [--uninstall]"

grep -qF "<string>$repo</string>" "$plist" \
  || die "$plist does not target this checkout ($repo); run install.sh from the repo it names"
[ -x "$repo/.venv/bin/python" ] || die "no $repo/.venv/bin/python"
[ -f "$env_file" ] || die "no $env_file: copy weekly.env.example to weekly.env, fill it in, chmod 600"
[ "$(ls -ld "$env_file" | cut -c1-10)" = "-rw-------" ] \
  || die "$env_file must be private to you: chmod 600 $env_file"
grep -Eq '^OPEN_MARIN_HEARTBEAT_URL=.+' "$env_file" \
  || die "OPEN_MARIN_HEARTBEAT_URL is empty in $env_file; set it to the Healthchecks.io ping URL"

"$plutil" -lint "$plist" >/dev/null
mkdir -p "$log_dir" "$agents"  # launchd opens its log files before the job runs; the dir must exist
bootout_if_loaded
install -m 644 "$plist" "$installed"
"$launchctl" bootstrap "$domain" "$installed"

cat <<EOF
Installed $label: stage runs Mondays at 05:00, logging to $log_dir/.
Run it once now, under launchd, to check it end to end (README.md, "Acceptance"):
  launchctl kickstart $domain/$label
EOF
