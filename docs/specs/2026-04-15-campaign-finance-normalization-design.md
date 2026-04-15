# Campaign Finance Normalization — Design Spec

**Date:** 2026-04-15
**Status:** Draft
**Author:** Claude (Opus), with Stuart Watson

## 1. Purpose

Parse NetFile campaign finance Excel exports into graph nodes and load them into Neo4j. This is the data that makes "follow the money" investigation queries possible.

## 2. Scope

**Build now (Phase 1):**
- Parse A-Contributions (monetary contributions received) and E-Expenditure (payments made) sheets
- Create Committee, MoneyFlow, and contributor Person/Organization stub nodes
- Load into Neo4j for Marin County (8 years) and Novato (8 years)

**Build later (Phase 2):**
- D-Expenditure (non-monetary/accrued), C-Contributions (non-monetary), loans, 496/497 forms
- Cross-jurisdiction entity resolution (merge "John Smith" across Marin + Novato)
- Candidate-to-committee linkage (connect committees to officeholders in the graph)

## 3. Data Shape

Each NetFile ZIP contains an Excel workbook with 16 sheets. Phase 1 focuses on:

**A-Contributions (Schedule A):** 75 columns per row. Key fields:
- `Filer_ID` (int) — unique committee identifier in NetFile
- `Filer_NamL` (str) — committee name
- `Committee_Type` — CTL (candidate-controlled), RCP (recipient), etc.
- `Tran_ID` (str) — unique transaction ID within the filing
- `Tran_NamL`, `Tran_NamF` — contributor last name, first name
- `Tran_Amt1` (float) — contribution amount
- `Tran_Date` (datetime) — date of contribution
- `Entity_Cd` — IND (individual), COM (committee), OTH (other), SCC, etc.
- `Tran_Emp`, `Tran_Occ` — employer, occupation
- `Tran_City`, `Tran_State`, `Tran_Zip4` — contributor address
- `Elect_Date` — election the filing covers

**E-Expenditure (Schedule E):** Same header structure, but `Payee_NamL`/`Payee_NamF` instead of `Tran_NamL`/`Tran_NamF`.

## 4. Entity Resolution Strategy

Per adversarial review recommendations:

- **MoneyFlow unique key:** `{filer_id}-{tran_id}` — one node per transaction row
- **Committee anchor:** `Filer_ID` — numeric, unambiguous. One Committee node per unique Filer_ID.
- **Contributor/payee identity:** Normalized name-based ID (`person-{slugify(last-first)}` for IND, `org-{slugify(name)}` for COM/OTH). **No cross-jurisdiction dedup in Phase 1.** Each name variant gets its own node. Iterative dedup comes in Phase 2.

This means "John Smith" contributing to both a Marin County committee and a Novato committee will create one Person node (same slug), but "John Smith" and "Jon Smith" will be separate nodes. That's acceptable for Phase 1.

## 5. Node Types Produced

| Type | Source | Example ID | Count estimate |
|------|--------|-----------|----------------|
| Committee | Unique Filer_ID across all years | `committee-netfile-1461685` | ~50-100 per jurisdiction |
| MoneyFlow | Each row (contribution or expenditure) | `moneyflow-1461685-1cVRUPUuwASA` | ~2,700 for Marin 2024 |
| Person | IND contributors/payees | `person-cullen-carleen` | ~1,000+ |
| Organization | COM/OTH contributors/payees | `org-sticker-mule` | ~200+ |
| Record | One per year-export | `record-marin-county-campaign-finance-export-2024` | 8 per jurisdiction |

## 6. Edge Types Produced

| Edge | From → To | Source |
|------|-----------|--------|
| `FROM_SOURCE` | MoneyFlow → Person/Org (contributor) | A-Contributions rows |
| `TO_TARGET` | MoneyFlow → Committee (recipient) | A-Contributions Filer_ID |
| `FROM_SOURCE` | MoneyFlow → Committee (spender) | E-Expenditure Filer_ID |
| `TO_TARGET` | MoneyFlow → Person/Org (payee) | E-Expenditure rows |
| `EVIDENCED_BY` | MoneyFlow → Record | Year export record |
| `IN_JURISDICTION` | Committee → Place | Jurisdiction from source config |

## 7. Output Format

Same settled-ontology JSONL as the meeting normalizer. Loaded via `load_neo4j_v2.py`.

## 8. Success Criteria

1. `python scripts/normalize_campaign_finance.py --source marin-county-campaign-finance` produces JSONL with Committee, MoneyFlow, Person, Organization nodes
2. Loading into Neo4j succeeds
3. Cypher query: "Show all contributions over $1,000 to Marin County committees in 2024" returns real data
4. Cypher query: "Which contributors gave to multiple committees?" returns real results
5. Existing meeting and San Rafael data untouched
