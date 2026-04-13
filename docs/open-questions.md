# Open Questions

This file is the centralized register for unresolved source ambiguities and modeling questions.

It exists because these issues were starting to spread across:

- normalized JSON `open_questions` arrays
- backlog items
- workspace project notes
- chat history

## How To Use This File

Use this register for questions that are:

- active
- high-signal
- likely to affect joins, identity, or promotion logic

Do not use it for general wishlist work. That still belongs in [backlog.md](./backlog.md).

## Logging Rules

Keep the most local question close to the source artifact:

- source-specific ambiguity stays in the relevant normalized JSON
- case-specific ambiguity can also live in a case-study doc

Mirror the question here when it affects:

- identity resolution
- graph joins
- record promotion
- object boundaries
- methodology

## Status Labels

- `open`: unresolved and still blocking or distorting modeling
- `watch`: unresolved but not currently blocking
- `resolved`: answered well enough to remove from active review
- `dropped`: no longer worth pursuing

## Active Register

### OQ-001: 700 Irwin hearing date mismatch

- `status`: open
- `layer`: permit thread / join integrity
- `scope`: `project-700-irwin-st`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/permit-sample-basket-01/bundle-01.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-700-irwin-public-hearing-notice/2026-04-10/source.html)
- `question`: The hearing notice body says January 13, 2025, but the project timeline and posting chronology strongly suggest January 13, 2026. Which hearing date is correct?
- `why it matters`: This affects the meeting join and any later decision chain tied to the project.
- `next evidence`: capture the linked meeting page or agenda where the hearing is listed officially.

### OQ-002: P5139 object boundary

- `status`: watch
- `layer`: permit schema
- `scope`: `project-metropolis-san-pedro-road-p5139`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/permit-sample-basket-01/bundle-01.json)
- `question`: Should `P5139` remain one `Application` with multiple permit signals, or should it split into child application / permit objects?
- `why it matters`: This is a direct pressure test of whether the permit layer distinguishes `Application` from `Permit` cleanly enough.
- `next evidence`: collect later hearing or decision records for `P5139` and see how the county actually refers to each requested approval.

### OQ-003: P4134 actor-role drift

- `status`: open
- `layer`: identity / joins
- `scope`: `project-souang-p4134`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/permit-sample-basket-01/bundle-01.json)
  - [p4134-appeal-chain.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/permit-sample-basket-01/p4134-appeal-chain.json)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-p4134-hcr-decision/2026-04-10/source.txt)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-p4134-reilly-appeal-attachment/2026-04-10/source.txt)
- `question`: The project page names `John Bogdsarian` as applicant, the HCR decision names `Steve Reilly` as applicant, and the appeal filing identifies `330 Land Co. / Lucas Valley Road, LLC` as appellant. Which roles are principal owner, applicant, representative, and appellant?
- `why it matters`: This is a live test of how the graph should separate owner, applicant, representative, and appellant roles instead of collapsing them onto one `Actor`.
- `next evidence`: inspect the remaining P4134 child records and later Board materials for signature blocks, owner labels, counsel labels, and applicant declarations.

### OQ-004: P4134 hearing-page description mismatch

- `status`: open
- `layer`: source reliability
- `scope`: `meeting-2025-12-08-marin-county-planning-commission-p4134-appeal`
- `source refs`:
  - [p4134-appeal-chain.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/permit-sample-basket-01/p4134-appeal-chain.json)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-p4134-planning-commission-hearing/2026-04-10/source.txt)
- `question`: Why does the December 8, 2025 hearing page describe the matter as a `Reilly Appeal of Sicular Environmental Consulting Proposal...` while surfacing Souang housing-project attachments on the same page?
- `why it matters`: The graph needs to preserve source inconsistency without silently normalizing away a potentially meaningful mismatch.
- `next evidence`: compare the staff report, signed resolution, and agenda text to see whether the mismatch is just bad labeling or evidence of a narrower appeal subject.

### OQ-005: P4134 scope of the May 14 determination

- `status`: open
- `layer`: object boundary
- `scope`: `determination-p4134-hcr-ministerial-decision-2025-05-14`
- `source refs`:
  - [p4134-appeal-chain.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/permit-sample-basket-01/p4134-appeal-chain.json)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-p4134-hcr-decision/2026-04-10/source.txt)
- `question`: Did the May 14, 2025 Housing Compliance Review determination only resolve the HCR component, or did it also effectively resolve parts of the Vesting Tentative Map and Tree Removal thread?
- `why it matters`: This determines whether the graph needs one `Determination` node here or several related child determinations.
- `next evidence`: extract the decision’s conditions and operative findings, then compare them with later appeal and resolution language.

### OQ-006: P4134 final Board outcome

- `status`: open
- `layer`: missing outcome record
- `scope`: `meeting-2026-03-10-marin-county-board-of-supervisors-p4134`
- `source refs`:
  - [p4134-appeal-chain.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/permit-sample-basket-01/p4134-appeal-chain.json)
- `question`: What was the final Board of Supervisors action on March 10, 2026?
- `why it matters`: The appeal chain is still missing its final outcome node.
- `next evidence`: capture the Board-hearing attachments and final resolution or minutes.

### OQ-007: Marin IJ body-extraction threshold

- `status`: resolved
- `layer`: media methodology
- `scope`: case study 01
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/bundle-01.json)
  - [media-attribution-rules.md](/Users/tammypais/projects/marin-civic-graph/docs/media-attribution-rules.md)
  - [manifest.json](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-ij-2024-08-24-mahon-creek-article/2026-04-11/manifest.json)
  - [2026-04-11.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/marin-ij-2024-08-24-mahon-creek-article/2026-04-11.json)
  - [marin-ij-2024-08-24-mention-claim-example.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/marin-ij-2024-08-24-mention-claim-example.json)
- `question`: When do citation-only Marin IJ records graduate into full article-body extraction and quote isolation?
- `why it matters`: This determines when `ArticleMention` and attribution-gap work can become evidence-bearing instead of remaining citation-level.
- `resolution note`: Resolved with the first public WordPress API capture for the August 24, 2024 Mahon Creek article. Citation-only Marin IJ records can graduate when a reproducible article-body surface exists, either through the public post API or a later operator-assisted path. The first worked example now supports mixed outcomes in one article: canonical actor join, case-scoped actor join, and hold-for-review mentions.

### OQ-008: San Rafael councilmember seed resolution

- `status`: resolved
- `layer`: identity resolution
- `scope`: case study 01
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/bundle-01.json)
  - [canonical-seeds-san-rafael-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/canonical-seeds-san-rafael-01.json)
- `question`: How should raw councilmember labels from official records resolve into canonical person records without hand-wavy matching?
- `why it matters`: This is the same join problem that will recur across meetings, votes, appointments, and disclosures.
- `resolution note`: Resolved with the first evidence-backed San Rafael canonical seed bundle. The August 19, 2024 official roster labels now resolve to full-name actor seeds such as `actor-kate-colin`, `actor-eli-hill`, `actor-maribeth-bushey`, `actor-rachel-kertz`, and `actor-maika-llorens-gulati`. The role relationship is preserved as a claim, while seat, district, and term structure remain out of scope until stronger election or roster evidence is captured.

### OQ-017: San Rafael elected seat boundary

- `status`: resolved
- `layer`: seat modeling
- `scope`: `canonical-seeds-san-rafael-01`
- `source refs`:
  - [canonical-seeds-san-rafael-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/canonical-seeds-san-rafael-01.json)
  - [identity-resolution-submodel.md](/Users/tammypais/projects/marin-civic-graph/docs/identity-resolution-submodel.md)
- `question`: When should San Rafael elected identity seeds graduate into explicit seat and term objects rather than role-only claims?
- `why it matters`: Vote, election, and disclosure joins want durable seat objects and a clean separation between the underlying elected seat and transient leadership designations such as `Vice Mayor`.
- `resolution note`: Resolved with official San Rafael elected-official, City Council, and November 5, 2024 election pages. The graph now supports explicit seat candidates for the at-large Mayor and Districts 1-4, plus `SeatService` candidates for the current officeholders. `Vice Mayor` remains a role claim layered on Rachel Kertz's District 4 seat service, not a separate seat.

### OQ-018: San Rafael current council term boundaries

- `status`: resolved
- `layer`: term-boundary modeling
- `scope`: `canonical-seeds-san-rafael-01`
- `source refs`:
  - [canonical-seeds-san-rafael-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/canonical-seeds-san-rafael-01.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-page/2026-04-11/source.html)
  - [document.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-governance-protocols-2026/2026-04-11/document.pdf)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-2025-12-15-meeting-page/2026-04-12/source.html)
  - [cc-minutes-2025-12-15.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-2025-12-15-meeting-page/2026-04-12/cc-minutes-2025-12-15.pdf)
- `question`: What is the formal duration of the current Vice Mayor designation?
- `why it matters`: The underlying council seats are now stable enough that the remaining risk was overloading `Vice Mayor` as if it were a free-floating office instead of a bounded leadership designation layered on top of a current `SeatService`.
- `resolution note`: Resolved with the January 2026 City Council governance protocols and the December 15, 2025 regular City Council meeting materials. The governance protocols state that the Vice Mayor role rotates on an annual basis, and the December 15, 2025 meeting page and official minutes show that the Council elected Rachel Kertz as Vice Mayor for 2026. The graph should model this as an annual role claim layered on top of her District 4 `SeatService`, not as a separate seat.

### OQ-019: Marin County BOS source-scope boundary

- `status`: watch
- `layer`: source-scope integrity
- `scope`: `marin-county-bos-meetings`
- `source refs`:
  - [2026-04-11.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/marin-county-bos-meetings/2026-04-11.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-bos-meetings/2026-04-11/source.html)
- `question`: Should the direct BOS Granicus publisher view keep adjacent upcoming rows like `FLOOD MEETING 260414` and `HOUSING MEETING 260414` inside the source family, or should those rows be filtered into separate special-district source families?
- `why it matters`: The direct official publisher view is the best county meeting backbone, but its upcoming table may occasionally surface non-BOS governing-board items that could blur source boundaries if they are promoted without an explicit rule.
- `next evidence`: inspect whether those same adjacent rows recur in the archived year panels or whether they only appear in the upcoming table, then decide whether the source family should preserve them as `other` or carve them into separate district-specific adapters.

### OQ-020: San Rafael city-side campaign folder enumeration boundary

- `status`: resolved
- `layer`: source adapter / campaign backfill
- `scope`: `san-rafael-public-records-financial-filings-folder`, `san-rafael-public-records-independent-expenditures-folder`
- `source refs`:
  - [2026-04-11.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-side-campaign-filings/2026-04-11.json)
  - [folder-probe.json](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-public-records-financial-filings-folder/2026-04-11/folder-probe.json)
  - [folder-probe.json](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-public-records-independent-expenditures-folder/2026-04-11/folder-probe.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-elections-index/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-past-elections/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-june-7-2016-election/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-november-3-2020-election/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-november-8-2022-election/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-november-5-2024-election/2026-04-11/source.html)
- `question`: Should the city-side campaign backfill adapter rely permanently on election-page child-folder discovery, or is there a stable anonymous Laserfiche listing path for the filing folders themselves?
- `why it matters`: This determines whether historical city-side campaign backfill is `page-linked` only or can graduate into actual folder-enumerated filing capture.
- `resolution note`: Resolved in favor of a stable anonymous folder-listing path. The public Laserfiche Angular browse app uses `FolderListingService.aspx/GetFolderListing2` with a bootstrapped anonymous `WebLinkSession` cookie and the payload `{ repoName, folderId, getNewListing, start, end, sortColumn, sortAscending }`. That path now yields real folder contents for the city-side campaign filing folders, including city-office candidate folders, older shared committee folders, and the 2020/2022 independent-expenditure folders.

### OQ-021: San Rafael 2018 election filing URL typo

- `status`: resolved
- `layer`: source hygiene
- `scope`: `san-rafael-november-6-2018-election`
- `source refs`:
  - [2026-04-11.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-side-campaign-filings/2026-04-11.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-november-6-2018-election/2026-04-11/source.html)
- `question`: The 2018 election page publishes a `Financial Filings` browse URL with `repo=CityofSanRafaelv` instead of `repo=CityofSanRafael`. Should the adapter preserve that raw URL only, or canonicalize the repo parameter while keeping the same folder ID (`31078`)?
- `why it matters`: This is a source-quality issue rather than a graph-model blocker, but it affects whether later replay or browser automation should trust the page URL verbatim.
- `resolution note`: Resolved by separating provenance from execution. Preserve the raw published URL in the discovery record, but canonicalize the repo parameter to `CityofSanRafael` for actual Laserfiche service calls. Folder entry `31078` captures successfully through the canonical repo name and returns the shared committee folder contents.

### OQ-022: San Rafael election direct-record holdout

- `status`: watch
- `layer`: direct record capture / election records
- `scope`: `san-rafael-election-direct-records`
- `source refs`:
  - [2026-04-11.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-election-direct-records/2026-04-11.json)
  - [records.json](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-election-direct-records/2026-04-11/records.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-june-2-2026-special-municipal-election/2026-04-11/source.html)
- `question`: Why does entry `41998` (`Resolution Calling Election`) still return HTTP 500 on the public Laserfiche JSON follow-up path when `36` other election-linked `DocView` records captured successfully?
- `why it matters`: The direct `DocView` path is now the best page-linked record-capture route for San Rafael election pages, so understanding the single remaining holdout will tell us whether the gap is document-specific or a broader current-cycle edge case.
- `current note`: The first normalized election-record bundle can still promote the 2026 call-election chain because sibling entry `41989` already includes the staff report, Resolution `15511`, and the full text of the measure. Entry `41998` is now a completeness gap, not a blocker for the 2026 election decision.
- `next evidence`: retest entry `41998` with browser-visible session state and compare it to sibling entry `41989`, which was captured from the same June 2, 2026 special-election page.

### OQ-023: San Rafael Form 700 direct-document recovery boundary

- `status`: watch
- `layer`: disclosure adapter / evidence depth
- `scope`: `san-rafael-sei-netfile-portal`
- `source refs`:
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-sei-netfile-portal/2026-04-12.json)
  - [manifest.json](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-sei-netfile-portal/2026-04-12/manifest.json)
  - [form700-700-filers-export.xls](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-sei-netfile-portal/2026-04-12/form700-700-filers-export.xls)
- `question`: Is there a repeatable public path to mass direct-document recovery for historical San Rafael Form 700 filings, or does the NetFile export remain a metadata-first inventory while targeted filer/date searches are used only for selective document fetches?
- `why it matters`: The full-history export is strong enough for filing inventory, actor recurrence, and disclosure counts, but it only exposes direct document URLs on a small minority of rows. That is good enough for graph backfill, but not yet good enough for one-shot raw-PDF preservation of the whole visible archive.
- `current note`: The full visible-history export currently yields `1085` 700-filer rows from `2018-07-02` through `2026-04-08`, with only `16` rows exposing direct document links in the exported HTML. The direct-link layer is therefore materially weaker than the inventory layer. The first graph-facing import now uses a deliberately narrow officeholder-only continuity bundle with `9` promoted Form 700 filings and `9` `EconomicInterestDisclosure` nodes for current San Rafael elected officials, all backed by the export workbook rather than by direct row-level PDFs.
- `next evidence`: use the known working targeted historical-search payload to test whether row-level filer/date searches can promote direct `GetDocument.aspx` URLs at scale without relying on the export alone.

### OQ-024: San Rafael city-side campaign office-scope boundary

- `status`: watch
- `layer`: campaign discovery normalization
- `scope`: `san-rafael-city-campaign-discovery-01`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-discovery-01/bundle-01.json)
  - [2026-04-11.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-side-campaign-filings/2026-04-11.json)
  - [campaign-finance-disclosures-submodel.md](/Users/tammypais/projects/marin-civic-graph/docs/campaign-finance-disclosures-submodel.md)
- `question`: When should the San Rafael city-side campaign discovery layer promote school-board, city-attorney, and clerk-assessor rows into canonical seat and candidacy objects instead of leaving them as discovery-only filing-folder records?
- `why it matters`: The page-linked filing destinations are real public evidence, but the current canonical seat model only covers San Rafael Mayor and City Council seats. Promoting the other offices early would create joins into the wrong institution layer.
- `current note`: The discovery bundle now preserves all `27` candidate-folder destinations as `Record` refs, but only the `15` city-office rows from the 2020, 2022, and 2024 mayoral and council races are promoted into `Actor` and `Candidacy` candidates.
- `next evidence`: add canonical seat and institution coverage for San Rafael school-board, city-attorney, and clerk-assessor offices before promoting those filing-folder rows beyond discovery-only state.

### OQ-025: San Rafael city-side campaign direct-document recovery boundary

- `status`: resolved
- `layer`: campaign filing evidence depth
- `scope`: `san-rafael-city-campaign-filings-01`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-filings-01/bundle-01.json)
  - [folder-listings.json](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-campaign-folder-listings/2026-04-12/folder-listings.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-campaign-folder-listings/2026-04-12.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-campaign-document-probe/2026-04-12.json)
  - [campaign-form460-pdf-export.md](/Users/tammypais/projects/marin-civic-graph/docs/campaign-form460-pdf-export.md)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-campaign-form460-pdf-export/2026-04-12.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-form460-pdf-01/bundle-01.json)
- `question`: What is the repeatable public path from city-side campaign filing entry ids to raw filing artifacts such as PDF or page-image assets beyond the now-proven metadata / page-count / OCR path?
- `why it matters`: Exact accounting and stronger evidence preservation are better with raw filing artifacts than with OCR text alone.
- `current note`: The repeatable public path is now proven for selected filings. A warmed anonymous session can start an export with `ZipEntriesHandler.aspx/StartExport`, poll `CheckExportStatus`, and download the actual filing PDF from `ExportJobHandler.aspx/GetExportJob`. The three selected Form 460 filings (`37677`, `37685`, `37365`) are now preserved as raw PDFs in the repo.
- `next evidence`: expand the same export workflow to broader city-side filing families when the project needs exact-accounting QA beyond the current high-value subset.

### OQ-026: San Rafael John Gamblin campaign folder dead link

- `status`: watch
- `layer`: campaign discovery integrity
- `scope`: `record-san-rafael-november-3-2020-election-john-gamblin-campaign-folder`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-discovery-01/bundle-01.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-campaign-folder-listings/2026-04-12.json)
- `question`: Why does candidate folder entry `31431` for `John Gamblin` return `Entry not found. [9001]` when the sibling 2020 city-office campaign folders resolve successfully?

### OQ-027: San Rafael Form 460 OCR completeness gap

- `status`: watch
- `layer`: campaign filing extraction quality
- `scope`: `san-rafael-city-campaign-form460-schedules-01`
- `source refs`:
  - [campaign-form460-schedule-extraction.md](/Users/tammypais/projects/marin-civic-graph/docs/campaign-form460-schedule-extraction.md)
  - [reconciliation-and-anomaly-model.md](/Users/tammypais/projects/marin-civic-graph/docs/reconciliation-and-anomaly-model.md)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-campaign-form460-schedules/2026-04-12.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-form460-schedules-01/bundle-01.json)
- `question`: How should the project treat the remaining contribution-side gap when `37685` and `37365` now reconcile exactly to the official `Schedule A Summary` itemized totals, but `37677` still trails its itemized summary by `$1,000.00`?
- `why it matters`: The project can now trust the payment-side extraction and most of the contribution-side extraction much more than before, but it still should not claim exact full-filing donor coverage on the Kate Colin filing without a tighter row parser.
- `current note`: The current schedule bundle now emits explicit `ValidationCheck` objects. `37677` remains the only contribution-side `extraction_gap`; the other filing-level reconciliation and summary-rollup checks reconcile cleanly. On the contribution side, `37677` improves to `$14,992.00` extracted itemized contributions against `$15,992.00` reported itemized contributions, with `$400.00` explicitly preserved as unitemized contributions.
- `next evidence`: add a page-specific patch for the remaining malformed Kate Colin `Schedule A` rows or introduce a stronger PDF-assisted parser for first-row and bad-date OCR edge cases before making exact-accounting or exhaustive-donor claims.

### OQ-028: Graph-v1 campaign evidence record completeness

- `status`: resolved
- `layer`: graph materialization / evidence completeness
- `scope`: `graph-v1`
- `source refs`:
  - [import-manifest.yaml](/Users/tammypais/projects/marin-civic-graph/registry/import-manifest.yaml)
  - [report.json](/Users/tammypais/projects/marin-civic-graph/data/projected/graph-v1/report.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-form460-schedules-01/bundle-01.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-filings-01/bundle-01.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-records-01/bundle-01.json)
- `question`: Should graph-v1 add normalized `Record` nodes for city-side campaign OCR, PDF, and folder artifacts that are already referenced from `Filing`, `MoneyFlow`, and `ValidationCheck` evidence arrays but are not yet promoted as standalone normalized records?
- `why it matters`: The current projection is structurally correct and the smoke checks pass, but the report still skips a large number of `missing_target:Record` edges because those evidence artifacts exist only as referenced IDs, not as normalized `Record` objects inside the narrowed v1 import scope.
- `resolution note`: Resolved with `san-rafael-city-campaign-records-01`, which now promotes `25` durable campaign evidence records drawn from already-referenced OCR, PDF, and folder artifacts. After adding that bundle to graph-v1 and folding in the John Gamblin folder record referenced by the actor supplement, the projection report no longer has a `missing_target:Record` category.

### OQ-029: Graph-v1 actor completeness after the issue supplement

- `status`: watch
- `layer`: graph materialization / identity completeness
- `scope`: `graph-v1`
- `source refs`:
  - [report.json](/Users/tammypais/projects/marin-civic-graph/data/projected/graph-v1/report.json)
  - [canonical-issues-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/canonical-issues-01.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-actors-01/bundle-01.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-discovery-01/bundle-01.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-ie-01/bundle-01.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/bundle-01.json)
- `question`: After promoting a narrow actor and issue supplement, which remaining `Actor` misses deserve first-class graph-v1 nodes, and which should stay out until a stronger canonical or parser-cleanup layer exists?
- `why it matters`: The issue side is now clean, but the graph still skips a material number of actor edges. Most of the remaining misses are not strong canonical targets. They are OCR-tainted vendors, payment platforms, PAC labels, or older raw role placeholders like `actor-mayor-kate`.
- `current note`: The current graph-v1 report now shows `missing_target:Actor = 147`, with no remaining `missing_target:Issue` or `missing_target:Record` categories. The highest-repeat skipped actor IDs are `actor-anedot`, `actor-four-waters-media-inc`, `actor-pmcohen-public-affairs`, and a small cluster of council role aliases from the homelessness bundle.
- `next evidence`: decide whether the next follow-up is a narrow actor-alias cleanup for existing official officeholders, a vendor/platform supplement for campaign finance analytics, or a stricter parser cleanup that keeps OCR-tainted actors out of graph-v1 entirely.

### OQ-030: Boyd operative-order gap

- `status`: resolved
- `layer`: legal / precedent normalization
- `scope`: `legal-precedent-01`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/legal-precedent-01/bundle-01.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-boyd-tro-order/2026-04-12.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-boyd-preliminary-injunction-order/2026-04-12.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-boyd-dismissal-order/2026-04-12.json)
  - [order.txt](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-boyd-dismissal-order/order.txt)
  - [judicial-pressure-test-basket-ingestion-checklist.md](/Users/tammypais/projects/marin-civic-graph/docs/judicial-pressure-test-basket-ingestion-checklist.md)
- `question`: Where can the project capture the operative August 2023 TRO order and the October 19, 2023 preliminary-injunction order as direct court-origin records for `Boyd v. City of San Rafael`?
- `why it matters`: The first normalized legal bundle needed the actual operative order texts for the injunction stages, not just later city summaries.
- `resolution note`: Resolved well enough for the current legal lane. `legal-precedent-01` now includes separate TRO and preliminary-injunction `legal_record` nodes backed by strong public filed-order copies, plus the direct city-linked dismissal order. The remaining Boyd issue is provenance strength, not missing order text.

### OQ-031: Grants Pass lower-court chain depth

- `status`: resolved
- `layer`: legal / precedent normalization
- `scope`: `legal-precedent-02`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/legal-precedent-02/bundle-01.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/grants-pass-district-opinion-order/2026-04-12.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/grants-pass-district-judgment/2026-04-12.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/ninth-circuit-grants-pass-amended-opinion/2026-04-12.json)
  - [legal-precedent-02.md](/Users/tammypais/projects/marin-civic-graph/docs/legal-precedent-02.md)
- `question`: Should the repo pull the district-court injunction and Ninth Circuit opinion that the Supreme Court reversed and remanded into the same Grants Pass bundle, or leave them for a lower-court companion bundle?
- `why it matters`: The legal lane needed a stable way to represent district, appellate, and Supreme Court phases without collapsing them into one case node.
- `resolution note`: Resolved in favor of keeping the lower-court chain inside `legal-precedent-02` as separate but related `Case` objects. The bundle now includes the District of Oregon opinion and judgment, the official Ninth Circuit amended opinion, and a case-lineage crosswalk through the Supreme Court phase.

### OQ-032: Grants Pass supporting-provenance gap

- `status`: watch
- `layer`: legal / precedent completeness
- `scope`: `legal-precedent-02`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/legal-precedent-02/bundle-01.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/grants-pass-district-opinion-order/2026-04-12.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/grants-pass-district-judgment/2026-04-12.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/ninth-circuit-grants-pass-amended-opinion/2026-04-12.json)
  - [legal-precedent-02.md](/Users/tammypais/projects/marin-civic-graph/docs/legal-precedent-02.md)
- `question`: Do we need the San Francisco amicus brief PDF itself or a direct district-court docket surface before `legal-precedent-02` is strong enough for import?
- `why it matters`: The core precedent chain is now real, so the remaining question is provenance and completeness of supporting advocacy and docket surfaces rather than whether the legal model works.
- `next evidence`: capture the public amicus-brief PDF linked from the SF City Attorney page and, if a stable free district docket path is available, add it without disturbing the current case and record IDs.

### OQ-016: San Rafael local Form 803 filing surface

- `status`: resolved
- `layer`: disclosure surface discovery
- `scope`: `campaign-finance-form-803-slice-01`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/campaign-finance-form-803-slice-01/bundle-01.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-disclosures/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-sei-netfile-portal/2026-04-11/source.html)
  - [document.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-governance-protocols-2026/2026-04-11/document.pdf)
  - [agenda-packet.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-2026-01-20-agenda-packet/2026-04-11/agenda-packet.pdf)
  - [search-results.json](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-public-records-form-803-search/2026-04-11/search-results.json)
  - [metadata.json](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-kate-colin-form-803-2025-09-04/2026-04-11/metadata.json)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-kate-colin-form-803-2025-09-04/2026-04-11/source.txt)
- `question`: What exact local San Rafael surface exposes filed Form 803 reports for local officials, if any?
- `why it matters`: The local-versus-state filing rule is now clear, but the project still lacks the first actual local Form 803 filing needed to promote a real behested-payment `Filing` and `MoneyFlow`.
- `resolution note`: Resolved through the San Rafael public Laserfiche portal. A quoted search for `Form 803` in the public records corpus returns `Form 803 - Kate Colin` as entry `41053`, and the same portal exposes both record metadata and extractable OCR page text through public JSON endpoints. That is strong enough to promote the first local `Filing` and `MoneyFlow: behested_payment` objects in the Form 803 slice.

### OQ-013: Mary Sackett seat and election boundary

- `status`: resolved
- `layer`: campaign joins
- `scope`: `committee-mary-sackett-for-marin-county-supervisor-2026`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/campaign-finance-sample-basket-01/bundle-01.json)
  - [filing.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-mary-sackett-form-497-2026-04-10/2026-04-11/filing.pdf)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-candidate-status-2026-06-02/2026-04-11/source.txt)
- `question`: What exact seat, district, and election context should the Mary Sackett committee and candidacy join to?
- `why it matters`: The current filing title is strong enough to justify a candidate-linked committee and candidacy candidate, but not yet strong enough to safely promote a fully resolved `Seat -> Election -> Candidacy` chain.
- `resolution note`: Resolved with the official Marin County candidate-status page for the June 2, 2026 Statewide Direct Primary Election. That page lists `Sackett, Mary**` under `County Supervisor - District 1`, with both declaration and candidate statement filed on `2/17/2026`, so the campaign bundle now promotes the `Seat -> Election -> Candidacy` chain for District 1.

### OQ-014: Resource Conservation PAC beneficiary boundary

- `status`: resolved
- `layer`: campaign methodology
- `scope`: `committee-resource-conservation-pac`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/campaign-finance-sample-basket-01/bundle-01.json)
  - [campaign.xml](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-campaign-finance-rss/2026-04-11/campaign.xml)
  - [filing.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-resource-conservation-pac-form-460-2026-04-08/2026-04-11/filing.pdf)
- `question`: What election, measure, or issue thread should the Resource Conservation PAC join to before schedule-level extraction is complete?
- `why it matters`: The cover page is enough to model the committee, sponsor, treasurer, and filing period, but not enough to safely attach the committee to a specific Marin decision chain without overclaiming.
- `resolution note`: Resolved by schedule-level extraction from the April 8, 2026 Form 460. The committee should not be forced into one beneficiary thread. The filing shows multiple itemized outflows: contributions to `Damon Connolly for Senate 2026`, `Josh Fryday for Lt. Governor 2026`, and `Heidi Sanborn for SMUD 2026`, plus professional-services payments to `S.E. Owens & Company`. The graph now treats this as a multi-beneficiary sponsored committee with separate campaign and vendor money flows.

### OQ-015: Marin Resource Recovery sponsor identity drift

- `status`: resolved
- `layer`: campaign identity
- `scope`: `committee-resource-conservation-pac`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/campaign-finance-sample-basket-01/bundle-01.json)
  - [filing.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-resource-conservation-pac-form-460-2026-04-08/2026-04-11/filing.pdf)
  - [report.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/town-of-ross-marin-sanitary-rate-review-2016/2026-04-11/report.pdf)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-resource-recovery-center-home/2026-04-11/source.html)
- `question`: Does `Marin Resource Recovery Center` in Schedule A resolve cleanly to the sponsor label `Marin Resource Recovery`, or should they remain distinct actors until a stronger business-identity source is captured?
- `why it matters`: This is a classic sponsor versus contributor identity-resolution problem. The committee title and the filing schedules do not use the same organization label, and the graph should not silently collapse them.
- `resolution note`: Resolved conservatively in favor of keeping them separate. The official Town of Ross rate-review report distinguishes `Marin Resource and Recovery (MRR)` from `the Marin Resource Recovery Center (MRRC)` as separate related entities, and the official MRRC website presents `Marin Resource Recovery Center` as its own facility within the Marin Sanitary family. That is strong enough to reject a silent merge of the two campaign actors.

### OQ-009: Prime Electric approval packet gap

- `status`: resolved
- `layer`: procurement joins
- `scope`: `project-bos-chambers-av-refresh`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/procurement-sample-basket-01/bundle-01.json)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-bos-chamber-upgrades-news-release/2026-04-11/source.txt)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-rfp-2883-bos-chambers-av-refresh/2026-04-11/source.txt)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-board-2025-10-21-agenda/2026-04-11/source.html)
  - [staff-report.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-prime-electric-staff-report/2026-04-11/staff-report.pdf)
  - [attachment.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-prime-electric-attachment/2026-04-11/attachment.pdf)
  - [agreement.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-prime-electric-agreement/2026-04-11/agreement.pdf)
- `question`: What is the exact Marin County Board record set for the October 21, 2025 Prime Electric approval?
- `why it matters`: The current county-side chain has the solicitation and a later official release, but it is still missing the meeting packet, staff report, and operative contract record that would anchor the `Decision -> Agreement` join cleanly.
- `resolution note`: The October 21, 2025 Granicus agenda page and linked CB-6 staff report, attachment, and agreement are now captured. They show that the approved Prime Electric contract itself is `$994,866.17`, while the authorized project total was `$1,144,237` after adding `$99,487` contingency and `$49,884` in additional project costs.

### OQ-010: Downtown Library agreement-family boundary

- `status`: resolved
- `layer`: procurement schema
- `scope`: `project-downtown-library-renovation`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/procurement-sample-basket-01/bundle-01.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-2024-09-16-downtown-library/2026-04-11/source.html)
  - [staff-report.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-downtown-library-construction-award-staff-report/2026-04-11/staff-report.pdf)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-2023-09-18-downtown-library/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-2025-04-07-downtown-library/2026-04-11/source.html)
  - [staff-report.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-downtown-library-first-amendment-staff-report/2026-04-11/staff-report.pdf)
  - [staff-report.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-downtown-library-second-amendment-staff-report/2026-04-11/staff-report.pdf)
- `question`: Should the Downtown Library architect and construction threads remain separate `Agreement` objects with a shared parent `Project`, or should they also roll up into a project-level contract family abstraction?
- `why it matters`: This is a direct pressure test of whether the procurement layer can stay specific enough for contract analytics without losing the user-facing “one project” view.
- `resolution note`: Keep separate `Agreement` objects for the architect, construction, and construction-management workstreams, all joined by the shared `Project`. The September 16, 2024 award record makes the boundary explicit: one project, but separate Unger construction and Unico construction-management agreements, in addition to the Noll & Tam design/administration PSA.

### OQ-011: Downtown Library State Library funding claim

- `status`: resolved
- `layer`: claim promotion
- `scope`: `project-downtown-library-renovation`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/procurement-sample-basket-01/bundle-01.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-downtown-library-reopening/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-2022-12-19-library-grants/2026-04-11/source.html)
  - [staff-report.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-downtown-library-state-grant-acceptance-staff-report/2026-04-11/staff-report.pdf)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/california-state-library-building-forward-report-2021-2022/2026-04-11/source.txt)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/california-state-library-lds-annual-update-2023-2024/2026-04-11/source.txt)
- `question`: What is the underlying official award record for the reopening page’s statement that the renovation was funded by the State of California and administered by the California State Library?
- `why it matters`: The graph should not promote that sentence into a durable `Grant` or `MoneyFlow` relationship without the award notice, Council acceptance record, or grant agreement.
- `resolution note`: The city-side claim is now backed by primary sources. The December 19, 2022 Council item and staff report confirm a `$1,000,000` SB 129 / Building Forward Downtown Carnegie grant accepted by the City. The California State Library annual update also lists a separate `$1,000,000` Targeted Grant for the `San Rafael Downtown Carnegie Library Preservation, Renovation, and Expansion Design Process`, which supports the city’s later `$2M` State Library funding line for the downtown project.

### OQ-012: County direct-artifact replacement path

- `status`: resolved
- `layer`: source methodology
- `scope`: procurement sample basket 01
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/procurement-sample-basket-01/bundle-01.json)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-bos-chamber-upgrades-news-release/2026-04-11/source.txt)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-slfrf/2026-04-11/source.txt)
  - [artifact-conventions.md](/Users/tammypais/projects/marin-civic-graph/docs/artifact-conventions.md)
  - [graph-joins-and-identity.md](/Users/tammypais/projects/marin-civic-graph/docs/graph-joins-and-identity.md)
  - [source-registry-format.md](/Users/tammypais/projects/marin-civic-graph/docs/source-registry-format.md)
- `question`: When the environment eventually permits direct county fetches, how should these proxy text captures be superseded without breaking stable record IDs?
- `why it matters`: The current procurement slice is honest about using text proxies, but the graph needs a stable way to replace proxies with raw HTML/PDF artifacts later.
- `resolution note`: The replacement convention is now explicit. Keep `source_id` and graph `record_id` stable when the newer artifact is the same semantic record; create a new `capture_id`, keep the older proxy capture in `data/raw/`, rerun extraction, and update the preferred normalized `artifact_path` only after review. Mint a new `record-*` node only when the improved artifact reveals a different object boundary.

### OQ-033: San Rafael council decision/vote depth after citywide meeting capture

- `status`: watch
- `layer`: breadth sprint / council decisions
- `scope`: `san-rafael-city-council-decisions-01`
- `source refs`:
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-council-minutes/2026-04-12.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-council-decisions-01/bundle-01.json)
  - [report.json](/Users/tammypais/projects/marin-civic-graph/data/projected/graph-v1/report.json)
- `question`: When should the citywide San Rafael council layer graduate from minutes-backed agenda items and decisions into packet-level record splitting or stricter vote provenance?
- `why it matters`: The graph now has a real citywide meeting, minutes-record, agenda-item, and decision layer, but complex consent blocks and multi-resolution items still rely on minutes-first heuristics rather than on packet-level object boundaries.
- `resolution note`: Narrowed materially. The second breadth-sprint council pass now captures `220` minutes PDFs, promotes `3175` `AgendaItem` candidates and `1453` `Decision` candidates, and raises graph-v1 to `6050` nodes / `20177` edges. The remaining question is no longer whether citywide decision extraction exists; it is when packet/staff-report parsing should replace or refine the current conservative minutes-first layer for the hardest item-boundary cases.

### OQ-034: San Rafael pre-current-term officeholder disclosure mapping

- `status`: watch
- `layer`: disclosure continuity / historical seat lineage
- `scope`: `san-rafael-officeholder-disclosures-01`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-officeholder-disclosures-01/bundle-01.json)
  - [2026-04-12.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-sei-netfile-portal/2026-04-12.json)
  - [canonical-seeds-san-rafael-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/canonical-seeds-san-rafael-01.json)
- `question`: How should pre-2020 or pre-district Form 700 rows for current San Rafael officeholders map once older seat structures and older term boundaries are modeled?
- `why it matters`: The elected-disclosure layer now covers explicit current terms plus the 2020-2024 prior terms for the current mayor, District 1, and District 4 officeholders. The remaining risk is older office structure drift, not simple current-term continuity.
- `current note`: The widened officeholder-disclosure bundle now imports `21` Form 700 filings and `21` `EconomicInterestDisclosure` nodes. `Kate Colin`, `Maika Llorens Gulati`, and `Rachel Kertz` now resolve through explicit historical `SeatService` windows starting on `2020-12-07`, while `Eli Hill` and `Maribeth Bushey` still only use the current post-2022 windows.
- `next evidence`: capture enough older San Rafael election and swear-in evidence to determine whether pre-2020 rows should map to older at-large council structures, older non-council offices, or remain out of graph-v1.

### OQ-035: San Rafael multi-cycle QA-backed campaign money coverage

- `status`: resolved
- `layer`: breadth sprint / campaign money
- `scope`: `san-rafael-city-campaign-filings-01`, `san-rafael-city-campaign-form460-schedules-01`
- `source refs`:
  - [query-pack-report.json](/Users/tammypais/projects/marin-civic-graph/data/projected/graph-v1/query-pack-report.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-filings-01/bundle-01.json)
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-city-campaign-form460-schedules-01/bundle-01.json)
- `question`: When should the San Rafael city-office campaign lane graduate from a single-cycle QA-backed money sample into true multi-cycle money recurrence across `2020`, `2022`, and `2024`?
- `why it matters`: The first formal fixed-query-pack run initially failed `Q4`, so the first Ralph loop was aimed at recovering one additional QA-backed campaign-money cycle before reopening broader breadth decisions.
- `current note`: The first Ralph-loop batch recovered a thin but sufficient 2020 money layer from city-office Form `460` filings. The current query-pack report now shows `qa_money_flow_years = [2020, 2024]`, `qa_money_flow_count = 138`, and `imported_noisy_actor_count = 0`, so the gating question is answered.
- `resolution`: Batch `01` of `san-rafael-city-campaign-money-01` was accepted on April 13, 2026. `Q4` now passes without reopening county breadth.

### OQ-036: Should the campaign-money Ralph loop continue into 2022 now that the gate is already met?

- `status`: watch
- `layer`: breadth sprint / campaign money
- `scope`: `san-rafael-city-campaign-money-01`
- `source refs`:
  - [san-rafael-city-campaign-money-01.json](/Users/tammypais/projects/marin-civic-graph/registry/loop-manifests/san-rafael-city-campaign-money-01.json)
  - [query-pack-report.json](/Users/tammypais/projects/marin-civic-graph/data/projected/graph-v1/query-pack-report.json)
  - [2026-04-13.json](/Users/tammypais/projects/marin-civic-graph/data/extracted/san-rafael-city-campaign-form460-schedules/2026-04-13.json)
- `question`: Once batch `01` makes all five fixed queries pass, should the loop continue into the `2022` city-office Form `460` batch or stop and choose the next densification lane?
- `why it matters`: The loop goal is now met, but the recovered `2020` layer is thin. Continuing into `2022` could strengthen recurrence depth, but it is no longer obviously the best next move compared with another San Rafael lane.
- `current note`: Batch `02` is now `deferred_pending_review` in the loop manifest. It should not run automatically just because it exists.
- `next evidence`: compare the likely product value of `2022` campaign-money depth against the next-best San Rafael densification candidate before opening another batch.

## Maintenance

When a question is answered:

1. update the relevant normalized file or case-study doc
2. change the status here to `resolved` or `dropped`
3. add a short note describing what resolved it

This file should stay short. If it turns into a dump of every loose thread, it stops being useful.
