# Declaring exact Results

The Run proposal can carry exact Trial × Result identities before autonomous
Preparation when the project root contains a `rob2.yaml` file with pre-resolved
ResultSpec inputs.

```yaml
schema_version: 1

outcome_targets:
  - id: mortality-30d
    label: Mortality at 30 days

results:
  - result:
      result_id: result:trial-a-mortality-30d
      trial_id: trial:trial-a
      randomization_id: randomization:trial-a
      comparison:
        experimental_arm_id: arm:treatment
        comparator_arm_id: arm:control
      effect_of_interest: assignment
      outcome_construct: Mortality
      measurement_instrument: Vital status
      time_point: 30 days
      analysis_population: Intention to treat
      analysis_model: Risk ratio, unadjusted
      effect_measure: RR
      source_locator: report.pdf p. 8 table 2
    estimate:
      value: "0.82"
      interval_lower: "0.66"
      interval_upper: "1.02"
    provenance_note: Resolved from the primary report.
```

Each declared Result must reference a Trial issued from its `input/` folder and
must have a unique `result_id`. Every declared Result receives an independent
Preparation scope, Evidence Bundle, Assessment, and static report. Multiple
Results may therefore share one Trial and secured Source inventory without
sharing Result-specific judgments.

Projects without declared `results` use proposal discovery after Source-role
resolution. An attributable review extracts provenance-bound Reported endpoint,
Randomization, and Arm candidates from eligible result-bearing full-text
reports; human promotion establishes Outcome-target and Trial-design identity,
and a later semantic mapping review proposes Trial-specific Result candidates.
A complete accepted mapping may materialize its ResultSpec revision when the
proposal is confirmed. An incomplete mapping explicitly reports pending Result
identity and proceeds through structured Result resolution before
outcome-dependent work begins.
