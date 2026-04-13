# Graph Query Pack Report

- `generated_at`: 2026-04-13T01:22:28Z
- `engine`: projection_jsonl
- `projection_id`: graph-v1
- `nodes`: 6050
- `edges`: 20177
- `queries_passed`: 4/5

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

- `pass`: no
- `metrics`: {"committee_count": 16, "cycle_rollup": {"2020": {"committee_count": 7, "filing_count": 66, "ie_filing_count": 4, "qa_money_flow_count": 0}, "2022": {"committee_count": 7, "filing_count": 44, "ie_filing_count": 0, "qa_money_flow_count": 0}, "2024": {"committee_count": 8, "filing_count": 42, "ie_filing_count": 0, "qa_money_flow_count": 136}}, "filing_count": 152, "ie_filing_count": 4, "imported_noisy_actor_count": 0, "qa_money_flow_count": 136, "qa_money_flow_years": [2024]}
- `notes`:
  - Committees and filings now span 2020, 2022, and 2024, but the QA-backed money layer still effectively lives in the 2024 Form 460 sample.
  - That is the core reason this query still fails: the graph has campaign filing breadth, but not multi-cycle QA-backed money recurrence yet.

## Q5: validation queue

- `pass`: yes
- `metrics`: {"status_counts": {"extraction_gap": 1, "reconciled": 11}, "subject_filing_count": 3, "validation_check_count": 12}
- `notes`:
  - The queue remains small enough to review directly, and the remaining non-reconciled item is still the known $1,000 Kate Colin Schedule A extraction gap.
  - This is the first query that checks whether new breadth work is creating a manageable validation surface instead of a noisy anomaly dump.

## Recommendation

Continue the San Rafael city-office campaign filing backbone, but focus specifically on multi-cycle QA-backed money extraction and validation rather than opening county tracks or adding more schema.
