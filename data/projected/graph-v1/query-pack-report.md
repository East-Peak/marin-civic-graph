# Graph Query Pack Report

- `generated_at`: 2026-04-13T12:44:59Z
- `engine`: projection_jsonl
- `projection_id`: graph-v1
- `nodes`: 6199
- `edges`: 20885
- `queries_passed`: 5/5

## Q1: actor-kate-colin dossier

- `pass`: yes
- `metrics`: {"committee_count": 2, "council_decision_count": 564, "council_meeting_count": 167, "council_record_count": 167, "filing_count": 57, "filing_family_counts": {"form_410": 17, "form_460": 21, "form_496": 1, "form_497": 8, "form_501": 3, "form_700": 5, "form_803": 2}, "filing_years": [2020, 2021, 2022, 2023, 2024, 2025, 2026], "seat_service_count": 2}
- `notes`:
  - Kate Colin now spans council voting, campaign committees, campaign filings, a local Form 803 filing, and imported Form 700 continuity.
  - The dossier crosses more than one year and more than one filing family, so it satisfies the fixed breadth-sprint threshold.

## Q2: current elected disclosure coverage

- `pass`: yes
- `metrics`: {"current_seat_service_count": 5, "imported_disclosure_filing_count": 10, "resolved_disclosure_filing_count": 10, "unresolved_disclosure_filing_count": 0}
- `notes`:
  - This query only tracks the narrow imported disclosure lane: current San Rafael elected seat services plus imported Form 700/Form 803 filings since 2019.
  - The pass condition is strict: every imported disclosure filing must resolve to both a canonical actor and a current seat service.

## Q3: San Rafael council decision timeline

- `pass`: yes
- `metrics`: {"decision_count": 1455, "decisions_with_evidence": 1455, "decisions_with_votes": 564, "meeting_count": 175, "year_span": [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]}
- `notes`:
  - This is the first fixed-query-pack check that directly measures whether the council breadth pass created an actual multi-year decision timeline.
  - The result is now a real 2019+ council decision spine rather than one worked-example branch.

## Q4: San Rafael election money spine

- `pass`: yes
- `metrics`: {"committee_count": 16, "cycle_rollup": {"2020": {"committee_count": 7, "filing_count": 66, "ie_filing_count": 4, "qa_money_flow_count": 2}, "2022": {"committee_count": 7, "filing_count": 44, "ie_filing_count": 0, "qa_money_flow_count": 0}, "2024": {"committee_count": 8, "filing_count": 42, "ie_filing_count": 0, "qa_money_flow_count": 136}}, "filing_count": 152, "ie_filing_count": 4, "imported_noisy_actor_count": 0, "qa_money_flow_count": 138, "qa_money_flow_years": [2020, 2024]}
- `notes`:
  - QA-backed campaign money now spans more than one cycle without importing noisy OCR actors into graph-v1.

## Q5: validation queue

- `pass`: yes
- `metrics`: {"status_counts": {"extraction_gap": 2, "reconciled": 12, "source_inconsistency": 2}, "subject_filing_count": 5, "validation_check_count": 16}
- `notes`:
  - The validation queue remains small enough to review directly.
  - The known Kate Colin 2024 Schedule A extraction gap remains visible in the queue and is still the main carried-forward reconciliation issue.
  - This query checks whether new breadth work is creating a manageable validation surface instead of a noisy anomaly dump.

## Supplemental Queries

### L1: legal constraint chain

- `pass`: yes
- `metrics`: {"boyd_present": true, "grants_pass_lineage_case_count": 3, "grants_pass_present": true, "legal_node_count": 26, "legal_record_count": 15, "linked_local_decision_count": 2, "shared_issue_count": 3, "shared_program_count": 1}
- `notes`:
  - This is a supplemental query, not part of the fixed five-query breadth gate.
  - It checks whether the first local-case plus controlling-precedent pair is materialized well enough to show a real legal constraint chain back into San Rafael decisions and programs.

## Recommendation

Do not widen scope blindly. Use the failed query set to pick the next density move and keep the sprint San Rafael-first.
