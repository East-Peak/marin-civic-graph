# Weekly ingestion LaunchAgent (template)

`cc.eastpeak.openmarin-refresh-weekly.plist` runs `scripts/refresh_weekly.py stage` every Monday at 05:00.
It is a **template**: nothing in the repo installs it, because installing it is the operator's call.

`stage` fetches every weekly source, floors each one against its last good run, and stages the results
under `data/ingest-runs/<run_id>/`. It then writes `digest.md` and stops at `awaiting_load_approval`. It never
loads into Neo4j and never publishes. Those two steps stay manual gates:

```sh
.venv/bin/python scripts/refresh_weekly.py status            # latest run's state and digest path
.venv/bin/python scripts/refresh_weekly.py load <run_id>     # needs NEO4J_URI/USER/PASSWORD in your shell
.venv/bin/python scripts/refresh_weekly.py publish <run_id>  # swaps data/exports/staging/ into data/exports/; no deploy
```

## Installing (operator only)

1. Copy the template and replace every `__REPO__` with the absolute repo path.
2. Replace `__SET_NEO4J_URI__` with Open Marin's operator graph URI (port 7688, never 7687, which is the
   family-tree store). `stage` uses it only for the `neo4j_target` preflight guard. Put no credentials in the plist.
3. Run `plutil -lint` on the copy, place it in `~/Library/LaunchAgents/`, then
   `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/cc.eastpeak.openmarin-refresh-weekly.plist`.

launchd output goes to `data/ingest-runs/launchd.{out,err}.log`. Each step's own log is in `<run>/logs/`.
