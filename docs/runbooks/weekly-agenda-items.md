# Weekly agenda items

The weekly run's agenda-items stage turns the agenda files of eligible council sources into AgendaItems, create
only. Code: scripts/agenda_items.py (the stage), scripts/agenda_parsers.py (parsers), scripts/guarded_load.py
(`load_agenda_bundle`), scripts/agenda_delta.py (the stage's before/after check), scripts/agenda_rehearsal.py
(rehearsal and check-loaded). The legacy one-off extractor (scripts/extract_agenda_items.py) is not part of it and
must not be run against the operator graph (it can delete a meeting's items); it now refuses while the graph lock
is held.

## What it does each week (when enabled)
After every meeting load of the run has succeeded, under the run lock and the graph lock
(~/.open-marin/locks/graph-localhost-7688.lock):
1. `agenda-pre`: a full export of the graph to `data/ingest-runs/<run>/agenda-items/pre/`.
2. `agenda-items`: for each eligible source (registry `agenda_items` block, weekly, not Granicus, parser qualified
   at its current version):
   - re-checks the agendas it loaded before (weekly until 28 days after the meeting): a changed url or changed bytes
     marks them `revised` in the ledger — reported, never re-parsed, the items are left as they are;
   - selects up to `cap` (20) council meetings with exactly one unshared agenda Record and no AgendaItems, newest
     first, plus held meetings due a retry (every 28 days, at most 5 per run, never from the cap);
   - fetches each agenda through the robots gate (the source's host allowlist; 5 s apart, plus Crawl-delay),
     parses it, holds what does not fit (another date, body or session; a notice; no items; two sessions; bytes
     shared with another meeting; …), and loads the rest in one transaction: creates only.
3. `agenda-post`: a full export to `…/agenda-items/post/`.
4. `agenda-delta`: the two exports must differ by exactly the committed items and their two edges each.

A failure in any of the four never stops the run (the meetings are loaded and published) but the heartbeat pings
`/fail` and the digest's "Agenda items" section says why. Holds never fail the run.

State: `data/ingest-runs/agenda-items-ledger.json` (per meeting: loaded / held / revised / pending, url, sha256,
item ids). Each run keeps its phases in `data/ingest-runs/<run>/agenda-items/` (selection, fetched results and
files, bundle, report, revisions, pre/post exports, delta); re-running a run's load re-runs the stage as a no-op.

## Reading the digest
| Column | Meaning |
|---|---|
| Loaded | meetings / AgendaItems created this run |
| Held | reason × count (held meetings are retried every 28 days; `body_unconfirmed`, `agenda_url_shared`, `agenda_records_ambiguous` are re-judged every run without a fetch) |
| Revised | loaded agendas whose url or bytes changed since: look at them by hand; nothing was changed in the graph |
| Backlog left / Catch-up weeks | fresh candidates not yet taken, and weeks at the cap to take them |

## A revised agenda
The ledger entry names the reason (`url_changed` or `content_changed`) and the new url or sha256. The loaded
items stay. If the change matters, a human decides (there is no automatic re-parse). Never delete items by hand.

## check-loaded (after the first real run with the stage on)
```
cd ~/projects/marin-civic-graph && RUN=<run id> \
  && .venv/bin/python scripts/crosswalk_rehearsal.py check-loaded "$RUN" --agenda-items
```
Read only. It binds to the run's pinned pre/post exports, bundle and report; recomputes the delta; checks the
ledger; and checks that no AgendaItem or Decision that existed before the run changed or vanished (pre-load
backup vs post export). PASS is required.

## Activation
The stage ships disabled (`AGENDA_ITEMS_ENABLED = False` in scripts/refresh_weekly.py) and no source is qualified
in the repo registry until its held-out evidence is recorded. Activation is a separate commit that sets the flag
(and, if not yet done, the `qualified` blocks), merged only after the San Rafael and Larkspur flips have landed
(or explicitly excluding whichever has not), on the same terms as docs/runbooks/san-rafael-weekly.md
"Activation": inspect a weekly run, rebase, re-gate (`pytest tests/ -q -m "not operator_data"` and
`cd app && npm run verify`), push, then fast-forward the canonical checkout to exactly the gated sha inside the
run lock (the snippet in that runbook). Then run check-loaded on the first run.

## Adding a source
Add an `agenda_items` block (artifact, parser, hosts, body, and `document` — the body named in the agenda
header), fetch ≥ 5 real agendas through the gate, have them annotated independently (reviewer brief in the
staging study), compare, and only then record `qualified: {parser, version, report}`.
