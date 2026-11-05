# The weekly run's PATH, sourced by run-weekly.sh before weekly.env (so an operator override there still wins).
# launchd starts a job with only /usr/bin:/bin:/usr/sbin:/sbin; the run needs Homebrew's pdftotext (the
# agenda-items stage, the votes digest). Set outright, never appended to the inherited PATH, so a launchd job and
# `env -i` resolve every tool the same way. The inventory and the run's own check: refresh_weekly.py TOOLS.
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
