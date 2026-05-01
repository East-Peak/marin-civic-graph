# Source Operations Log

Track every data source, how it's ingested, when it was last run, and what cadence it needs for cron.

## Meeting Capture Adapters

All run via `python scripts/ingest.py --source {source_id} --registry registry/{adapter}-sources.yaml`

| Source ID | Adapter | Registry | Last captured | Meetings | Cron cadence | Notes |
|---|---|---|---|---|---|---|
| `marin-county-bos` | granicus (legacy) | granicus-sources.yaml | 2026-04-14 | 317 | Weekly (Tue) | BOS meets most Tuesdays |
| `novato-city-council` | granicus (modern) | granicus-sources.yaml | 2026-04-14 | 409 | Weekly (Tue/Thu) | Meets 2nd + 4th Tue |
| `sausalito-city-council` | granicus (modern) | granicus-sources.yaml | 2026-04-14 | 254 | Biweekly (Tue) | Meets 1st + 3rd Tue |
| `tiburon-town-council-granicus` | granicus (modern) | granicus-sources.yaml | 2026-04-15 | 570 | Biweekly (Wed) | Meets 1st + 3rd Wed |
| `corte-madera-town-council` | civicplus | civicplus-sources.yaml | 2026-04-15 | 903 | Weekly | Multiple bodies, AJAX year fetch |
| `corte-madera-planning-commission` | civicplus | civicplus-sources.yaml | — | — | Weekly | Split from town-council source |
| `tiburon-town-council` | civicplus | civicplus-sources.yaml | 2026-04-15 | 0 | — | Only has 2012-2016 data, no current use |
| `mill-valley-planning-commission` | civicplus | civicplus-sources.yaml | 2026-04-15 | 542* | Weekly | *Captured as mill-valley-committees |
| `mill-valley-parks-recreation` | civicplus | civicplus-sources.yaml | — | — | Monthly | Split from committees source |
| `fairfax-town-council` | proudcity | proudcity-sources.yaml | 2026-04-15 | 174 | Weekly (Wed) | Archive pages need per-year URLs |
| `belvedere-city-council` | proudcity | proudcity-sources.yaml | 2026-04-15 | 96 | Biweekly (Mon) | Uses archive_pages config |
| `ross-town-council` | drupal_ross | drupal-sources.yaml | 2026-04-15 | 19 | Monthly | Tiny town, sparse data |

## Campaign Finance Capture

Run via `python scripts/ingest.py --source {source_id} --registry registry/netfile-sources.yaml`

| Source ID | Adapter | Last captured | Years | Cron cadence | Notes |
|---|---|---|---|---|---|
| `marin-county-campaign-finance` | netfile | 2026-04-14 | 2019-2026 (8) | Quarterly | ZIP exports with Excel workbooks |
| `novato-campaign-finance` | netfile | 2026-04-14 | 2019-2026 (8) | Quarterly | Some years empty (pre-2022) |

## Normalization Pipelines

| Script | What it does | Last run | Cron cadence | Command |
|---|---|---|---|---|
| `normalize_meetings.py` | Adapter JSON → Meeting/Record/Org/Place nodes → Neo4j | 2026-04-15 | After each capture run | `python scripts/normalize_meetings.py --all --load` |
| `normalize_campaign_finance.py` | NetFile ZIPs → Committee/MoneyFlow/Person nodes → Neo4j | 2026-04-15 | After each NetFile capture | `python scripts/normalize_campaign_finance.py --all --load` |
| `ingest_socrata_permits.py` | Socrata SODA API → 49K Project+Place nodes + IN_JURISDICTION edges → Neo4j | 2026-04-14 | Quarterly | `python scripts/ingest_socrata_permits.py --load` |

## Post-Normalization Pipelines

| Script | What it does | Last run | Cron cadence | Command |
|---|---|---|---|---|
| `resolve_committee_candidates.py` | Link committees → candidate Person nodes via name parsing | 2026-04-15 | After campaign finance normalization | `python scripts/resolve_committee_candidates.py` |
| `extract_agenda_items.py` | Download agenda PDFs, parse sections/items | 2026-04-15 | After meeting normalization | `python scripts/extract_agenda_items.py --all --limit 200` |
| `extract_decisions.py` | Download minutes PDFs, parse votes/decisions | 2026-04-15 | After meeting normalization | `python scripts/extract_decisions.py --all --limit 200` |

## Manual / One-Time Scripts

| Script | What it does | Last run | Notes |
|---|---|---|---|
| `migrate_graph_v2.py` | Migrate graph-v1 → settled ontology | 2026-04-15 | One-time migration, won't run again |
| `load_neo4j_v2.py` | Load JSONL into Neo4j | 2026-04-15 | Used by normalizers' --load flag |
| `verify_neo4j_v2.py` | Run 20 verification checks | 2026-04-15 | Run after any load to verify |
| Officeholder seeding | Python script creating Seat/SeatService nodes | 2026-04-15 | Run-once inline script, needs formalization |

## Not Yet Built — Future Pipelines

| Source | What | Priority | Access | Notes |
|---|---|---|---|---|
| **Form 700 (FPPC)** | Officeholder economic interests | High | `form700search.fppc.ca.gov` (all 87200 filers since Jan 2025) | AB 1170 mandates e-filing |
| **Form 700 (NetFile local)** | Broader staff disclosures | High | 9 cities have portals: `public.netfile.com/pub/?aid={CITY}` | City codes: cmar, raf, NVO, SAU, tib, ctm, LARK, SMO, ROSS |
| **eTRAKiT permits** (4 cities) | City-level permits | Medium | Sausalito, Tiburon, San Anselmo, Larkspur — same ASP.NET scraping | One adapter covers all 4 |
| **Accela permits** (2 cities) | City-level permits | Medium | Fairfax (`aca-prod.accela.com/FAIRFAX/`), Corte Madera (`aca-prod.accela.com/CORTE`) | One adapter covers both |
| **CourtListener** | Federal case metadata | Medium | Free REST API at courtlistener.com | Search by party: "City of San Rafael", "County of Marin" |
| **GIS parcels** | 96K parcel geometries | Medium | Free ArcGIS REST API | Spatial backbone for proximity queries |
| **Marin Superior Court** | State trial court cases | Low | Login required, post-June-2023, no API | Tyler Odyssey portal, manual |
| **OpenGov permits** (2 cities) | San Rafael + Mill Valley permits | Low | Modern SPA, hard to scrape | May need Playwright |
| **Form 803 (behested payments)** | Official solicited payments | Low | Local filings only, no central database | PRA request to city clerks |

## Cron Schedule (Proposed)

```
# Weekly: Meeting capture + normalization + agenda/decision extraction
0 2 * * 1  python scripts/ingest.py --all --registry registry/granicus-sources.yaml
0 3 * * 1  python scripts/ingest.py --all --registry registry/civicplus-sources.yaml
0 4 * * 1  python scripts/ingest.py --all --registry registry/proudcity-sources.yaml
0 5 * * 1  python scripts/ingest.py --all --registry registry/drupal-sources.yaml
0 6 * * 1  python scripts/normalize_meetings.py --all --load
0 7 * * 1  python scripts/extract_agenda_items.py --all --limit 50
0 8 * * 1  python scripts/extract_decisions.py --all --limit 50

# Quarterly: Campaign finance
0 2 1 1,4,7,10 *  python scripts/ingest.py --all --registry registry/netfile-sources.yaml
0 3 1 1,4,7,10 *  python scripts/normalize_campaign_finance.py --all --load
0 4 1 1,4,7,10 *  python scripts/resolve_committee_candidates.py

# Monthly: Verification
0 9 1 * *  python scripts/verify_neo4j_v2.py
```

## Neo4j AuraDB

- Instance: `<INSTANCE-ID>.databases.neo4j.io` (paid)
- Credentials: `AuraDB-credentials-file`
- Current state: ~43K nodes / ~68K edges (includes 1K permit sample loaded 2026-04-14)
- Schema: `registry/neo4j-schema.cypher` (22 constraints, full-text index, 12 property indexes)
