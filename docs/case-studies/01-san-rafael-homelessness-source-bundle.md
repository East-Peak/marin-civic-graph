# Case Study 01 Source Bundle

Date drafted: April 10, 2026

This document defines the first concrete artifact bundle to collect for Case Study 01.

Reference:

- [Case Study 01](./01-san-rafael-homelessness.md)
- [Ingestion Checklist](./01-san-rafael-homelessness-ingestion-checklist.md)
- [Artifact Conventions](../artifact-conventions.md)

## Bundle ID

- `san-rafael-homelessness-01__bundle-01`

## Goal

Assemble the smallest raw source set that can support the first real end-to-end extraction pass.

This bundle should be enough to produce:

- one official timeline
- one August 19, 2024 meeting package
- one first-pass actor table
- one first-pass place table
- one first-pass money-flow set

## Status

Bundle 01 was started on April 10, 2026.

Captured so far:

- August 19, 2024 meeting page
- August 19, 2024 agenda PDF
- August 19, 2024 packet PDF
- August 19, 2024 minutes PDF
- August 19, 2024 staff report landing page
- August 19, 2024 staff report PDF
- August 19, 2024 item 5.a report PDF
- August 19, 2024 item 5.a public comment PDFs
- camping ordinance implementation page
- `Boyd` dismissal news release page
- `Grants Pass` statement page
- `Grants Pass` explainer page
- sanctioned camping area page
- June 2024 homelessness update page
- November 21, 2024 homelessness update page
- January 24, 2025 homelessness update page
- San Francisco City Attorney `Grants Pass` amicus page
- San Rafael disclosures page
- Marin County campaign finance NetFile landing page

## Priority Order

1. August 19, 2024 meeting package
2. litigation / legal-framing pages
3. implementation and sanctioned-camping program pages
4. update pages that extend the timeline
5. media citations and articles

## Bundle Contents

### A. August 19, 2024 Meeting Package

These are the highest-value artifacts in the first bundle.

- [x] meeting page
  - source ID: `san-rafael-aug-19-2024-council-meeting`
  - URL: https://www.cityofsanrafael.org/meetings/city-council-august-19-2024/
  - expected artifacts:
    - `source.html`
    - any linked agenda / packet / video URLs in manifest

- [x] staff report landing page
  - source ID: `san-rafael-aug-19-2024-staff-report`
  - URL: https://www.cityofsanrafael.org/documents/august-19-2024-staff-report-camping-ordinance-amendments-report-on-homelessness/
  - expected artifacts:
    - `source.html`
    - `staff-report.pdf`
    - linked attachments if available

- [x] agenda PDF if separately linked
  - expected filename: `agenda.pdf`

- [x] packet PDF if separately linked
  - expected filename: `packet.pdf`

- [x] minutes if separately linked
  - expected filename: `minutes.pdf` or `minutes.html`

- [x] meeting video URL capture
  - expected storage:
    - URL in manifest
    - screenshot only if page structure is fragile

### B. Legal / Litigation Framing

- [x] `Grants Pass` statement page
  - source ID: `san-rafael-grants-pass-statement`
  - URL: https://www.cityofsanrafael.org/city-of-san-rafael-statement-on-grants-pass-decision/
  - expected artifact:
    - `source.html`

- [x] `Grants Pass` explainer / FAQ page
  - source ID: `san-rafael-grants-pass-explainer`
  - URL: https://www.cityofsanrafael.org/supreme-courts-grants-pass-ruling-its-effect-on-san-rafaels-encampment-policy/
  - expected artifact:
    - `source.html`

- [x] `Boyd` dismissal news release
  - source ID: `san-rafael-boyd-dismissal-news-release`
  - URL: https://www.cityofsanrafael.org/news-release-federal-judge-dismisses-lawsuit-limiting-city-regulation-of-camping-on-public-property/
  - expected artifact:
    - `source.html`

- [x] San Francisco City Attorney amicus post
  - source ID: `sf-city-attorney-grants-pass-amicus`
  - URL: https://sfcityattorney.org/san-francisco-files-amicus-brief-with-u-s-supreme-court-in-grants-pass/
  - expected artifact:
    - `source.html`

### C. Implementation / Program Pages

- [x] implementation approach page
  - source ID: `san-rafael-camping-implementation-plan`
  - URL: https://www.cityofsanrafael.org/camping-ordinance-implementation-approach-plan/
  - expected artifact:
    - `source.html`
  - high-value details:
    - named nonprofit partners
    - site-specific restrictions
    - gift-card / free-food references

- [x] sanctioned camping area page
  - source ID: `san-rafael-sanctioned-camping-area`
  - URL: https://www.cityofsanrafael.org/sanctioned-camping-area/
  - expected artifact:
    - `source.html`

### D. Timeline Update Pages

- [x] June 2024 update
  - source ID: `san-rafael-homelessness-update-june-2024`
  - URL: https://www.cityofsanrafael.org/homelessness-update-june-2024-2/
  - expected artifact:
    - `source.html`

- [x] November 21, 2024 update
  - source ID: `san-rafael-homelessness-update-nov-2024`
  - URL: https://www.cityofsanrafael.org/homelessness-news-update-november-21-2024/
  - expected artifact:
    - `source.html`

- [x] January 24, 2025 update
  - source ID: `san-rafael-homelessness-update-jan-2025`
  - URL: https://www.cityofsanrafael.org/homelessness-news-update-january-24-2025/
  - expected artifact:
    - `source.html`

### E. Context and Money Surfaces

- [x] San Rafael disclosures page
  - source ID: `san-rafael-disclosures`
  - URL: https://www.cityofsanrafael.org/disclosures/
  - expected artifact:
    - `source.html`

- [x] Marin County campaign finance portal landing page
  - source ID: `marin-county-campaign-finance-netfile`
  - URL: https://netfile.com/agency/cmar/
  - expected artifact:
    - `source.html`

### F. Local Media Layer

The first bundle should at minimum preserve citations even if full text is deferred.

- [ ] Marin IJ issue-specific article list
  - source ID: `marin-ij-homelessness-coverage`
  - expected artifacts:
    - citation list in manifest
    - article URLs
    - article titles
    - publication dates
    - paywall access notes

If operator-assisted access is available:

- [ ] capture full text or browser snapshots for a small first set of core articles

## Suggested Raw Storage Layout

```text
data/raw/
  san-rafael-aug-19-2024-council-meeting/
    2026-04-10/
      manifest.json
      source.html
  san-rafael-aug-19-2024-staff-report/
    2026-04-10/
      manifest.json
      source.html
      staff-report.pdf
```

## First Extraction Targets

Once the raw bundle exists, extract these first:

### From the August 19 package

- agenda item titles
- motions
- vote results
- contract names
- contract recipients
- grant references
- named working groups
- named places

### From implementation and update pages

- nonprofit partner names
- contractor names
- sanctioned-site opening date
- participant counts
- place names and restrictions

### From legal framing pages

- explicit claims about what `Grants Pass` changed
- explicit claims about why `Boyd` constrained the City
- dates of legal milestones

## First Normalization Targets

The first normalized objects from this bundle should be:

- 1 `Meeting`
- 3-10 `AgendaItem` candidates
- 3-8 `Decision` candidates
- 10-20 `Document` records
- 5-15 `Actor` seed records
- 5-10 `Place` records
- 3-10 `MoneyFlow` candidates

## Bundle Completion Definition

Bundle 01 is complete when:

- [x] all core official pages are captured raw
- [x] the August 19, 2024 package is materially complete
- [x] all known PDFs and attachment URLs from the meeting package are preserved
- [x] timeline update pages are captured
- [ ] at least a citation-level Marin IJ article list exists

## Known Gaps

- the relationship between the item-specific meeting PDF and the separate staff report PDF still needs review
- video export strategy is still open
- Marin IJ archive coverage will depend on operator access

## Recommended Immediate Next Action

Continue bundle 01 with:

1. citation-level Marin IJ article inventory
2. first extraction pass over the official bundle
3. review overlap between `item-5a-report.pdf`, `staff-report.pdf`, and `packet.pdf`

That should make bundle 01 complete enough to begin a disciplined first extraction and normalization pass.
