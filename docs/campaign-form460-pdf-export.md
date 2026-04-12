# San Rafael Form 460 PDF Export Capture

Verified: April 12, 2026

This note records the first repeatable raw-PDF export path for selected San Rafael city-side campaign filings.

## Scope

Captured filings:

- `37677` — Kate Colin 2024 first preelection Form 460
- `37685` — Rachel Kertz 2024 preelection Form 460
- `37365` — Rachel Kertz 2024 semiannual Form 460

## What Works

The public path is now strong enough for selective raw filing export when the adapter does:

1. bootstrap a fresh anonymous session
2. warm the specific document with `DocView.aspx?id=...`
3. confirm export rights through `FolderListingService.aspx/GetExportRights`
4. start the export through `ZipEntriesHandler.aspx/StartExport`
5. poll completion through `ZipEntriesHandler.aspx/CheckExportStatus`
6. download the finished artifact from `ExportJobHandler.aspx/GetExportJob/?token=...`

For the three selected filings, that path returned actual `application/pdf` artifacts without audit-reason or watermark prompts.

## What This Produced

The raw export bundle now preserves:

- `3` successful PDF exports
- stable local artifact paths for each filing
- byte size and `sha256` hashes for each PDF
- export-token workflow metadata proving the public path end to end

## Current Boundary

This does **not** mean:

- every city-side campaign filing family is already captured as raw PDF
- page-image asset URLs are needed or documented separately
- exact filing-level accounting is solved automatically

The raw artifact boundary is now solved for the selected `Form 460` filings. The remaining work is extraction quality and broader adapter coverage.

## Files

- [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-campaign-form460-pdf-export/2026-04-12.json)
- [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-form460-pdf-01/bundle-01.json)
- [manifest.json](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-campaign-form460-pdf-export/2026-04-12/manifest.json)
