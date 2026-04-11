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

- `status`: watch
- `layer`: identity resolution
- `scope`: case study 01
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/san-rafael-homelessness-01/bundle-01.json)
- `question`: How should raw councilmember labels from official records resolve into canonical person records without hand-wavy matching?
- `why it matters`: This is the same join problem that will recur across meetings, votes, appointments, and disclosures.
- `next evidence`: build the first canonical `Person` seeds for San Rafael electeds and map the August 19 records against them.

### OQ-009: Prime Electric approval packet gap

- `status`: open
- `layer`: procurement joins
- `scope`: `project-bos-chambers-av-refresh`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/procurement-sample-basket-01/bundle-01.json)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-bos-chamber-upgrades-news-release/2026-04-11/source.txt)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-rfp-2883-bos-chambers-av-refresh/2026-04-11/source.txt)
- `question`: What is the exact Marin County Board record set for the October 21, 2025 Prime Electric approval?
- `why it matters`: The current county-side chain has the solicitation and a later official release, but it is still missing the meeting packet, staff report, and operative contract record that would anchor the `Decision -> Agreement` join cleanly.
- `next evidence`: capture the October 21, 2025 Board meeting page, packet, and any linked agreement or staff report.

### OQ-010: Downtown Library agreement-family boundary

- `status`: open
- `layer`: procurement schema
- `scope`: `project-downtown-library-renovation`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/procurement-sample-basket-01/bundle-01.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-2023-09-18-downtown-library/2026-04-11/source.html)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-city-council-2025-04-07-downtown-library/2026-04-11/source.html)
  - [staff-report.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-downtown-library-first-amendment-staff-report/2026-04-11/staff-report.pdf)
  - [staff-report.pdf](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-downtown-library-second-amendment-staff-report/2026-04-11/staff-report.pdf)
- `question`: Should the Downtown Library architect and construction threads remain separate `Agreement` objects with a shared parent `Project`, or should they also roll up into a project-level contract family abstraction?
- `why it matters`: This is a direct pressure test of whether the procurement layer can stay specific enough for contract analytics without losing the user-facing “one project” view.
- `next evidence`: inspect the captured staff reports and any later signed agreement pages for the Noll & Tam and Unger actions, then compare how the city itself groups the contract family.

### OQ-011: Downtown Library State Library funding claim

- `status`: watch
- `layer`: claim promotion
- `scope`: `project-downtown-library-renovation`
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/procurement-sample-basket-01/bundle-01.json)
  - [source.html](/Users/tammypais/projects/marin-civic-graph/data/raw/san-rafael-downtown-library-reopening/2026-04-11/source.html)
- `question`: What is the underlying official award record for the reopening page’s statement that the renovation was funded by the State of California and administered by the California State Library?
- `why it matters`: The graph should not promote that sentence into a durable `Grant` or `MoneyFlow` relationship without the award notice, Council acceptance record, or grant agreement.
- `next evidence`: capture the underlying grant award surface or city acceptance record before promoting the funding relationship.

### OQ-012: County direct-artifact replacement path

- `status`: watch
- `layer`: source methodology
- `scope`: procurement sample basket 01
- `source refs`:
  - [bundle-01.json](/Users/tammypais/projects/marin-civic-graph/data/normalized/procurement-sample-basket-01/bundle-01.json)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-bos-chamber-upgrades-news-release/2026-04-11/source.txt)
  - [source.txt](/Users/tammypais/projects/marin-civic-graph/data/raw/marin-county-slfrf/2026-04-11/source.txt)
- `question`: When the environment eventually permits direct county fetches, how should these proxy text captures be superseded without breaking stable record IDs?
- `why it matters`: The current procurement slice is honest about using text proxies, but the graph needs a stable way to replace proxies with raw HTML/PDF artifacts later.
- `next evidence`: define a replacement convention where `Record` IDs stay stable while artifact paths and provenance metadata are upgraded.

## Maintenance

When a question is answered:

1. update the relevant normalized file or case-study doc
2. change the status here to `resolved` or `dropped`
3. add a short note describing what resolved it

This file should stay short. If it turns into a dump of every loose thread, it stops being useful.
