# Specify the Result

Use this reference while choosing and constructing each Proposal Result. Use the
live `validate_proposal` schema for field shapes; `save_proposal` consumes the
receipt returned by that call.

## Construct the request

This fictional example shows the shape of one complete `validate_proposal` request
for an assessable comparative Result. It assumes supporting Evidence has already
been selected. Replace every example fact and identifier with information from
the current Trial. Use the current `expected_revision` from `get_status` and
same-Trial Evidence handles returned by the tools. Choose `relation` and
`applicability` from inspected Sources; the example values are not defaults.
The live schema remains authoritative. Schema validity alone does not establish
Evidence support or scientific correctness.

```json
{
	"results": [
		{
			"kind": "assessable",
			"trial_id": "fictional_quiz_trial",
			"relation": "narrower",
			"relation_rationale": "The reported mean difference is limited to learners with observed quiz scores, while the assignment target includes all randomized learners.",
			"applicability": {
				"design": "individual_parallel",
				"rationale": "Learners were individually randomized to two parallel teaching groups.",
				"evidence": ["eh_0000000000000001"]
			},
			"target": {
				"measurement": {"method": "Number of correct answers on the course quiz"},
				"time_point_or_window": {"kind": "quantified", "description": "15 days after randomization", "value": "15", "unit": "days"},
				"comparison_groups": [
					{"id": "practice", "assignment": "Spaced practice"},
					{"id": "review", "assignment": "Single review session"}
				],
				"baseline_subgroup": null,
				"intended_effect_measure": "Mean difference"
			},
			"reported": {
				"form": "comparative_effect",
				"effect_measure": "Mean difference",
				"estimate": "2.3",
				"analysis_population": "Randomized learners with observed course quiz scores; handling of learners without observed scores is not reported.",
				"endpoint": {"name": "Course quiz score"}
			},
			"passage_refs": ["eh_0000000000000001"]
		}
	],
	"assessments": [
		{
			"trial_id": "fictional_quiz_trial",
			"evidence_basis": ["eh_0000000000000001"],
			"scope_justification": "The selected passage supports the reported quiz endpoint at 15 days, which is the target time point; the observed-score restriction makes the relation narrower.",
			"population_justification": "The target is all randomized learners. The reported analysis includes learners with observed scores, while exclusions and missing observations are not fully reported.",
			"unknowns": ["The report does not establish how learners without observed scores were handled."],
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

After a successful validation call, save only its receipt. Copy the exact
`reasoning_id` and `expected_revision` returned by that call; do not invent or
recalculate either value, and do not resend the Result cards:

```json
{"expected_revision": 8, "reasoning_id": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
```

For a group-bound Result, use one `group_values` array and keep every value as
its own source string:

```json
{
	"form": "group_bound_values",
	"analysis_population": "All randomized learners with quiz results at day 15.",
	"endpoint": {"name": "Course quiz score"},
	"group_values": [
		{"group_id": "practice", "statistic": "mean", "value": "18.4", "unit": "points"},
		{"group_id": "review", "statistic": "mean", "value": "16.1", "unit": "points"}
	]
}
```

For an unavailable Result, provide a concrete missing fact and an assessment
with a missing-fact justification. Use an intake-condition basis only when the
captured Trial has no supported Sources:

```json
{
	"results": [
		{
			"kind": "unavailable",
			"trial_id": "fictional_quiz_trial",
			"relation": "unavailable",
			"missing_facts": [
				{
					"fact": "Quiz result at 15 days after randomization",
					"basis": {"kind": "missing_reporting", "evidence": "eh_0000000000000001"}
				}
			]
		}
	],
	"assessments": [
		{
			"trial_id": "fictional_quiz_trial",
			"evidence_basis": ["eh_0000000000000001"],
			"missing_fact_justification": "The selected passage captures the missing report; it does not support an invented estimate.",
			"unknowns": [],
			"counterevidence": []
		}
	],
	"expected_revision": 7
}
```

For numeric timing, include the description as well as the value and unit. It
preserves the time origin or window, for example:

`{"kind": "quantified", "description": "15 days after randomization", "value": "15", "unit": "days"}`

Use `described` when the source gives a timing window in words:

`{"kind": "described", "description": "During the course"}`

## Establish pack applicability

Identify the unit of randomization and whether the trial uses a parallel or
crossover design. Record `applicability` with a concise rationale and inspected
Evidence from this Trial. Set `design` to `individual_parallel`,
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
supplied. `reported.analysis_population` holds estimate participants and
reported exclusions. Describe every complete randomized arm in
`comparison_groups`. `measurement.method` is ascertainment or definition, not a
summary statistic.

Include the passages supporting the population summary in passage_refs,
including separate passages for eligibility criteria and analyzed denominators.

The reported object records the Source endpoint and quantities. Keep its
endpoint distinct from the captured requested outcome. The server supplies the
captured outcome, target metric, and `effect_of_interest:"assignment"`.

For every assessable Result, explain the complete correspondence in
`relation_rationale`, including population, outcome, measurement, time,
comparison, and analysis scope. Matching endpoint names alone do not establish
exactness. State any material difference. For other assessable Results:

- `broader`: the reported event, population, or time scope is a superset;
- `narrower`: it is a subset or adds restrictions;
- `component`: it is one constituent of the requested composite or category;
- `related`: the constructs overlap without one of those ordered relations.

Keep Source-owned endpoint names and quantities bound to exact selected Evidence
even when their scientific scope is equivalent.

## Preserve the Source-owned quantities

Choose one reported form for a comparative Result:

- `comparative_effect` for a between-group estimate;
- `group_bound_values` for one complete statistic, value, and unit per randomized
  group.

Use the Source endpoint label in `endpoint.name`. Include
`endpoint.definition` only when one selected passage explicitly ties the exact
complete definition to that label; otherwise omit it.

Keep the endpoint name and at least one complete quantitative tuple in the same
Evidence item. The tuple is an effect measure plus estimate, a complete
statistic/value/unit group value, or complete category axes plus cell value.
Precision is supported separately. Do not splice an endpoint name from one
passage with all quantities from another.

For a continued or split table, use top-level `evidence` with one
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
their separate fields. Do not invent statistics or units. For a
comparative effect, omit optional `group_values` unless the Source states one
unambiguous statistic and unit for every target group. Reported group IDs are
structural references and must match target group IDs.

## Keep one-arm descriptions out of comparative assessment

A complete descriptive profile for one randomized group is not a comparative
effect or a complete pair of group values. Do not send it into RoB 2 assessment.
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
