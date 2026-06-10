# 990 fixture sources

Real IRS Form 990 e-file XML, operator-staged 2026-06-09 for M2b (`scripts/ingest_990.py`).
Never synthesized, never fetched by the goal loop. Orgs chosen by size/prominence and
schema coverage per the top-down decision doc (§3) — NOT by suspicion.

Retrieval path: ProPublica Nonprofit Explorer org pages provided the e-file `object_id`s
(the API v2 `filings_with_data` no longer carries them); XML downloaded from the
GivingTuesday 990 data lake (public S3 mirror of IRS e-file releases):
`https://gt990datalake-rawdata.s3.amazonaws.com/EfileData/XmlFiles/<object_id>_public.xml`

All fields below verified by namespace-agnostic parse, **scoped to the `Filer` element of
`ReturnHeader`** (first-match-in-document-order returns the preparer firm, e.g. ARMANINO LLP
on the MCF returns — do not do that).

| File | Organization | EIN | TaxYr | Return type |
|---|---|---|---|---|
| `202421369349304932.xml` | Marin Community Foundation | 94-3007979 | 2022 | IRS990 |
| `202541349349313719.xml` | Marin Community Foundation | 94-3007979 | 2023 | IRS990 |
| `202421309349304522.xml` | Marin Agricultural Land Trust | 94-2689383 | 2022 | IRS990 |
| `202530769349201418.xml` | Sausalito Foundation | 94-6077085 | 2024 | IRS990EZ |

Roles in the fixture contract:

- **MCF 2022 + 2023** — two consecutive tax years of the same filer: drives the EIN-identity
  collapse (one Organization node across years) and the multi-year Membership dedupe test
  (same officer both years → one Membership node, unioned `evidence_record_ids`).
- **MALT 2022** — a different filer: cross-org separation, resolver negative cases.
- **Sausalito Foundation 2024 (990-EZ)** — non-IRS990 return: the parser must skip it with a
  logged reason, never emit nodes from it.

Provenance (ProPublica org pages, retrieved 2026-06-09):

- https://projects.propublica.org/nonprofits/organizations/943007979 (MCF)
- https://projects.propublica.org/nonprofits/organizations/942689383 (MALT)
- https://projects.propublica.org/nonprofits/organizations/946077085 (Sausalito Foundation)

Discovery notes: ProPublica's own `download-xml` endpoint bot-challenges non-browser clients;
the data-lake S3 URLs above are the reproducible path. The data lake had not yet ingested the
newest (2026-released) objects at staging time.
