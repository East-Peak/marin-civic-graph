# Artifact Conventions

Date drafted: April 10, 2026

This document defines how collected source artifacts should be named and stored.

The goal is to make raw collection:

- reproducible
- inspectable
- easy to diff
- easy to reprocess

## Core Principles

- store raw before transformed
- do not overwrite silently
- keep provenance close to the artifact
- prefer deterministic names over ad hoc labels

## Suggested Top-Level Layout

```text
data/
  raw/
    <source_id>/
      <capture_date>/
        manifest.json
        source.html
        document.pdf
        attachment-01.pdf
        screenshot-01.png
  extracted/
    <source_id>/
      <capture_date>.json
  normalized/
    <case_study_id>/
      <bundle_id>.json
```

For planning purposes, only `data/raw/` needs to exist first.

## Directory Naming

### `source_id`

Use the exact `source_id` from the source registry.

Example:

- `san-rafael-aug-19-2024-staff-report`

### `capture_date`

Use UTC date format:

- `YYYY-MM-DD`

Example:

- `2026-04-10`

If multiple captures happen on the same day and need to be distinct:

- `YYYY-MM-DDTHHMMSSZ`

## File Naming

### Page HTML

- `source.html`

If multiple HTML pages are fetched from the same bundle:

- `source-01.html`
- `source-02.html`

### PDFs

Use a short deterministic descriptive slug.

Examples:

- `staff-report.pdf`
- `agenda.pdf`
- `packet.pdf`
- `minutes.pdf`
- `ordinance-2035.pdf`
- `attachment-01-contract-fs-global.pdf`

### JSON API Responses

- `response.json`
- `response-01.json`

### Screenshots

- `screenshot-01.png`
- `screenshot-02.png`

Use screenshots only when they add debugging or provenance value.

## Per-Capture Manifest

Every raw capture directory should contain a `manifest.json`.

Suggested shape:

```json
{
  "source_id": "san-rafael-aug-19-2024-staff-report",
  "capture_id": "san-rafael-aug-19-2024-staff-report__2026-04-10",
  "captured_at": "2026-04-10T20:15:00Z",
  "entry_url": "https://www.cityofsanrafael.org/documents/august-19-2024-staff-report-camping-ordinance-amendments-report-on-homelessness/",
  "fetch_strategy": "static_html",
  "artifacts": [
    {
      "path": "source.html",
      "content_type": "text/html"
    },
    {
      "path": "staff-report.pdf",
      "content_type": "application/pdf"
    }
  ],
  "notes": [
    "Attachment links discovered from landing page."
  ]
}
```

Optional upgrade fields:

```json
{
  "capture_quality": "proxy_text",
  "supersedes_capture_id": "san-rafael-aug-19-2024-staff-report__2026-04-10",
  "replacement_reason": "direct_pdf_available"
}
```

## Bundle IDs

When a capture belongs to a specific case-study collection effort, assign a bundle ID.

Suggested format:

- `<case_study_id>__bundle-01`

Example:

- `san-rafael-homelessness-01__bundle-01`

This is useful when several `source_id`s are captured together as one working set.

## Raw vs Extracted vs Normalized

### Raw

Unchanged artifacts fetched from the source surface.

Examples:

- HTML
- PDF
- JSON
- images

### Extracted

Machine-readable output derived from raw artifacts.

Examples:

- extracted text
- section map
- table extraction
- quote blocks

### Normalized

Case-study or graph-ready candidate objects.

Examples:

- `Meeting` candidate
- `AgendaItem` candidate
- `MoneyFlow` candidate
- `ArticleMention` candidate

## Proxy To Direct Replacement

Sometimes the environment only permits a proxy capture:

- browser-visible text snapshot
- `r.jina.ai` text proxy
- OCR fallback

Later, the same source surface may become directly fetchable as raw HTML or PDF.

When that happens:

1. Keep the same `source_id`.
2. Create a new raw capture directory with a new `capture_id`.
3. Do not overwrite or delete the old proxy capture.
4. Mark the new manifest as superseding the older capture when practical.
5. Rerun extraction from the newer artifact.
6. Update normalized references only if the newer capture is the same semantic record.

This is an evidence upgrade, not a new source identity.

### What Stays Stable

- `source_id`
- graph `record_id` for the same underlying record
- higher-level joins like `decision_id`, `agreement_id`, `project_id`

### What Can Change

- `capture_id`
- `fetch_strategy`
- preferred `artifact_path` in normalized output
- extraction output derived from the improved artifact

### When To Mint A New Record

Do create a new `record-*` ID if the better artifact reveals that the old object boundary was wrong.

Examples:

- a proxy page really represented two separate attachments
- a packet-level proxy gets replaced by a specific child contract PDF
- a meeting-page proxy turns out to contain several distinct legislative records

In that case:

- keep the old raw capture for provenance
- keep or retire the older record node intentionally
- create new child `record-*` objects for the more precise artifacts

## Naming Rules

- use lowercase ASCII
- use hyphens, not spaces
- keep names stable across reruns
- include explicit dates in filenames only when the file itself represents a dated object

## What Not To Do

- do not save extracted text on top of raw HTML
- do not rename files casually after review
- do not use vague names like `file1.pdf` or `stuff.pdf`
- do not mix unrelated source captures into the same directory

## Initial Recommendation

For the first live collection pass:

- create one raw capture directory per `source_id`
- group the first set mentally under the case-study bundle
- only add extracted and normalized layers after the raw set is stable
