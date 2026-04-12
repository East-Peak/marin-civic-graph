# San Rafael Form 460 Schedule Extraction

Verified: April 12, 2026

This note records the current schedule-level extraction pass over the selected San Rafael city-side `Form 460` filings, using OCR for contribution-heavy pages and the preserved PDF text layer for `Schedule E` payment pages.

## Scope

Source filings:

- `37677` — Kate Colin 2024 first preelection Form 460
- `37685` — Rachel Kertz 2024 preelection Form 460
- `37365` — Rachel Kertz 2024 semiannual Form 460

Derived outputs:

- [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-campaign-form460-schedules/2026-04-12.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-form460-schedules-01/bundle-01.json)

## What This Produced

The current pass promotes:

- `3` enriched `Filing` candidates
- `103` actor candidates or actor joins
- `130` `MoneyFlow` candidates

Per filing:

- `37677`
  - `45` Schedule A rows
  - `27` Schedule E rows
  - extracted itemized contributions: `$13,793.00`
  - reported monetary contributions: `$16,392.00`
  - extracted itemized payments: `$23,337.66`
  - reported unitemized payments: `$57.30`

- `37685`
  - `23` Schedule A rows
  - `1` Schedule D row
  - `6` Schedule E rows
  - extracted itemized contributions: `$6,625.00`
  - reported monetary contributions: `$7,265.00`
  - extracted itemized payments: `$3,576.26`
  - reported unitemized payments: `$249.73`
  - reported payments made: `$3,925.99`

- `37365`
  - `28` Schedule A rows
  - extracted itemized contributions: `$5,648.00`
  - reported monetary contributions: `$6,915.00`
  - no itemized Schedule E rows
  - reported unitemized payments: `$183.29`

## What Works

- Schedule A OCR is strong enough to promote many itemized contribution rows.
- Schedule D can support small, high-confidence rows when the page keeps the payment type and stance legible.
- Schedule E is materially stronger now that the extractor prefers the PDF text layer when the raw export exists.
- The `37677` and `37685` itemized Schedule E row sums now match the PDF summary totals exactly.
- Schedule E summary values now preserve unitemized payments even when a filing has no itemized Schedule E rows.
- Existing city-side `Committee` and `Filing` IDs can be reused instead of inventing a parallel campaign namespace.

## Current Boundary

This is still a conservative extraction layer.

It does **not** mean:

- full filing completeness is solved
- contribution-side extraction is complete
- the parser is strong enough to replace manual review for every row

The remaining gap is narrower now. Payment-side extraction is substantially better, but contribution-side totals still trail the reported filing totals, so the project still should not treat these filings as exhaustively parsed.

## Interpretation Rule

Use this layer for:

- actor continuity
- candidate / committee joins
- donor and vendor recurrence
- bounded media-to-campaign overlap work

Do not use it yet for:

- exact full-filing accounting
- contribution-limit enforcement claims
- “all donors” or “all expenditures” analytics without review
