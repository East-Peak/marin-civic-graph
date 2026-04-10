# Borrow Map

This project should steal proven patterns instead of inventing everything from scratch.

## Product References

### CivLab / SF Gov Graph

Reference:

- https://sfgov.civlab.org/

Borrow:

- institution pages with legal source + official site
- seats and appointments as first-class data
- meetings attached directly to bodies
- media coverage attached to the same page
- topic views like homelessness, housing, transit, public safety

Do not copy:

- San Francisco-specific taxonomy
- any assumptions unique to charter-city governance

### Machinery of Government

Reference:

- https://machineryofgovernment.uk/

Borrow:

- hierarchy as a first-class concept
- typed institution categories
- role separation between officials and institutions
- graph view as a serious analytical tool

Do not copy:

- UK-specific ministry and public-body ontology wholesale

### House of the People

Reference:

- https://houseofthepeople.com/

Borrow:

- decisions and votes as first-class objects
- browsable entry points for bills, representatives, parties, and gap views
- the idea of comparing representative behavior to surrounding signals

Do not copy:

- direct-democracy framing for local government without strong methodology

## Open Source Building Blocks

### Open Civic Data / Pupa

References:

- https://open-civic-data.readthedocs.io/en/latest/
- https://github.com/opencivicdata/pupa

Borrow:

- core civic schema
- identifiers for jurisdictions, people, organizations, posts, memberships
- event / vote / bill object model

Role in Marin Civic Graph:

- baseline civic-process ontology

### City Scrapers

References:

- https://github.com/City-Bureau/city-scrapers
- https://github.com/City-Bureau/city-scrapers-template

Borrow:

- meeting scraper patterns
- test discipline for ugly local-government sites
- per-jurisdiction scraper modularity

Role in Marin Civic Graph:

- meeting and document ingestion

### Legistar Scrapers

References:

- https://github.com/opencivicdata/python-legistar-scraper
- https://github.com/opencivicdata/scrapers-us-municipal

Borrow:

- Legistar / Granicus collection patterns
- municipal scraper conventions

Role in Marin Civic Graph:

- any jurisdiction that exposes Legistar-style infrastructure

### Councilmatic

Reference:

- https://github.com/datamade/chi-councilmatic

Borrow:

- public browse / search patterns
- entity page IA for legislation, committees, meetings, and people

Role in Marin Civic Graph:

- public-facing UX inspiration

### FollowTheMoney

Reference:

- https://github.com/alephdata/followthemoney

Borrow:

- practical entity ontology
- payments, ownership, organizations, roles, cases
- normalization mindset for investigative data

Role in Marin Civic Graph:

- influence / money / NGO / contractor layer

### Aleph

Reference:

- https://github.com/alephdata/aleph

Borrow:

- entity-document browsing ideas
- investigative workflow concepts

Do not copy:

- the full application as a dependency

Notes:

- Useful as inspiration only. The public repo was sunset after December 2025.

### court-scraper

Reference:

- https://github.com/biglocalnews/court-scraper

Borrow:

- court scraping patterns if judicial tracking becomes a later phase

Role in Marin Civic Graph:

- future extension, not v1

## Recommended Stack Shape

For Marin v1:

- Open Civic Data for civic-process primitives
- FollowTheMoney for money / entity / case primitives
- City Scrapers and Legistar tools for ingestion
- Councilmatic for browse / search page patterns

This is the shortest path to a useful system without copying any one project whole.
