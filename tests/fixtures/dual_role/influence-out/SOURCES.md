# Influence-out fixture slice — sources

Byte-verbatim slice of the real Marin County NetFile-derived campaign-finance
bundle (`data/normalized/marin-county-campaign-finance-campaign-finance/`,
normalize_campaign_finance.py output, bundle id
`marin-county-campaign-finance__2026-04-14`). Every line in `nodes.jsonl` /
`edges.jsonl` here is a literal line of the source files, in source-file
order — nothing fabricated, nothing re-serialized. Staged 2026-06-10 for
milestone M2d (dual-role candidate read model).

## What is included and why

| Rows | Role in M2d tests |
| --- | --- |
| `org-marin-agricultural-land-trust` + its 6 FROM_SOURCE flows (2020-03-06 → 2022-06-06, total 152,692.50, incl. one real negative amount −7,307.50) + `committee-netfile-1424535`, `committee-netfile-1444863` | The positive influence-out leg of the real dual-role join (990 fixture EIN 942689383 is the funding-in leg) |
| `org-community-action-marin` + `moneyflow-1474069-TxlZkgAM99rJ` (TO_TARGET → the org) + `committee-netfile-1474069` | Direction negative: the org appears ONLY as a flow target — money TO the org is not influence-out |
| `org-3qc-inc` (1 flow) and `org-alten-construction-inc` (2 flows) + `committee-netfile-1447634`, `committee-netfile-1436437` | Influence-out-only noise: orgs with no funding-in leg must not surface; they exercise the `influence_out_only` coverage count |
| All FROM_SOURCE / TO_TARGET / EVIDENCED_BY edges for the 10 included flows | The complete edge set the reader needs; `IN_JURISDICTION` edges are out of scope for the read model and excluded |

Totals: 19 nodes (4 Organization, 10 MoneyFlow, 5 Committee), 30 edges.

## Intentional properties of the slice

- **Campaign-envelope superset:** rows carry `promotion_state`, `qa_lane`,
  `source_bundle_ids`, `source_sections`, `source_status` on top of the v2
  envelope — the reader must tolerate and ignore them (kept verbatim here
  precisely to test that).
- **Dangling EVIDENCED_BY targets:** the four
  `record-marin-county-campaign-finance-export-{2020,2021,2022,2024}` ids
  have no Record node in this slice (nor in the source bundle) — record ids
  are carried verbatim with no node-closure requirement.
- **Org contributor rows only:** no Person nodes, no street addresses
  (verified at staging by node-type assertion and address-pattern scan).
