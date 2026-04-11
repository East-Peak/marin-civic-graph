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

- `status`: watch
- `layer`: media methodology
- `scope`: case study 01
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/bundle-01.json)
  - [media-attribution-rules.md](/Users/tammypais/projects/marin-civic-graph/docs/media-attribution-rules.md)
- `question`: When do citation-only Marin IJ records graduate into full article-body extraction and quote isolation?
- `why it matters`: This determines when `ArticleMention` and attribution-gap work can become evidence-bearing instead of remaining citation-level.
- `next evidence`: define a stable operator-assisted capture workflow for subscription-backed articles before promoting any quote-level claims.

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

- `status`: watch
- `layer`: term-boundary modeling
- `scope`: `canonical-seeds-san-rafael-01`
- `source refs`:
  - [canonical-seeds-san-rafael-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/canonical-seeds-san-rafael-01.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-elected-officials/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-page/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-november-5-2024-election/2026-04-11/source.html)
- `question`: What are the exact start and end dates for the current District 2 and District 3 council seat services, and what is the formal duration of the current Vice Mayor designation?
- `why it matters`: The graph can now represent current seat occupancy, but exact term boundaries still matter for historical queries and officeholder overlap analysis.
- `next evidence`: capture the earlier district-election or canvass materials that seated the current District 2 and District 3 councilmembers, plus any formal council action or protocol that defines the Vice Mayor designation period.

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

## Maintenance

When a question is answered:

1. update the relevant normalized file or case-study doc
2. change the status here to `resolved` or `dropped`
3. add a short note describing what resolved it

This file should stay short. If it turns into a dump of every loose thread, it stops being useful.
