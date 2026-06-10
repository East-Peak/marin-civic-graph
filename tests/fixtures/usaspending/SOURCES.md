# USASpending fixture sources (M2c)

All files are **verbatim, unmodified** response bodies from the public USASpending API,
captured 2026-06-09. Endpoint for every file:

```
POST https://api.usaspending.gov/api/v2/search/spending_by_award/
Content-Type: application/json
```

Shared request `fields` (the API returns only requested fields; the sort field must be
among them):

```json
["Award ID","Recipient Name","Award Amount","Awarding Agency","Awarding Sub Agency",
 "Funding Agency","Funding Sub Agency","Start Date","End Date","Award Type",
 "CFDA Number","recipient_id","generated_internal_id","Recipient UEI",
 "Recipient Business Categories"]
```

## spending-by-award-grants-p1.json / spending-by-award-grants-p2.json

Same query, pages 1 and 2 (drives pagination + cross-page recipient dedupe):

```json
{
  "filters": {
    "award_type_codes": ["02", "03", "04", "05"],
    "recipient_locations": [{"country": "USA", "state": "CA", "county": "041"}],
    "time_period": [{"start_date": "2022-10-01", "end_date": "2025-09-30"}]
  },
  "fields": <shared fields above>,
  "page": 1,            // and 2 for -p2
  "limit": 10,
  "sort": "Award Amount",
  "order": "desc"
}
```

## spending-by-award-direct-payments-p1.json

Direct-payments group — contains the real skip-rule rows:

```json
{
  "filters": {
    "award_type_codes": ["06", "10"],
    "recipient_locations": [{"country": "USA", "state": "CA", "county": "041"}],
    "time_period": [{"start_date": "2022-10-01", "end_date": "2025-09-30"}]
  },
  "fields": <shared fields above>,
  "page": 1,
  "limit": 5,
  "sort": "Award Amount",
  "order": "desc"
}
```

## Contract verification + empirical findings (capture-time, 2026-06-09)

- **Cross-page repeated recipients (real, both pages):** `BUCK INSTITUTE FOR RESEARCH
  ON AGING` (`ba9b782e-…`) and `COMMUNITY ACTION MARIN` (`cf3072ee-…`).
- **UEI:** field name is `"Recipient UEI"`; all 20 grant rows carry one; values are
  12-char alphanumeric WITH letters (e.g. `JZ9FLAVMPEB9`) — digits-only normalization
  would destroy them.
- **Skip-rule rows (5, all real):** `generated_internal_id` prefix `ASST_AGG_`
  (county-level aggregate records — published in aggregate precisely because the
  underlying recipients are individuals/PII-redacted); `Recipient Name` =
  `"MULTIPLE RECIPIENTS"`, `Recipient UEI` = null, `recipient_id` = null.
- **Identity:** every row carries `generated_internal_id` (e.g.
  `ASST_NON_09CH011669_075`, uppercase). Award profile URL =
  `https://www.usaspending.gov/award/<generated_internal_id>` (verbatim case).
- **Amount:** `"Award Amount"` is a JSON float in dollars (e.g. `31949723.2`) —
  the award-lifetime total obligation, not an annual figure.
- **recipient_id format:** UUID-with-level-suffix, already lowercase-hyphenated
  (e.g. `cf3072ee-ffc8-260e-4fc3-57dc5b893427-C`; `-C` company / `-R` recipient level).
- **Agency code:** there is NO `toptier_code` field in this endpoint's response; it
  carries `awarding_agency_id` (internal numeric) and `agency_slug` (stable,
  e.g. `department-of-health-and-human-services`).
- **Funding vs awarding agency:** both field pairs present; funding == awarding on
  every staged row (0 divergent rows).
- **`Recipient Business Categories`:** valid request field, but null on every staged
  row (and on the top-25 scan) — effectively unavailable from this endpoint.
- **Cross-source (990 fixtures):** neither Marin Community Foundation nor MALT
  appears in the staged pages — no deterministic cross-source seed; cross-source
  joins remain name-based queued candidates.
- **Duplicate award ids:** none across the three files (real pagination never
  overlaps).
- **API constraint:** `award_type_codes` must all come from ONE group per request
  (mixing e.g. `"02"` and `"A"` returns a 400); full coverage requires one request
  series per group.
