# Specify the Result

Each Trial gets one Proposal selection: the reported result that RoB 2 will
assess, or an unavailable disposition. Build the complete request first, call
`validate_proposal`, then `save_proposal` with only the revision that
validation returns. The live `validate_proposal` schema is authoritative; never
send placeholders or partial objects to discover it.

## Choose the closest complete Result

Read the main report first, then compare the materially plausible candidates on:

- event set or construct (overall survival, recurrence-free survival and a
  survival/hospitalization composite are different outcomes);
- time origin, time point or window;
- population (all randomized, a subgroup, an analysed subset);
- measurement or ascertainment;
- severity or other eligibility criteria within the outcome.

Choose in this order: an exact assessable Result; else the closest complete
comparative Result (the one covering the requested construct with the fewest
added criteria; for a composite request, the complete composite over one
component); else an unavailable Result. Do not rank by name similarity,
statistical significance, clinical importance or where the number appears.
Matching numbers do not prove matching endpoints. If materially different
candidates remain and the choice would change the question, ask the researcher
with the actual alternatives. Apply shared constraints the same way across
Trials.

## Establish pack applicability

This pack covers individually randomized parallel trials. From this Trial's
Sources, identify the unit of randomization and whether the design is parallel
or crossover. Set `design` to `individual_parallel`, `cluster_randomized` or
`crossover` with `design_rationale` and same-Trial `design_evidence`, or to
`unclear` when the Sources do not settle it. Unsupported or unclear designs stay
unassessed after Proposal Review; they are distinct from an unavailable Result.

## Construct the request

The **target** records what was requested: `target_measurement`,
`target_window` (and optional numeric `target_time_value` with
`target_time_unit`), the randomized `comparison_groups`, an optional
`baseline_subgroup` and the `intended_effect_measure`. Without a subgroup the
target is everyone randomized in this Trial.

The **reported** fields record what the Source says, as literal strings:
`reported_outcome` (the endpoint label), optional `reported_definition` (only if
one passage ties the full definition to that label), `analysis_population`
(who was analysed and reported exclusions), and either a between-group
`effect_measure` and `estimate` with optional `precision` (the verbatim
interval), or `group_values` for every target group (`group_id`, `statistic`,
`value`, `unit`; use null for an unprinted statistic or unit). An arm's mean is
a group value, not a comparative estimate; do not subtract arms to invent one.
Put other comparison statistics such as p-values in `reported_statistics`.

`relation` states how the report relates to the target:

- `exact`: requires `candidate.clarity` with all eight facets
  (`outcome_definition`, `measurement`, `time_point`, `analysis_population`,
  `comparison_groups`, `effect_measure`, `source_table_meaning`,
  `eligible_result_choice`) set to `specified`;
- `broader`: the reported event, population or time scope is a superset;
- `narrower`: a subset, or added restrictions;
- `component`: one constituent of a requested composite;
- `related`: overlapping constructs without one of those relations.

Explain the correspondence in `scope_rationale` and the population in
`population_rationale` (separate baseline eligibility from exclusions and
missing observations). Unknown scope facts go in `unknowns`; conflicting
passages in `counterevidence`.

This fictional example shows a complete request. Replace every value:

```json
{
  "selections": [
    {
      "trial_id": "fictional_quiz_trial",
      "relation": "narrower",
      "candidate": {
        "design": "individual_parallel",
        "design_rationale": "Learners were individually randomized to two parallel teaching groups.",
        "design_evidence": [
          "eh_0000000000000001"
        ],
        "target_measurement": "Number of correct answers on the course quiz",
        "target_window": "15 days after randomization",
        "comparison_groups": [
          {
            "id": "practice",
            "assignment": "Spaced practice"
          },
          {
            "id": "review",
            "assignment": "Single review session"
          }
        ],
        "baseline_subgroup": null,
        "intended_effect_measure": "Mean difference",
        "reported_outcome": "Course quiz score",
        "reported_definition": null,
        "analysis_population": "Randomized learners with observed course quiz scores; handling of learners without observed scores is not reported.",
        "effect_measure": "Mean difference",
        "estimate": "2.3",
        "target_time_value": "15",
        "target_time_unit": "days"
      },
      "scope_rationale": "The reported mean difference is limited to learners with observed quiz scores, while the assignment target includes all randomized learners. The selected passage supports the reported quiz endpoint at 15 days, which is the target time point; the observed-score restriction makes the relation narrower.",
      "population_rationale": "The target is all randomized learners. The reported analysis includes learners with observed scores, while exclusions and missing observations are not fully reported.",
      "source_passages": [
        "eh_0000000000000001"
      ],
      "unknowns": [
        "The report does not establish how learners without observed scores were handled."
      ],
      "counterevidence": [
        {
          "evidence": "eh_0000000000000002",
          "implication": "A separate fictional report states that learners without observed scores were excluded after randomization, which conflicts with treating the reported population as all randomized learners."
        }
      ]
    }
  ],
  "expected_revision": 7
}
```

Then save with the revision returned by validation:

```json
{
  "expected_revision": 8
}
```

For a result reported only as group values, replace `effect_measure`,
`estimate` and `precision` with:

```json
{
  "analysis_population": "All randomized learners with quiz results at day 15.",
  "group_values": [
    {
      "group_id": "practice",
      "statistic": "mean",
      "value": "18.4",
      "unit": "points"
    },
    {
      "group_id": "review",
      "statistic": "mean",
      "value": "16.1",
      "unit": "points"
    }
  ],
  "reported_outcome": "Course quiz score"
}
```

Keep `comparison_groups` and `group_values` to the requested comparison; other
arms stay in the Sources. A multi-arm joint comparison is allowed when requested.

## Use unavailable only for a real missing premise

Use `candidate: null` only when no complete comparative result exists for the
requested outcome, with `missing_facts` grounded in a passage that shows what is
missing (`missing_reporting`), or `intake_condition` with
`code:"no_supported_sources"` when the Trial has no Sources:

```json
{
  "selections": [
    {
      "trial_id": "fictional_quiz_trial",
      "relation": "unavailable",
      "candidate": null,
      "scope_rationale": "The selected passage captures the missing report; it does not support an invented estimate.",
      "population_rationale": null,
      "source_passages": [
        "eh_0000000000000001"
      ],
      "unknowns": [],
      "counterevidence": [],
      "missing_facts": [
        {
          "fact": "Quiz result at 15 days after randomization",
          "basis": {
            "kind": "missing_reporting",
            "evidence": "eh_0000000000000001"
          }
        }
      ]
    }
  ],
  "expected_revision": 7
}
```

A one-arm description, or a before/after comparison of non-randomized periods,
is not a comparative result: keep its passage as Evidence and name the missing
comparator result. A related endpoint or a repairable draft is not
unavailability: submit the complete candidate with a non-exact relation.
