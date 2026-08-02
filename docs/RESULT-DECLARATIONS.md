# Declaring exact Results

The Companion Ready view can show exact Trial × Result identities before
autonomous Preparation when the project root contains a `rob2.yaml` file with
pre-resolved ResultSpec inputs.

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
Preparation scope, Evidence Bundle, Assessment, and Review case. Multiple
Results may therefore share one Trial and secured Source inventory without
sharing Result-specific judgments.

Projects without declared `results` remain compatible with the agent-driven
Result-resolution workflow. In that mode the Ready view explicitly reports
that exact Result identity is pending and Preparation resolves the single
engine-issued Result before outcome-dependent work begins.
