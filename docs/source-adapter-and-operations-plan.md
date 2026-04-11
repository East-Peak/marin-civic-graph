# Source Adapter And Operations Plan

Date drafted: April 11, 2026

This note captures a practical point that should shape the project early:

- each municipality stores public records differently
- each source family has its own access quirks
- the project needs both a historical backfill plan and an ongoing cron plan

The graph will only be as good as the source adapters behind it.

## Operating Assumption

For most source families, the long-term operating pattern should be:

1. discover and classify the source surface
2. document the source-specific quirks
3. run a historical backfill
4. switch the source to recurring sync

For Marin Civic Graph, the default historical target should be:

- backfill to at least `2019-01-01` where the archive supports it cleanly

Stretch goal:

- go earlier when a source has a durable archive and the records remain high value

## Why This Must Be Explicit

We already know the project is not scraping one platform.

It is scraping a mix of:

- WordPress pages
- Granicus / meeting packet surfaces
- NetFile portals
- Laserfiche public-records portals
- county pages with Cloudflare behavior
- PDF-first document archives
- city and county one-off landing pages

Those are different operational systems, not just different URLs.

## Source Profile Dimensions

Each source should eventually carry an explicit adapter profile.

At minimum, the profile should answer:

- `platform_family`
- `access_pattern`
- `change_signal`
- `archive_shape`
- `backfill_strategy`
- `cron_strategy`
- `known_quirks`

## Platform Families We Already Know About

### WordPress / ProudCity municipal pages

Examples:

- San Rafael city pages
- Marin IJ WordPress post API

Typical behavior:

- static HTML pages are fetchable
- some pages have useful WP JSON endpoints
- record links may still point to PDFs, storage buckets, or external portals

Useful strategies:

- `static_html`
- `json`

Typical change signals:

- page modified timestamps
- new post IDs
- updated linked PDFs

### Laserfiche public-records portals

Examples:

- San Rafael public records
- local Form 803 discovery

Typical behavior:

- anonymous public access exists
- direct page browsing may fail without a session cookie
- public JSON endpoints can still work after bootstrap
- OCR text and metadata are available through service endpoints

Useful strategies:

- `cookie_aware_json`

Typical change signals:

- new search results for known terms
- new entry IDs in a filing folder

Known quirks:

- browser-looking session bootstrap is required
- searches can be noisy without exact term discipline
- OCR quality can be good enough for first-pass extraction but not always enough for checkbox-level precision

### NetFile / campaign disclosure portals

Examples:

- Marin County campaign portal
- San Rafael SEI portal

Typical behavior:

- ASP.NET form state
- search requires cookies and postback handling
- RSS feeds help for recent filings
- direct document images are stable once the image ID is known

Useful strategies:

- `rss`
- `cookie_aware_json`
- `pdf_download`

Typical change signals:

- new RSS items
- new committee filings
- new disclosure filings

Known quirks:

- search mechanics differ from document download mechanics
- local campaign and local disclosure surfaces may not be the same portal
- same jurisdiction may split campaign, Form 700, and Form 803 across different systems

### Granicus / agenda packet surfaces

Examples:

- Marin County Board materials

Typical behavior:

- meeting pages are stable
- packets and attachments are high-value child records
- item IDs and attachment boundaries matter

Useful strategies:

- `static_html`
- `pdf_download`

Typical change signals:

- new meeting page
- revised packet
- added attachment

### Cloudflare-blocked county pages

Examples:

- several Marin County planning pages in this environment

Typical behavior:

- public page is visible in browser
- direct CLI fetch may be blocked

Useful strategies:

- `text_proxy`
- later upgrade to direct capture when possible

Known quirks:

- capture should stay transparent about being a proxy
- do not pretend a text snapshot is the original artifact

## Municipality And Institution Profiles

The registry should not just list sources. It should accumulate source behavior by owner.

For each municipality or county family, we eventually want a profile covering:

- where meetings live
- where filings live
- where public records live
- whether permits are on a separate system
- whether search requires cookies, browser assist, or text proxy
- whether records are indexed by date, folder, committee, project number, or document ID

Early examples already visible in the project:

- `San Rafael`
  - city pages are mostly straightforward WordPress / ProudCity
  - disclosures and financial filings route through Laserfiche
  - some campaign/disclosure surfaces split between NetFile and Laserfiche
- `Marin County`
  - campaign filings route through NetFile
  - BOS materials are on county / Granicus-like meeting surfaces
  - some planning pages are browser-visible but CLI-blocked here

## Historical Backfill Plan

The project should treat historical collection as a first-class stage, not a cleanup task.

### Default target

- `2019-01-01` forward for most recurring civic surfaces

### Priority order

1. meetings and agenda materials
2. ordinances and resolutions
3. contracts, grants, and amendments
4. campaign and disclosure filings
5. permit and application threads
6. legal and oversight records
7. media enrichment

### Backfill modes

- `archive_sweep`
  - crawl known archive pages by year / month / meeting date
- `rss_replay`
  - use feed history where still exposed
- `folder_walk`
  - enumerate public-records folders by entry ID or listing pages
- `document_chain_backfill`
  - start from a known project, case, or meeting and pull linked child records backward

## Cron Plan

After initial backfill, each source should move to recurring sync.

### Default recurring cadence

- `weekly` for most stable municipal record surfaces

### Faster cadence where justified

- `daily`
  - active meeting calendars
  - campaign filing feeds near elections
  - public-records search surfaces that change frequently

- `monthly`
  - slow-changing guidance or archive index pages

### Cron outputs

Each run should produce:

- new capture manifest
- diffable normalized output
- explicit note when the source shape changed

## What To Capture In The Registry

The source registry should eventually carry enough information that a new adapter can be built without rediscovering the source manually.

That means each source entry should know:

- platform family
- backfill start target
- recurring cadence
- known quirks
- preferred discovery path
- preferred artifact format

## Immediate Project Implications

The next source-registry iteration should stop being only a source list.

It should start acting like an operations registry for:

- source-specific idiosyncrasies
- historical backfill planning
- recurring sync planning

That is the layer that makes large-scale five-year ingestion practical.
