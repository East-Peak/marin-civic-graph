# San Rafael Form 460 Schedule Extraction

Verified: April 12, 2026

This note records the first schedule-level extraction pass over the selected San Rafael city-side `Form 460` OCR bundle.

## Scope

Source filings:

- `37677` — Kate Colin 2024 first preelection Form 460
- `37685` — Rachel Kertz 2024 preelection Form 460
- `37365` — Rachel Kertz 2024 semiannual Form 460

Derived outputs:

- [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-campaign-form460-schedules/2026-04-12.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-form460-schedules-01/bundle-01.json)

## What This Produced

The first pass promotes:

- `3` enriched `Filing` candidates
- `94` actor candidates or actor joins
- `103` `MoneyFlow` candidates

Per filing:

- `37677`
  - `45` Schedule A rows
  - `3` Schedule E rows
  - extracted itemized contributions: `$13,793.00`
  - reported monetary contributions: `$16,392.00`
  - extracted itemized payments: `$3,935.76`

- `37685`
  - `23` Schedule A rows
  - `1` Schedule D row
  - `3` Schedule E rows
  - extracted itemized contributions: `$6,625.00`
  - reported monetary contributions: `$7,265.00`
  - extracted itemized payments: `$2,400.00`
  - reported payments made: `$3,925.99`

- `37365`
  - `28` Schedule A rows
  - extracted itemized contributions: `$5,648.00`
  - reported monetary contributions: `$6,915.00`
  - no itemized Schedule E rows captured from the current OCR

## What Works

- Schedule A OCR is strong enough to promote many itemized contribution rows.
- Schedule D can support small, high-confidence rows when the page keeps the payment type and stance legible.
- Schedule E can support a mixed parser:
  - one path for column-preserved payee / code / amount sections
  - one path for OCR lines that collapse payee, code, description, and amount into one line
- Existing city-side `Committee` and `Filing` IDs can be reused instead of inventing a parallel campaign namespace.

## Current Boundary

This is still a conservative extraction layer.

It does **not** mean:

- full filing completeness is solved
- OCR is strong enough to replace manual review for every row

The extracted row totals still trail the reported filing totals in all three filings. That is the main evidence that the OCR path is usable but incomplete. Raw PDF export is now solved separately, but the parser still needs stronger QA and row recovery.

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
