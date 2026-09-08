# Specify the Result

Use this reference while choosing and constructing each Proposal Result. Use the
live `save_proposal` schema for field shapes.

## Establish pack applicability

Identify the unit of randomization and whether the trial uses a parallel or
crossover design. Record `applicability` with a concise rationale and inspected
Evidence from this Trial. Set `design:"individual_parallel"` with
`status:"supported"` for individually randomized parallel trials. Use
`status:"unsupported"` for `cluster_randomized` or `crossover`, and
`design:"unclear"` with `status:"uncertain"` for unresolved design. A supported
or unsupported classification requires same-Trial Evidence handles.

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

Choose an exact assessable Result first. If none exists, choose the closest
complete non-exact assessable candidate or profile. Use unavailable only when no
complete assessable candidate exists.

Inventory complete main-article candidates and any materially competing
candidates in other Sources. Compare:

- event set;
- time origin or window;
- population;
- measurement or ascertainment; and
- state, severity, or other eligibility criteria.

Prefer the candidate that directly covers the requested construct with the
fewest added criteria. For an umbrella or composite request, prefer a complete
reported family or profile over an isolated component when available. A first
hit, familiar label, important clinical result, or identical number is not a
scientific correspondence rule.

Submit one best candidate per Trial. Competing candidates inform the choice;
they are not Proposal alternatives. Replace the complete Trial card if later
review identifies a better candidate.

## Separate target from report

The target records the requested measurement, time, randomized groups, intended
analysis population, and intended effect measure. Describe every complete
randomized arm in `comparison_groups`. `measurement.method` is ascertainment or
definition, not a summary statistic.

The reported object records the Source endpoint and quantities. Keep its
endpoint distinct from the captured requested outcome. The server supplies the
captured outcome, target metric, and `effect_of_interest:"assignment"`.

Use `relation:"exact"` when the complete requested and reported Result scopes
are scientifically equivalent. Compare the event definition, measurement, time,
population, comparison, and analysis or effect scope. If names differ, provide
a source-grounded correspondence explanation in `relation_rationale`. A matching
name alone does not establish equivalence. For other assessable Results:

- `broader`: the reported event, population, or time scope is a superset;
- `narrower`: it is a subset or adds restrictions;
- `component`: it is one constituent of the requested composite or category;
- `related`: the constructs overlap without one of those ordered relations.

State the material difference in `relation_rationale`. Keep Source-owned endpoint
names and quantities bound to exact selected Evidence even when their scientific
scope is equivalent.

## Preserve the Source-owned quantities

Choose one reported form:

- `comparative_effect` for a between-group estimate;
- `group_bound_values` for one complete statistic, value, and unit per randomized
  group;
- `single_group_category_profile` for a complete category profile reported for
  one randomized group.

Use the Source endpoint label in `endpoint.name`. Include
`endpoint.definition` only when one selected passage explicitly ties the exact
complete definition to that label; otherwise omit it.

Keep the endpoint name and at least one complete quantitative tuple in the same
Evidence item. The tuple is an effect measure plus estimate, a complete
statistic/value/unit group value, or complete category axes plus cell value.
Precision is supported separately. Do not splice an endpoint name from one
passage with all quantities from another.

Keep quantities as Source strings. Do not invent statistics or units. For a
comparative effect, omit optional `group_values` unless the Source states one
unambiguous statistic and unit for every target group. Reported group IDs are
structural references and must match target group IDs.

## Keep one-arm category profiles assessable

Missing comparator values do not make a fully reported one-arm categorical
profile unavailable. Use `single_group_category_profile`, retain all randomized
arms in the target, and point `reported.group_id` to the supported arm.

Set `category_axis_names` to the ordered non-treatment dimensions. Each cell's
`category_axes` contains one exact Source label for every dimension, in that
order. Put the shared population or denominator in `denominator_basis`. Preserve
each opaque cell value, including a combined count and percentage. Never invent
comparator cells.

## Use unavailable only for a real missing premise

An unavailable Result needs concrete `missing_facts`. Each fact has exactly one
basis:

- `missing_reporting` with an Evidence handle whose passage explicitly states
  the missing input; or
- `intake_condition` with `code:"no_supported_sources"` for a captured Trial
  with zero Sources and that exact Intake condition.

A related endpoint, missing comparator for a complete one-arm profile, or a
repairable draft does not establish unavailability. If the requested label is
absent but a complete related candidate exists, submit it with a non-exact
relation for Proposal Review.

Completion: every Trial has one internally coherent assessable Result or one
unavailable disposition grounded in concrete missing facts.
