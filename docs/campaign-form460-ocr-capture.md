# Selected San Rafael Form 460 OCR Capture

Verified: April 12, 2026

This note records the first selective OCR capture path for San Rafael city-side campaign filings.

## Scope

Captured filings:

- `37677` — Kate Colin 2024 first preelection Form 460
- `37685` — Rachel Kertz 2024 preelection Form 460
- `37365` — Rachel Kertz 2024 semiannual Form 460

## What Works

The public path is strong enough for selective filing capture when the adapter does:

1. bootstrap a fresh anonymous session
2. warm the specific document with `DocView.aspx?id=...`
3. call the JSON services for:
   - metadata
   - document info / page count
   - page-level OCR text

That is now enough to preserve:

- filing title
- template
- page count
- path metadata when available
- full page OCR text
- schedule coverage across the filing

## What This Produced

The OCR bundle shows:

- Kate Colin `37677` with `26` pages and schedules `A` through `H`
- Rachel Kertz `37685` with `11` pages and schedules `A`, `B`, `C`, `D`, `E`, `F`, and `H`
- Rachel Kertz `37365` with `10` pages and schedules `A`, `B`, `C`, `D`, `E`, `F`, and `H`

## Current Boundary

This note does **not** solve on its own:

- page-image asset URLs
- full-filing export coverage across the broader city-side campaign archive

Selective raw PDF export is now documented separately in [campaign-form460-pdf-export.md](/docs/campaign-form460-pdf-export.md). The OCR path remains useful because it preserves page-level text directly.

## Files

- [2026-04-12.json](/data/extracted/san-rafael-city-campaign-form460-ocr/2026-04-12.json)
- [bundle-01.json](/data/normalized/san-rafael-city-campaign-form460-ocr-01/bundle-01.json)
