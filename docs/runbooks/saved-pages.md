# Saved pages: the meeting listings we may not fetch

Every Granicus host we read answers `User-agent: * / Disallow: /` in its robots.txt (checked
2026-10-16), so the weekly run never fetches these listings (`schedule: saved-page` in
registry/granicus-sources.yaml). The operator saves them from a browser instead; the weekly digest
lists each one with its age and says "save a fresh page" once one is missing or older than 14 days.

## Monday: save these five pages

Open each listing, save it with "Save Page As… → Webpage, HTML Only" (or view source and save), as
`data/raw/manual/<today, YYYY-MM-DD>/granicus/<source id>.html` in the main checkout:

1. `marin-county-bos` — https://marin.granicus.com/ViewPublisher.php?view_id=33
2. `novato-city-council` — https://novato.granicus.com/ViewPublisher.php?view_id=7
3. `sausalito-city-council` — https://sausalito.granicus.com/ViewPublisher.php?view_id=6
4. `tiburon-town-council-granicus` — https://townoftiburon.granicus.com/ViewPublisher.php?view_id=5
5. `san-anselmo-town-council` — https://sananselmo-ca.granicus.com/ViewPublisher.php?view_id=8

## What happens next

The next weekly run picks up the newest saved page of each source by itself; nothing else to run.
Each one ends the stage with one outcome, shown in the digest's "Saved pages" table:

- **accepted** — new bytes: parsed exactly as a fetched page would be (`ingest.py --saved-page`),
  kept as `data/raw/<id>/<date>/saved-<sha256 prefix>.html`, then loaded like any source. If its
  floors reject it, that run fails like any failed source (one alert).
- **unchanged** — that page is already loaded. **stale** — the newest page is older than 14 days
  (it is not ingested; save a fresh one). **missing** — none saved yet. **rejected** — these exact
  bytes failed their floors in an earlier run; save the page again.
- None of unchanged / stale / missing / rejected fails the run or the heartbeat. The saved files are
  only read, never moved or deleted.

To ingest one by hand instead (e.g. before Monday):
`python scripts/ingest.py --source novato-city-council --saved-page data/raw/manual/2026-10-19/granicus/novato-city-council.html`.
The weekly run still loads it (a captured page that was never loaded counts as new).

## The robots gate for everything else

Every request a meeting adapter makes (Corte Madera, Ross, Fairfax, Belvedere) is checked against
that host's robots.txt first (scripts/robots_gate.py): fetched once per host per run (recorded with
its sha256 in the run's state.json `robots`), Crawl-delay honored per host (Ross asks for 15 s), every
request decision logged in `data/ingest-runs/<run>/logs/requests-<registry>.jsonl`. A disallowed URL
ends the source `robots_disallowed` with the matching rule; an unreachable or erroring robots.txt
ends it `robots_unavailable`. Both fail that source (and the heartbeat), so a host that changes its
rules is noticed the same Monday.
