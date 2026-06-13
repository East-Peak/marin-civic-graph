# Form 700 interior fixture basket

Real FPPC Form 700 (Statement of Economic Interests) filings fetched from the
NetFile public portals for Marin County (`cmar`) and the City of San Rafael
(`raf`). Staged 2026-06-10 for the M4 interior-extraction milestone
(`scripts/extract_form700_interiors.py`). Together the basket covers every
interior schedule (A-1, A-2, B, C, D, E) at least once, plus one cover-only
filing and one amendment.

These are public records published by the filing agencies. Fixtures are
consumed by tests, never fetched at test time.

## Basket

| image id | agency | filer | position | statement | schedules | pages | in repo |
|---|---|---|---|---|---|---|---|
| 216262973 | cmar | Werby, Todd | Retirement Board member, Retirement Board | Annual 2025 | A-1, A-2, B, C, D | 19 | local-only |
| 216307037 | cmar | Jones, Sarah | Director of Community Development | Annual 2025 | A-1, A-2, C | 4 | yes |
| 216034157 | cmar | Fusenig, Sara | Administrative Services Director, District Attorney | Annual 2025 (amendment) | E | 2 | yes |
| 216872504 | cmar | Alden, John | Inspector General, Office of the County Executive | Assuming 2026 | cover only | 1 | yes |
| 215754761 | raf | Holm, James Alexander | Police Lieutenant, Police Department | Annual 2025 | A-1, A-2, B | 4 | local-only |
| 215774405 | raf | Lara, Lindsay | City Clerk | Annual 2025 | C (loan) | 2 | yes |

Each `interiors/<image-id>/` directory holds `document.pdf` and
`metadata.json` (index-derived facts: filer, dates, agency, filing GUID,
declared schedules, `pdf_sha256`).

## Local-only filings

The two Schedule-B-bearing PDFs (216262973, 215754761) print residential
street addresses / assessor parcel numbers in their text layers. This repo is
public, so those PDFs are **never committed** (see `interiors/.gitignore`).
They are pinned by `pdf_sha256` in their committed `metadata.json` and can be
re-fetched by an operator from `source_url`
(`https://netfile.com/Connect2/api/public/image/<image-id>`). Tests that need
them must skip when the PDF is absent and the extraction loop must BLOCK —
never fetch — when a pinned fixture is missing or fails its hash check.

## Verification performed at staging time

- Every PDF downloaded directly from the NetFile document endpoint; sha256
  computed at download time and pinned in `metadata.json`.
- Text layers verified with `pdftotext -layout` (no OCR): every schedule row
  in every filing transcribed and reconciled against the structured
  transaction records returned by the NetFile public search API
  (`POST https://netfile.com/api/public/sites/api/searchtransactions`).
  Werby: 21 A-1 + 12 A-2 + 4 B + 7 C + 2 D = 46/46 rows matched. Jones: 5/5.
  Fusenig: 2/2. Holm: 4/4. Lara: 1/1. Alden: cover-only, "No reportable
  interests" box checked.
- Page counts verified with `pdfinfo` against the cover-page schedule summary
  (`file(1)` misreports page counts on these PDFs).
- Filing dates on covers ("E-Filed" stamp, agency-local time) matched to the
  portal index `filingDate` for each filing GUID.

## Notable real-world quirks preserved in the basket

Kept deliberately — parsers must handle them, not normalize them away:

- E-filed PDFs print the **full form template**, including empty sections and
  unchecked boxes; checked boxes render as a leading `X`.
- NetFile redacts tenant names in Schedule B ("Name(s) redacted"), in both the
  PDF text layer and the API; 216262973 also carries a redacted overflow page.
- Gift dates can postdate the filing date (216262973: gifts dated 05/13/26 on
  a statement e-filed 2026-03-22). Recorded verbatim.
- A Schedule C "YOUR BUSINESS POSITION" value can be an entity name rather
  than a title (216262973), or the literal `None` (215754761).
- An A-2 entity name can match street-address shapes while being a legitimate
  business name (216262973) — address-stripping must be field-scoped, not a
  raw substring sweep.
- 216034157 is a stamped AMENDMENT; its parent filing GUID is recorded as
  `amends_filing_guid` in `metadata.json`.
- Spouse interests appear with explicit markers (216307037: A-2 position
  "Managing Director (spouse)", Schedule C "Spouse's or registered domestic
  partner's income" box).
