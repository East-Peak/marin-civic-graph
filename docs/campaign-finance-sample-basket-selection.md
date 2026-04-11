# Campaign Finance Sample Basket Selection

Verified: April 11, 2026

This document picks the first three concrete campaign-finance and disclosure sample threads for Marin Civic Graph.

The goal is to pressure-test the campaign/disclosure layer against public local filing surfaces that are directly fetchable now, not against an imagined future statewide warehouse.

## Primary Basket

### Slot A: Mary Sackett for Marin County Supervisor 2026

- Portal home: https://public.netfile.com/pub2/?aid=CMAR
- RSS filing feed: https://netfile.com/connect2/api/public/list/filing/rss/CMAR/campaign.xml
- Filing PDF: https://netfile.com/Connect2/api/public/image/216618080

Why this is in:

- clearly candidate-linked committee title
- directly accessible official Form 497 PDF
- filing includes committee ID, filing ID, filing timestamp, and a named contributor committee
- gives the cleanest first pass for `Committee -> Filing -> MoneyFlow` without reverse-engineering the full NetFile search workflow yet

What it pressure-tests:

- candidate-linked committee identity
- `Form 497` filing modeling
- committee-to-contribution joins
- committee donor as an `Actor`
- evidence-first handling of office or district ambiguity when the filing title is more specific than the current election capture set

Why it beats the alternatives:

- `Aikens for Supervisor 2026` and `Magali Limeta for Marin County Supervisor 2026` were also visible in the RSS feed, but the Mary Sackett filing was the freshest directly verifiable committee thread and already exposed a named donor committee on page one

### Slot B: Resource Conservation PAC, sponsored by Marin Resource Recovery

- Portal home: https://public.netfile.com/pub2/?aid=CMAR
- RSS filing feed: https://netfile.com/connect2/api/public/list/filing/rss/CMAR/campaign.xml
- Filing PDF: https://netfile.com/Connect2/api/public/image/216601918

Why this is in:

- official Form 460 PDF is directly accessible
- cover page explicitly states `General Purpose Committee` and `Sponsored`
- the filing exposes a clear sponsor relationship and named treasurer on page one
- this is a better first outside-money thread than trying to jump straight into independent-expenditure search mechanics

What it pressure-tests:

- sponsored-committee modeling
- distinction between `Committee`, sponsor `Actor`, and treasurer `Actor`
- `Form 460` filing periods and amended-status handling
- when a non-candidate committee should remain only weakly joined to issues or elections until line-item schedules are extracted

Why it beats the alternatives:

- `Sensible Taxpayers of Marin 2026 Sponsored by Coalition of Sensible Taxpayers` is a strong reserve thread, but the Resource Conservation PAC filing is richer because the Form 460 cover page already exposes committee type, sponsor status, treasurer identity, and filing period in one public record

### Slot C: Quinn Gardner annual Form 700

- City disclosure spine: https://www.cityofsanrafael.org/disclosures/
- SEI portal: https://public.netfile.com/pub/?AID=raf
- RSS filing feed: https://netfile.com/connect2/api/public/list/filing/rss/RAF/sei.xml
- Filing PDF: https://netfile.com/Connect2/api/public/image/216603530

Why this is in:

- directly accessible official Form 700 PDF
- cover page exposes filer name, agency, department, position, jurisdiction, filing type, filing timestamp, and covered period
- gives the cleanest first disclosure thread for `EconomicInterestDisclosure -> Actor -> Institution`

What it pressure-tests:

- `Form 700` modeling
- actor-to-institution joins from a disclosure record
- department-level institutional joins inside a city filing
- annual disclosure timing and statement-type handling

Why it beats the alternatives:

- other recent San Rafael Form 700 filings were visible in the RSS feed, but Quinn Gardner was the first one directly verified to include a clean city, department, and position chain on the cover page

## Reserve Threads

### Reserve A: Sensible Taxpayers of Marin 2026 Sponsored by Coalition of Sensible Taxpayers

- Filing PDF: https://netfile.com/Connect2/api/public/image/216397574

Why keep it in reserve:

- direct `Form 497` late-contribution thread
- explicit sponsor-name echo between committee and contributor
- useful if the first outside-money slice needs a narrower contribution-focused control case

### Reserve B: San Rafael Form 803 / behested-payment disclosure thread

- Disclosure spine: https://www.cityofsanrafael.org/disclosures/

Why keep it in reserve:

- the city disclosure page advertises Form 803 availability
- useful after the first `Form 700` thread if we want to test behested-payment joins rather than only economic-interest disclosure

Current status after the first follow-on slice:

- local-versus-state filing boundaries are now verified
- the public San Rafael SEI portal appears to be Form 700-oriented, not a visible Form 803 search surface
- San Rafael City Council governance records now provide the strongest local public behested-payment guidance records
- the remaining step is to locate the actual local filed Form 803 surface

## Why This Basket Is Balanced

Together these three slots cover:

- one candidate-linked committee filing
- one sponsored non-candidate committee filing
- one city disclosure filing
- one `Form 497`
- one `Form 460`
- one `Form 700`
- one county filing surface
- one city disclosure surface

That is enough to test whether the campaign/disclosure layer really needs:

- `Committee`
- `Candidacy`
- `Filing`
- `EconomicInterestDisclosure`
- campaign `MoneyFlow`
- sponsor, treasurer, and institution joins

## Immediate Next Moves

1. Capture and manifest the portal home pages, RSS feeds, and selected filing PDFs.
2. Normalize a first campaign sample bundle with candidate `Committee`, `Filing`, `EconomicInterestDisclosure`, and `MoneyFlow` objects.
3. Resolve the first seat/election ambiguity for the Mary Sackett committee using an official election or committee search surface.
4. Extract line-item schedules from the Resource Conservation PAC Form 460 before assigning it to a specific race, measure, or issue thread.
5. Decide when San Rafael disclosure threads should expand from `Form 700` into `Form 803` and other ethics surfaces.

## Source Basis

The selection is based on official public filing surfaces reviewed on April 11, 2026:

- the Marin NetFile public portal exposes campaign search by name, committee ID, elections browsing, yearly exports, and dedicated date-search sections for independent expenditures and `Form 497` contributions
- the Marin campaign RSS feed directly exposes recent committee titles, filing types, filing dates, and document links
- the selected Mary Sackett and Resource Conservation PAC filings are directly fetchable as official PDFs from NetFile
- the San Rafael disclosures page exposes the city disclosure spine and links into the public SEI portal
- the San Rafael SEI RSS feed directly exposes recent Form 700 filings and document links
- the selected Quinn Gardner filing is directly fetchable as an official PDF and exposes agency, department, position, and annual-statement context on the cover page
