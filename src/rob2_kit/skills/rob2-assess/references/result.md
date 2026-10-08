# Specify the Result

Use this reference while choosing and constructing each Proposal Result. Use the
live `validate_proposal` schema for field shapes. Submit one choice with its reasoning per Trial in
`selections`; `save_proposal` consumes the
receipt returned by that call.

## Construct the request

Construct the scientific card before sending it. A comparative `estimate`,
`effect_measure` and optional `precision` are source strings. Selected narrative
or figure handles belong in `source_passages`; `candidate.evidence` is only for advanced typed
proof objects. Handles already carry record-kind/source metadata, but cannot
supply scientific scope, clarity, units or uncertainty.

The comparative fields describe a between-group effect, such as a difference,
ratio or hazard ratio. An arm's mean or median is a group value, even when both
arms report the same number. A comparison p-value does not turn an arm statistic
into a comparative estimate. When the report supplies only arm statistics,
use the complete `group_values` form below; do not invent a contrast by subtracting
them or place one arm's value in `estimate`.

For `exact`, `candidate.clarity` requires eight explicit facets: `outcome_definition`,
`measurement`, `time_point`, `analysis_population`, `comparison_groups`,
`effect_measure`, `source_table_meaning` and `eligible_result_choice`. Each accepts
`specified`, `unclear`, `unavailable` or `conflicting`; exact requires every facet
specified. Do not fill these from matching numbers or treat them as defaults.
An optional group value needs separate `group_id` and `value`, supported by the
source. `statistic` and `unit` are literal source labels (string or null). A null
unit preserves an unreported or unresolved unit; it does not assert dimensionless.
Put a scientific unit interpretation and its basis in `scope_rationale`, rather
than inventing a printed label. Keep `source_table_meaning` unresolved when a
statistic or unit is null, and preserve conflicting units in the rationale.
Non-null units remain strictly source-bound. Timing value and unit must be given
together or both omitted. `source_passages` is the one shared citation array;
`unknowns` a string array, and `counterevidence` an object array or `[]`.

Use `candidate: null` with grounded `missing_facts` only when no complete comparative
candidate can proceed. Unknown scope facts about an existing candidate go in the
selection's `unknowns`; they are not another selection for the same Trial. Construction feedback groups repeated defects by record field, with counts
and missing fields, so independent failures remain visible. A reading receipt
repair is separate: satisfy its exact pending source ranges before validation
can complete. Structural acceptance does not settle source entailment.

This fictional example shows the shape of one complete `validate_proposal` request
for an assessable comparative Result. It assumes supporting Evidence has already
been selected. Replace every example fact and identifier with information from
the current Trial. Use the current `expected_revision` from `get_status` and
same-Trial Evidence handles returned by the tools. Choose `relation` and
`design` from inspected Sources; the example values are not defaults.
The live schema remains authoritative. Schema validity alone does not establish
Evidence support or scientific correctness.

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

After a successful validation call, save only its receipt. Copy the
`expected_revision` returned by that call; do not recalculate it or resend the
Result cards. The server retains the validated draft and its audit identity:

```json
{
  "expected_revision": 8
}
```

For a group-bound Result, replace the comparative fields with the following
scientific fields in the complete card; omit `effect_measure`, `estimate`, and
`precision`. Keep every value as its own source string:

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

Keep `target.comparison_groups` and `reported.group_values` limited to the
requested comparison. Other arms can remain in the cited Source and context,
but do not add them to the assessment target merely for completeness. A requested
joint comparison can include multiple arms; this is not a two-arm restriction.
The saved card, not a narrower verbal summary, defines the groups assessed.

For an unavailable Result, use one selection with `candidate: null`, a concrete
source-grounded missing fact and `scope_rationale` explaining why it prevents a
complete candidate. Use an intake-condition basis only when the
captured Trial has no supported Sources:

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

For numeric timing, include the description as well as the value and unit. It
preserves the time origin or window, for example:

`{"target_window": "15 days after randomization", "target_time_value": "15", "target_time_unit": "days"}`

For a target window described in words, omit numeric timing fields:

`{"target_window": "During the course"}`

## Establish pack applicability

Identify the unit of randomization and whether the trial uses a parallel or
crossover design. Record `design_rationale` and inspected `design_evidence` from this Trial. Set `design` to `individual_parallel`,
`cluster_randomized`, or `crossover` when Sources establish that design. Each
known design requires same-Trial Evidence handles. Use `design:"unclear"` when
the design remains unresolved. The server determines pack support from `design`.

If design is unclear, use bounded discovery in the main report and relevant
methods Sources. Keep unresolved applicability explicit after that discovery;
it must remain unassessed. A word such as "group" or "site" alone does not
establish a randomization unit. Classify support from source facts, without a
default assumption of individual randomization.

Present a complete available Result with its unsupported or unresolved
applicability in the existing Proposal Review. Approval records an unassessed
disposition; it does not authorize the parallel pack for that design. Keep this
distinct from an unavailable Result, which means Result facts are missing.
For a known unsupported design, the missing requirement is the appropriate
RoB 2 pack. For unresolved design, the missing requirement is source information
establishing the design and unit of randomization.

## Choose the closest complete Result

Before selecting, inventory the complete set of materially plausible candidates
and apply the same comparison convention to each candidate. Do not enumerate
every endpoint in the Source: show one competing candidate when ambiguity could
change the selected Result, and record why the chosen candidate wins on scope.
Choose an exact assessable Result first. If none exists, choose the closest
complete non-exact assessable candidate. Use unavailable when no comparative
Result is reported for the requested outcome and the missing premise is
supported by selected Evidence.

Inventory complete main-article candidates and any materially competing
candidates in other Sources. Compare:

- event set;
- time origin or window;
- population;
- measurement or ascertainment; and
- state, severity, or other eligibility criteria.

Prefer the candidate that directly covers the requested construct with the
fewest added criteria. For an umbrella or composite request, prefer a complete
reported family over an isolated component when available. A first hit, familiar
label, important clinical result, or identical number is not a scientific
correspondence rule.

Submit one best candidate per Trial. Competing candidates inform the choice;
they are not Proposal alternatives. Replace the complete Trial card if later
review identifies a better candidate.

## Separate target from report

The target records the requested measurement, time, randomized groups, an
optional baseline-defined subgroup, and intended effect measure. The server
anchors target to randomized participants, qualified by `baseline_subgroup` when
supplied. `analysis_population` holds estimate participants and
reported exclusions. Describe the randomized arms in the requested comparison
in `comparison_groups`, preserving legitimate joint multi-arm targets. `target_measurement` is ascertainment or definition, not a
summary statistic.

Include the passages supporting the population summary in `source_passages`,
including separate passages for eligibility criteria and analyzed denominators.
Trial eligibility defines who entered this Trial. With no baseline subgroup, the
target is all participants randomized in that Trial, not everyone in an external
disease population. Eligibility alone does not make its all-randomized analysis
`narrower`. Compare analysis restrictions against the specified target; discuss
transport beyond trial eligibility separately. A genuinely broader external
target must be independently specified, not inferred from a disease label.

The reported object records the Source endpoint and quantities. Keep its
endpoint distinct from the captured requested outcome. The server supplies the
captured outcome, target metric, and `effect_of_interest:"assignment"`.

For every assessable Result, explain the complete correspondence in
`scope_rationale`, including population, outcome, measurement, time,
comparison, and analysis scope. Matching endpoint names alone do not establish
exactness. State any material difference. For `exact`, submit `clarity` with all
eight facets supported as `specified`; omitting it records all facets as unclear
and cannot establish exactness. For a non-exact Result, identify which facets
remain unclear, unavailable, or conflicting. For other assessable Results:

- `broader`: the reported event, population, or time scope is a superset;
- `narrower`: it is a subset or adds restrictions relative to the specified target;
- `component`: it is one constituent of the requested composite or category;
- `related`: the constructs overlap without one of those ordered relations.

Keep Source-owned endpoint names and quantities bound to exact selected Evidence
even when their scientific scope is equivalent. `candidate.reported_outcome`
already holds the raw quantitative-anchor endpoint label; it is not a normalized
interpretation field. Explain equivalent wording and separately sourced event
criteria in `scope_rationale` with their citations. `candidate.precision` holds
the verbatim interval expression (including stated confidence level and units),
not a reformatted explanation. Target measurement/window, analysis-population
summary and scope/population reasoning remain interpreted, evidence-grounded
prose; they need not imitate source wording. Literal binding failure by itself
does not establish scientifically incorrect meaning.

## Preserve the Source-owned quantities

Supply `effect_measure` and `estimate` for a between-group effect, or omit
both and supply complete `group_values` for every randomized group. The server
derives the canonical form. A category profile remains descriptive and cannot
proceed to comparative assessment without the comparator result.

Use the Source endpoint label in `reported_outcome`. Include
`reported_definition` only when one selected passage explicitly ties the exact
complete definition to that label; otherwise omit it.

Keep the endpoint name and at least one complete quantitative tuple in the same
Evidence item. The tuple is an effect measure plus estimate, a complete
statistic/value/unit group value, or complete category axes plus cell value.
Precision is supported separately. Do not splice an endpoint name from one
passage with all quantities from another.

For a continued or split table, use `candidate.evidence` with one
`table_multispan` object instead. Select each literal fragment separately and
give it one role: `title_or_definition`, `header`, `quantitative_row`, `unit`,
or `footnote`. It needs at least distinct `header` and `quantitative_row`
handles; include a `unit` or `footnote` span when those values are used. The
server retains every selected Evidence identity and coordinate. It does not
create a continuous quote or infer that the cited fragments form one table, so
state only the source facts those individual spans establish. Use the actual
endpoint from a cited title, definition, or header; do not substitute a generic
row label such as `Total`.

Keep quantities as Source strings. Put a comparative estimate's reported
interval in `precision`. Keep a group statistic's label, value, and unit in
their separate fields. Omit `statistic` or use `statistic: null` when the source
gives a group value but does not identify its statistic; keep `source_table_meaning` unclear and
explain the unresolved meaning in the Result rationale. A nearby verb such as
“changed” is not a statistic label. Do not invent statistics or units. For a
comparative effect, omit optional `group_values` unless the Source states one
unambiguous statistic and unit for every target group. Reported group IDs are
structural references and must match target group IDs.

## Keep one-arm descriptions out of comparative assessment

A complete descriptive profile for one randomized group is not a comparative
effect or a complete pair of group values. Do not send it into RoB 2 assessment.
Likewise, a within-group comparison of exposure periods is not a contrast of
randomized assignments when those periods were not randomized. Establish the
assignment mechanism for the selected comparison, not only for the trial as a
whole. Do not relabel before/after periods as randomized arms. Inspect reported
comparisons or complete group values for the actual randomized assignments
before concluding that their comparative Result is unavailable.
Keep the exact source passage selected as Evidence and use an unavailable Result
whose `missing_facts` names the unreported comparative result. Use
`missing_reporting` with that Evidence as the basis. Do not invent comparator
values or category cells. Labels such as mITT, per-protocol, and as-treated do
not make an otherwise comparative Result ineligible by themselves.

## Use unavailable only for a real missing premise

An unavailable Result needs concrete `missing_facts`. Each fact has exactly one
basis:

- `missing_reporting` with an Evidence handle whose passage explicitly states
  the missing input; or
- `intake_condition` with `code:"no_supported_sources"` for a captured Trial
  with zero Sources and that exact Intake condition.

A related endpoint or a repairable draft does not establish unavailability. If
the requested label is absent but a complete comparative candidate exists,
submit it with a non-exact relation for Proposal Review. A one-arm descriptive
report cannot establish a comparative effect; retain its exact passage as
Evidence and identify the missing comparator result.

Completion: every Trial has one internally coherent comparative Result or one
unavailable disposition grounded in concrete missing facts.
