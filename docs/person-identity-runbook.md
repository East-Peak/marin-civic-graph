# Person identity review (operator-only)

A donor "Person" in the graph is a name bucket: every contribution reported under one name slug. Before any
contribution is tied to a person in government, the operator reviews the evidence and records a decision. This
runbook covers that private review. Nothing here changes the public graph, the bake or the app; publishing approved
decisions is later work.

Code never decides identity. It ranks questions, shows evidence, and records the operator's answers.

## Where things live

| What | Where | In a repo? |
|---|---|---|
| HMAC key, address-cluster hashes, review files, operator report, stale latch | `$OPEN_MARIN_IDENTITY_DIR` (default `~/.open-marin-private/identity/`) | never |
| Decisions (one JSON line each) | private data repo, `identity/person/decisions.jsonl` | private data repo only |
| Code and tests | `scripts/identity_person*.py`, `tests/test_identity_person_*.py` | this repo |

The private directory must resolve outside this repo, the private data repo and all their worktrees; the tools
refuse otherwise. The key must be `0600` and the directory `0700`, both owned by you, with no symlink on the path.

The contributor street (`Tran_Adr1`/`Tran_Adr2`, with `Tran_Zip4`) is read from the raw workbooks into memory only.
It is never written anywhere: not to a file, log, report, error message or git history. What is kept is a keyed
HMAC per row (private directory only) and, in the decision file, keyed fingerprints of the rows a decision covers.
Review files show address clusters as letters (A, B, …), never streets or hashes.

**As of 2026-10-12, NetFile's public exports carry no contributor street at all.** `Tran_Adr1`/`Tran_Adr2` (and
the treasurer and intermediary street columns) are empty in every row of every captured year. So every row reports
`missing_street`, no bucket has address clusters, class C is empty, and B/A items rank by total alone. The
machinery is in place for a source that does carry the street (the filed Form 460 itself, for example). Until one
is added, the evidence is name, committee, date, amount, occupation, employer, city and ZIP5.

## Once: create the key

    python scripts/identity_person.py init-key

It writes `key-v1` and prints only its path. It never replaces an existing key. Back the key up somewhere private
if you want decisions to survive a lost disk (see *Key loss*).

## Each review round

1. **Freeze the inputs.** Take a live export with `scripts/export_live_graph.py --backup --out-dir <dir>` into a
   staging directory outside the repos. Do not take it while the Monday weekly run holds
   `data/ingest-runs/.lock`. The ledger bundle (`normalized/campaign-ledger/` in the private data repo) and the raw
   workbooks (`data/raw/`, newest capture per year) are read where they are.
2. **Build.**

        python scripts/identity_person.py build --export <dir> --as-of YYYY-MM-DD

   `--as-of` is the frozen clock: nothing else in the output carries a date, so two builds over the same inputs
   are byte-identical. Output goes to `<private>/builds/<as-of>/` (or `--out <name>`):
   - `review/batch-001.md`: the first batch (up to 60 items), with the evidence and numbered options;
   - `review/batch-001.options.json`: the decision lines each option expands to, and the batch id (its digest is
     recorded in the manifest, so ingest refuses an options file the build did not write);
   - `queue.json`: every item; `report.md` / `report.json`: the operator report;
   - `manifest.json`: every input's sha256, the key version and the latch digest;
   - `decisions-state.json`: each decision's status; `address-evidence.jsonl`: the per-row hashes (private).
3. **Review.** Read the cautions at the top of the batch. Write a text file of answers: the first line is the
   batch line printed at the top of the review (`batch b-…`), then one line per item you decide — the item number
   (or its `q-…` id), a space, the option number. `#` starts a comment; blank lines are ignored; skipping an item
   is fine (it stays in the queue). Example:

        batch b-0123456789ab
        1 1     # all rows are this person
        2 3     # cannot decide
        q-B-50a1de09f0 2

   Item numbers belong to one build's batch. The batch line ties your answers to it: answers written for another
   batch (including a rebuild whose items changed) are refused, never silently applied to different items.
4. **Ingest.**

        python scripts/identity_person.py ingest --build <as-of or name> --answers <your file>

   Each answer expands to its option's decision lines (an `is` always comes with the `same` it rests on; two
   answers that share a line write it once). Ingest re-reads the build's inputs and refuses if any changed since
   the build. It checks each line's grammar and its fingerprints against the current evidence. If any answer or
   line is malformed, stale, unsupported or contradictory, the whole file is rejected and nothing is written; errors
   name your answer line, never echo what you typed. Otherwise the new lines are appended to the decision file
   atomically. Lines already in the file are no-ops.

   Raw decision lines (one JSON decision per line, e.g. edited by hand) still ingest without `--answers`:
   `ingest --build <name> <file>`.
5. **Commit.** The weekly snapshot commits `identity/person/` with the rest of the private data repo. You can also
   commit it by hand. Git is the history.

## The queue

- **B**: the bucket node itself has a government role (cast a vote, filed a Form 700, controls a committee).
  Question: which of its address clusters are that official's own?
- **A**: the bucket's reported name matches a government Person on another node. There is one item per (bucket,
  that Person), and every match is listed. Last-name-only matches are never made, and suffixes must agree when
  both names have one.
- **C**: the bucket's rows form two or more address clusters (top 25 by total). Question: one person or several?

Each bucket goes to the first class that applies. Buckets that are only payees (paid by a committee, with no role
on the node) are counted but never queued. Within a class, buckets whose rows form a single address cluster come
first. Then come larger totals (signed, in cents, over distinct flows). Stale decisions and conflicts are listed
before everything else.

What evidence means:
- Same name and same address is the strongest evidence, and still a question: household namesakes, omitted
  suffixes and shared business addresses all produce it.
- Different addresses mean "multiple reported address clusters", not different people: people move.
- Generic employers and occupations (retired, none, self-employed, n/a, …) are not evidence.
- There is no government-side address source. Government Person nodes may themselves be name-joined, so check
  each fact's provenance.
- Never infer coordination, favoritism or patronage.

## Decisions

| kind | groups | meaning |
|---|---|---|
| `same` | one group | these rows are one person |
| `distinct` | two or more groups | no row of one group is the same person as a row of another (a group alone does not imply sameness) |
| `is` | one group + `target` + `basis` | the person of these rows is the government Person `target`; `basis` names the `same` line it rests on |
| `reject` | one group + `target` | these rows are not `target` |
| `defer` | one or more groups (+ optional `target`) | cannot decide from these inputs |

A line also carries the keyed fingerprint of every covered row, `reviewer` (`stuart`), `date` and an optional
`note` code (one of: household_namesake, suffix_omitted, moved, shared_business_address, generic_employer_only,
same_employer, same_occupation, insufficient_evidence, official_record_differs, other). Free text is never
allowed, because the file must not hold an address.

To reverse a decision, edit or delete its line. Removing a `same` suspends every `is` that rests on it.

### Stale, latched, suspended, conflict

- **Stale**: a covered row changed, was amended away or is gone, or the target changed (renamed, lost its role,
  removed). A stale decision is not effective and comes back to the queue with a field-level diff. The diff names
  fields only: for an address it says just "address changed".
- **Latched**: once a build sees a decision stale, it stays stale even if the evidence changes back. To
  revalidate, re-ingest the identical line while its fingerprints are current.
- **Suspended**: an `is` whose `basis` `same` is missing, not effective, or does not cover its rows.
- **Conflict**: contradictory decisions. Examples: `same` and `distinct` over the same rows; one person with two
  targets; a `reject` against an `is`; one MoneyFlow whose rows land on two people. Every decision involved is
  suspended, and they come back as one conflict item. A flow in conflict is counted for nobody.
- **Defer** is a valid answer. It takes the item out of the queue until its rows change.

Totals in the report count each MoneyFlow once, for at most one person.

## Key loss

Without the key, current fingerprints cannot be computed. Every identity command fails closed, and nothing else in
the pipeline is affected. To recover:

1. Create a new key at the next version: `init-key --version N`. It refuses any version the decision file has
   already used.
2. Build. Every decision is now stale (all fields differ: "re-keyed") and comes back to the queue.
3. Re-review, then ingest fresh lines and delete the old ones.

The decision file itself is versioned weekly in the private data repo, so the decisions are never lost; only
their effectiveness waits for re-review.
