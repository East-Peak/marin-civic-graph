# Graph Query Pack Report

- `generated_at`: 2026-04-13T11:19:00Z
- `engine`: projection_jsonl
- `projection_id`: graph-v1
- `nodes`: 6068
- `edges`: 20251
- `queries_passed`: 5/5

## Q1: actor-kate-colin dossier

- `pass`: yes
- `metrics`: {"committee_count": 2, "council_decision_count": 564, "council_meeting_count": 167, "council_record_count": 167, "filing_count": 53, "filing_family_counts": {"form_410": 17, "form_460": 21, "form_496": 1, "form_497": 8, "form_501": 3, "form_700": 1, "form_803": 2}, "filing_years": [2020, 2021, 2022, 2023, 2024, 2025, 2026], "seat_service_count": 1}
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
- `metrics`: {"decision_count": 1454, "decisions_with_evidence": 1454, "decisions_with_votes": 564, "meeting_count": 175, "year_span": [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]}
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

## Recommendation

Do not widen scope blindly. Use the failed query set to pick the next density move and keep the sprint San Rafael-first.
