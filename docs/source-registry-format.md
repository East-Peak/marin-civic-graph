# Source Registry Format

Date drafted: April 10, 2026

This document defines the source-manifest format for Marin Civic Graph.

The registry is the canonical inventory of source surfaces.

It should answer:

- what this source is
- who owns it
- what it exposes
- how to fetch it
- how often to check it
- how far back we intend to backfill it
- what platform quirks it has
- what risks it carries

## Core Principles

- one row or document per source surface
- one stable `source_id`
- one explicit fetch strategy
- one explicit object expectation list
- one explicit review-risk classification

The registry should be human-readable first and machine-usable second.

## Suggested Shape

```yaml
source_id: san-rafael-city-council-meetings
label: San Rafael City Council Meetings
owner_type: institution
owner_id: san-rafael-city-council
jurisdiction_id: san-rafael
case_study_ids:
  - san-rafael-homelessness-01
source_category: meetings
source_type: html_index
entry_url: https://www.cityofsanrafael.org/city-council-meetings/
discovery_urls:
  - https://www.cityofsanrafael.org/departments/public-meetings/
fetch_strategy: static_html
browser_required: false
expected_objects:
  - meeting
  - document:agenda
  - document:packet
  - document:minutes
  - document:video
cadence: daily
history_depth: archive
backfill_start_target: 2019-01-01
platform_family: wordpress_proudcity
access_pattern: static_public_page
change_signal: new_meeting_page_or_updated_packet
source_tier_default: B
robots_notes: allow
auth_required: false
review_risk: low
dedupe_key_strategy: url_plus_meeting_date
known_quirks: []
notes:
  - Stable city page with archive links.
  - High-value source for v1.
```

## Required Fields

### Identity

- `source_id`
- `label`
- `owner_type`
- `owner_id`
- `jurisdiction_id`
- `case_study_ids`

### Classification

- `source_category`
- `source_type`
- `expected_objects`

### Access

- `entry_url`
- `fetch_strategy`
- `browser_required`
- `auth_required`

### Operations

- `cadence`
- `history_depth`
- `backfill_start_target`
- `platform_family`
- `access_pattern`
- `change_signal`
- `review_risk`
- `dedupe_key_strategy`

## Field Definitions

### `source_id`

Stable machine-friendly ID.

Rule:

- never reuse for a different source
- if the same source moves URLs but is functionally the same, keep the ID

### `owner_type`

Allowed values:

- `institution`
- `actor`
- `jurisdiction`
- `external`

### `source_category`

Examples:

- `meetings`
- `official_communications`
- `disclosures`
- `campaign_finance`
- `contracts`
- `grants`
- `media`
- `litigation`

### `source_type`

Examples:

- `rss`
- `json_api`
- `html_index`
- `pdf_index`
- `legistar`
- `campaign_portal`
- `guidance_page`
- `article`
- `article_archive`
- `document_landing_page`

### `fetch_strategy`

Allowed values for v1:

- `rss`
- `json`
- `cookie_aware_json`
- `static_html`
- `pdf_download`
- `text_proxy`
- `browser_assisted`
- `manual_operator`

Notes:

- use `text_proxy` when the official source is public but direct CLI fetch is blocked and a transparent text mirror is temporarily required
- use `cookie_aware_json` when an official public site exposes anonymous JSON endpoints only after session bootstrap or cookie setup
- if later direct fetch becomes possible, keep the same `source_id` and change the fetch strategy on the next capture rather than creating a new source entry

### `expected_objects`

List of object families we expect to derive from this source.

Examples:

- `meeting`
- `agenda_item`
- `decision`
- `claim`
- `document:agenda`
- `document:packet`
- `document:minutes`
- `document:video`
- `money_flow:campaign_contribution`
- `money_flow:contract`
- `article_mention`

### `cadence`

Suggested values:

- `hourly`
- `daily`
- `weekly`
- `monthly`
- `election_cycle`
- `manual`

Operational note:

- for long-running recurring collection, `weekly` should be treated as the default floor for stable civic record surfaces
- use `daily` only where the source actually changes often enough to justify it

### `history_depth`

Suggested values:

- `latest_only`
- `rolling_window`
- `archive`

### `backfill_start_target`

The earliest date we intend to backfill to for this source, when known.

Examples:

- `2019-01-01`
- `2020-01-01`
- `archive_start_unknown`

Operational note:

- the project default for recurring civic surfaces should be at least `2019-01-01` unless the source family is lower value or the archive shape makes that unrealistic

### `platform_family`

Examples:

- `wordpress_proudcity`
- `laserfiche_public_records`
- `netfile_campaign_portal`
- `granicus_meeting_portal`
- `cloudflare_blocked_html`
- `pdf_first_archive`

### `access_pattern`

Examples:

- `static_public_page`
- `cookie_bootstrap_required`
- `rss_plus_direct_document`
- `browser_visible_cli_blocked`
- `public_search_portal`

### `change_signal`

Examples:

- `new_rss_item`
- `new_meeting_page_or_updated_packet`
- `new_folder_entry`
- `new_filing_image`
- `manual_archive_sweep`

### `review_risk`

Suggested values:

- `low`
- `medium`
- `high`

Examples:

- `low`: stable official meeting page
- `medium`: awkward PDF archive with changing titles
- `high`: quote-heavy local media requiring affiliation review

## Optional Fields

- `discovery_urls`
- `publisher`
- `source_tier_default`
- `robots_notes`
- `paywall_status`
- `login_owner`
- `jurisdiction_scope`
- `place_scope`
- `known_quirks`
- `notes`

## `case_study_ids`

Use this field when a source is directly tied to one or more named case studies.

Examples:

- `san-rafael-homelessness-01`

This is mainly a planning and scoping convenience.

## Paywall / Auth Fields

When access is limited, capture it explicitly.

### `paywall_status`

Suggested values:

- `none`
- `soft_paywall`
- `hard_paywall`
- `mixed_archive`

### `login_owner`

Examples:

- `project`
- `operator`
- `subscription_required`

This is especially relevant for local media like Marin IJ.

## Minimal v1 Registry Coverage

The first registry should include:

- Marin County Board of Supervisors meetings
- Marin County campaign finance portal
- San Rafael City Council meetings
- San Rafael boards and commissions index
- San Rafael disclosures page
- San Rafael sanctioned camping / homelessness update pages
- Marin IJ local coverage entry points

## Storage Recommendation

For planning:

- keep the registry in markdown or YAML

For implementation:

- use one registry file plus per-source detail files if the list grows large

The registry should be editable without any database.
