# Larkspur City Council in the weekly run: Archive Center agendas, native ids, no-overwrite load

Larkspur posts its City Council agendas on a CivicPlus **Archive Center** page,
`https://www.larkspur.ca.gov/Archive.aspx?AMID=49`. That is one static listing of titled items, each a PDF
at `Archive.aspx?ADID=N`. The source `larkspur-city-council` (registry/civicplus-sources.yaml) brings in
**meetings and their agenda Records from 2019 on**. It brings in no minutes and no votes:

- the minutes are on `records.cityoflarkspur.org` (Laserfiche), whose robots.txt is `Disallow: /`;
- `ca-larkspur2.civicplus.com` is `Disallow: /` too.

The source's host allowlist (`allowed_hosts: [www.larkspur.ca.gov]`) means neither host, nor any other,
gets a request from this source. That covers pages, redirect hops, robots.txt fetches and robots.txt
redirects, whatever any robots.txt says.

| Piece | Where |
|---|---|
| Adapter (listing parser, every row accounted for) | scripts/adapters/civicplus_archive.py |
| Host allowlist | scripts/robots_gate.py (`hosts=`) |
| Ingest identity mode `native-only`, pinned load policy | scripts/ingest.py, scripts/crosswalk.py |
| First-run floor (`floors.min_rows`) | scripts/ingest_guard.py |
| No-overwrite load: stub allowance, listing memory | scripts/guarded_load.py |
| Rehearsal, check-loaded | scripts/crosswalk_rehearsal.py (`--expected` for a native-only source) |

## How a Monday goes

1. **Stage.** The run makes two requests: robots.txt, then the listing page (no item is fetched). Every
   row is accounted for:
   - **included**: a meeting;
   - **excluded**, with a reason: `before_backfill_from`; `attendance_notice` (a courtesy notice that a
     quorum may attend another body's event); `index_of_same_day_agendas` (a cover page for a day whose
     meetings each have their own row);
   - **unresolved**.

   Any of these fails the source closed: an unresolved row, a missing or wrong archive table, a table
   without exactly one item link, or a listing that no longer reaches back before 2019. Nothing is
   written, and the digest's Failures name the ADID and the reason (`adapter error: unresolved row ADID
   N: <reason>: <title>`). The `min_rows` floor (the reviewed inventory) catches a partial parse on a first
   run.
2. **Ids.** A meeting is a listing key `(date, type, ordinal)`:
   - the type comes from the title and note: `cancelled_meeting`, `joint_meeting`, `closed_session`,
     `special`, `workshop`, `regular`;
   - "Second Special" gets ordinal 2.

   Its id is the city's item id, `meeting-larkspur-city-council-adid-<N>`. A notice naming two dates is
   two meetings, `-adid-<N>-<date>`, sharing one notice Record. Two rows on one key with the same title
   are a re-posting: the meeting takes the latest ADID, and the others are listed as
   `superseded_item_ids`. The date/title identity map is never used for this source.
3. **Load.** The load goes through `guarded_load`, as San Rafael's does
   ([san-rafael-weekly.md](san-rafael-weekly.md)): creates only, and never a write to an existing node or
   relationship. In addition:
   - the capture's pinned `load_policy` must equal the registry's now;
   - `org-larkspur-city-council` and `place-larkspur` may be created **only if absent**, once. Both
     already exist in the graph (2026-10-17), so they are left untouched, including the council
     stub's bare `name`;
   - the graph remembers the listing (see the holds below).
4. **Report.** As for San Rafael: `data/ingest-runs/<run>/load-reports/larkspur-city-council.<n>.json`.
   `held` means nothing of Larkspur was written, it shows in the digest's Failures, and the heartbeat goes
   `/fail`.

## When Larkspur is held (or fails its pull)

| Reason | Meaning | What to do |
|---|---|---|
| `adapter error: unresolved row ADID N: …` | The city posted a row the rules cannot read. Possible reasons: `no_date`, `invalid_date`, `no_type_word`, `plural_agendas`, `unconsumed_text`, `cancelled_and_regular_same_day`, `same_key_different_titles`. | Open `Archive.aspx?ADID=N` in a browser. If it is a new title shape, extend the rules with a test vector from the real title. Never exclude it by hand. |
| `listing_table_missing`, `row_count_mismatch`, `listing_truncated` | The page is not the whole listing (redesign, outage, truncation). | Look at the saved raw page (`data/raw/larkspur-city-council/<date>/source.html`). |
| `listing_item_missing` | A loaded meeting's agenda item is gone from the listing (truncation, deletion, or a replacement posting). | Compare with the last good raw page. A deliberate replacement is a reviewed migration; never delete or re-id a Meeting to clear it. |
| `repost_suspected` | A new item sits on a listing key an existing Meeting holds (a re-posted agenda). | Same: decide which item is the meeting's agenda, as a reviewed migration. |
| `listing_key_changed` | A loaded item's title now reads as a different date or type, or a notice's set of dates changed. | Check the PDF; a reviewed migration if the city corrected it. |
| `listing_item_dropped` | A loaded item is still listed but no longer reads as a meeting (e.g. retitled as a courtesy notice). | Check the PDF; a reviewed migration if the meeting really is gone. |
| `listing_item_reassigned`, `new_repost_on_loaded_meeting` | A loaded meeting's own item now reads as another item's re-post, or a new re-post of a loaded meeting appeared (the load cannot record it without writing the existing Meeting). | Check the PDFs; decide which posting is the meeting's agenda as a reviewed migration. |
| `superseded_item_reappeared` | A posting absorbed as a re-post of another meeting now reads as its own meeting, or under another one. | Check both PDFs; never let it become a second Meeting by itself. |
| `cancellation_conflict` | A cancellation and a regular meeting on one date, across loads. | Check whether the regular meeting was cancelled after its agenda was posted. |
| `artifact_url_changed`, `artifact_url_on_other_record` | As for San Rafael. | As for San Rafael. |
| `policy_mismatch` | The registry changed between stage and load (identity, institution, place, stubs), or the capture's header disagrees. | Stage a fresh run. |
| `missing_node` | A node other than the two allowed stubs is absent. | Investigate. |

## Rehearsal (staging only, no graph writes)

```
python scripts/crosswalk_rehearsal.py rehearse --source larkspur-city-council \
  --export <fresh export dir> --work ~/open-marin-staging/larkspur-council/rehearsal-<date> \
  --identity-cache data/ingest-runs/meeting-identity.json \
  --responses <recorded responses> --expected <expected.json>
```

`--expected` is `{"meetings": [...], "records": [...], "stubs": [...]}`. It is built from the reviewed
listing inventory (a staging tool independent of the adapter), never from the adapter's own output.
`--responses` replays a pinned capture: robots.txt and the listing, through the real gate.

## After a real Monday run: check-loaded

Use the San Rafael snippet ([san-rafael-weekly.md](san-rafael-weekly.md), "After a real Monday run")
with `--source larkspur-city-council` and the post-export under `~/open-marin-staging/larkspur-council/`;
when the agenda-items stage ran, use the run's `agenda-items/pre` export as that snippet's first form says.
For a native-only source, check-loaded does two things the crosswalk version does not:

- it refuses if the registry's load policy changed since the run;
- a stub that the run created counts as the source's own, so it must match the plan exactly. A stub
  that already existed is compared on the properties the normalizer writes.

## Activation (the flip)

Larkspur is `schedule: manual` until the switch to `weekly` is merged. That happens on the same terms as
San Rafael's:

1. the inspected 2026-10-19 run;
2. rebased on whatever San Rafael flip landed;
3. re-gated and pushed;
4. the canonical checkout fast-forwarded to exactly the gated SHA under the run lock.

The snippet is the one in [san-rafael-weekly.md](san-rafael-weekly.md), "Activation". The first weekly
Larkspur load is the first load ever (228 Meetings at the 2026-10-18 inventory, or more as the city posts
agendas). Its check-loaded is the first proof on the real graph.

## Minutes and votes

Not available by fetch (robots `Disallow: /` on the minutes host). The route is a records request to the
City Clerk. A draft is in the goal's staging report; nothing has been sent.
