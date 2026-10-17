# Votes refresh: saved minutes → a reviewed, apply-ready CAST_VOTE batch

The 2026-10 backfill (votes Part A + B2) covered Novato City Council minutes through 2026-03-10 and Board of
Supervisors minutes through 2026-03-20. `scripts/votes_refresh.py` keeps both bodies current as a **backlog of
known Meetings**: every in-scope Meeting after those dates is tracked, any pending one can be taken whatever its
date, and a meeting's minutes are processed once.

Both bodies publish minutes on Granicus (`novato.granicus.com`, `marin.granicus.com`), whose robots.txt disallows
every agent. **Nothing here fetches.** You save each file by hand; the scripts only read it.

State lives in `~/open-marin-staging/votes-refresh/` (`REFRESH_ROOT`):

| File | What it is |
|---|---|
| `config.json` | the reviewed roster and person mapping, verified once by `init` and pinned by sha256 |
| `registry.jsonl` | append-only: batch claims (meeting → document sha256), revisions, releases, conflicts, roster holds and their resolutions |
| `applied.jsonl` | the applied journal: written only after a verified apply |
| `history.jsonl` | one line per `todo`/`prepare` run |
| `todo.md` / `todo.json` | the minutes to save |
| `batches/batch-NNN/rev-K/` | one revision of a batch: manifest, ledger, bundle, plan, spot check (a `votes_apply.py` state dir) |
| `roster-holds/` | one review packet per roster hold, and `resolutions.txt` |

## 1. What to save

```
python scripts/votes_refresh.py todo --export <export dir>
```

`<export dir>` is a read-only `python scripts/export_live_graph.py --backup --out-dir …` of the operator graph,
made after the weekly run has loaded the newest listings (the weekly digest shows the same list under
"Votes minutes to save"). `todo.md` starts with the age of each body's newest loaded listing: it reports coverage
of **known** Meetings as of that date, never "current through". A listing older than 14 days is a warning.

For each meeting, open its MinutesViewer URL in your browser and save the file to the path shown:

    data/raw/manual/<YYYY-MM-DD>/minutes/<body>/<meeting_id>.<pdf|docx|html>

- **Board of Supervisors: save the MinutesViewer page as HTML** (`.html`). Board listing titles never say whether a
  meeting was regular or special, so only the page's own `clip_id` proves which meeting it is.
- Novato: PDF is fine (the saved PDF, or the page as HTML).

A saved file is accepted only on its own heading: the jurisdiction (Novato / Marin + Board of Supervisors, and no
other Marin city or county), exactly one printed date equal to the meeting's, and the session (closed / special /
regular) matching the listing. Anything uncertain stays pending, and `todo.md` says why (for example
`heading_session_mismatch:closed≠regular` for a closed-session file saved as the regular meeting).

Once a slot has a prepared or applied file, a different file for that meeting is never parsed: it is recorded as
`document_version_conflict` and shown in `todo.md` and `status`.

## 2. Prepare a batch

```
python scripts/votes_refresh.py prepare --export <export dir>
```

This is offline (it reads files only) and takes every pending meeting with an accepted file. It ends in one of:

- `AWAITING_MINUTES`: nothing is saved yet (`todo.md` is refreshed). `NOTHING_ELIGIBLE`: no pending meeting at all.
- `BLOCKED`: the only saved files belong to a body with an unresolved apply (see §6) or damaged batch metadata.
- `AWAITING_ROSTER_REVIEW`: roster-change evidence held the votes (§3); nothing attached.
- `ALL_HELD`: the documents were parsed but nothing could attach (see `bundle/repair.jsonl`).
- `AWAITING_REVIEW`: a plan and a spot-check sheet are ready (`batches/batch-NNN/rev-1/`).

Every batch revision is a pure function of its `manifest.json`.
`python scripts/votes_refresh.py check --batch batch-NNN --rev K` rebuilds it into a temporary dir and requires
byte identity.

## 3. Roster holds

A roll-call or vote name with no confirmed roster term, or oath / resignation / appointment / vacancy / election
wording for the body itself, records a **roster hold** and writes `roster-holds/<hold_id>.md`. Every vote of that
body dated on or after the hold's date is then held, in every batch, until the hold is answered. That includes a
batch approved before the hold was found: `votes_apply.py apply` refuses it.

- No roster change (a misprint, a commission appointment the detector could not place): add
  `<hold_id> dismiss: <why>` to `roster-holds/resolutions.txt`, then re-prepare the batch
  (`prepare --export <dir> --batch batch-NNN`).
- A real change (a new member, a resignation): leave the hold. It needs a reviewed roster batch, which is a
  follow-up goal.

Hints only, never a term change: a confirmed member missing from every roll call of the batch. A body with no
usable roll call is reported as "insufficient evidence".

## 4. Review and staging bake

1. An independent reviewer (not the author of the batch) checks `spot-check.md` against the source minutes. They
   write a review file whose first line is `Sheet sha256: <sha256 of spot-check.md>`, then one line per item:
   `S<n> agree`, `S<n> disagree: …` or `S<n> unsure: …`.
2. If any item is a disagree or an unsure, hold those events with `{"holds": [{"event_id": …, "reason": "S<n>: …"}]}`
   and run `prepare --export <dir> --batch batch-NNN --reviewer-holds <file>`. That makes a new revision, which
   needs a new review.
3. Bake the candidate into staging and serve it locally:

   ```
   R=~/open-marin-staging/votes-refresh/batches/batch-NNN/rev-K
   python scripts/bake_public_substrate.py --source live-export --live-export-dir $R/plan/candidate \
       --sqlite $R/bake/public-substrate.sqlite --report $R/bake/substrate-bake-report.json
   (cd app && SERVING_BACKEND=substrate SUBSTRATE_DB_PATH=$R/bake/public-substrate.sqlite npx next dev -p 3421)
   python scripts/votes_apply.py bake-check --sqlite $R/bake/public-substrate.sqlite --bundle $R/bundle \
       --plan $R/plan --targets $R/plan/targets.json --baseline <export dir> \
       --base-url http://localhost:3421 --out $R/bake-check.json
   ```

   The batch-scoped check covers:
   - the new Decisions' labels and public props, and the existing target Decisions' props (unchanged);
   - the exact edges on the batch's own targets;
   - every baseline vote, unchanged;
   - nothing unplanned;
   - one rendered Decision page per body in the batch.

## 5. Approve, then Stuart applies

```
python scripts/votes_refresh.py approve --batch batch-NNN --review <review file> --bake-check $R/bake-check.json
```

This yields `AWAITING_APPLY` and an approval sha256 bound to every file. The apply is Stuart's step:

```
python scripts/votes_apply.py apply --state-dir $R --approve <sha256> --canonical-root ~/projects/marin-civic-graph
```

For a refresh revision this holds the refresh lock and then the weekly lock throughout. It:
1. Re-checks that the revision is current and that no roster hold covers it.
2. Backs up the graph; the backup must equal the baseline, else DRIFT.
3. Publishes `APPLY_IN_PROGRESS`.
4. Runs one transaction, then a whole-graph re-read inside it.
5. Commits, runs a post-apply export, and journals the batch only on a MATCH.

If another batch applied first, this one reports DRIFT. Rebase it with `prepare --export <fresh export> --batch
batch-NNN`, which makes a new revision; review, bake and approve again.

## 6. When an apply's outcome is unknown

`APPLY_IN_PROGRESS` (the process died), `APPLY_UNVERIFIED` or an unreadable `state.json` blocks new batches for
that body. Never edit the state by hand. Run:

```
python scripts/votes_refresh.py resolve --batch batch-NNN --canonical-root ~/projects/marin-civic-graph
```

It takes a fresh read-only export of the live graph (bolt://localhost:7688 only).
- Equal to the candidate → `APPLIED`, journaled.
- Equal to the baseline → `ROLLED_BACK`, slots released.
- Anything else stays unresolved: recover from `apply/RECOVERY.md`.

## 7. After the next publication

```
python scripts/votes_apply.py check-published --state-dir $R --sqlite <published public-substrate.sqlite> \
    --base-url <site>
```

For a refresh batch this checks the exact edges on that batch's own targets and that every baseline vote is
unchanged; votes added by later batches are allowed. Only this records `PUBLISHED_VERIFIED`.

`abandon --batch batch-NNN` releases an unapplied batch. Its meetings can be taken again, by the same files only.
