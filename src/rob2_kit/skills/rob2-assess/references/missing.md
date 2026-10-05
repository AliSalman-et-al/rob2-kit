# Assess missing outcome data

Use this reference for Domain 3. The approved Result fixes the outcome and time
point; the returned question cards fix answer direction and activation.

Every active answer is accompanied by a concise justification, an `unknowns`
array (use `[]` when none are identified), and a `counterevidence` array. A
counterpoint refers to the answer's zero-based basis index, for example:

```json
"counterevidence": [{"evidence": ["eh_0123456789abcdef"], "implication": "This passage limits the strength of the selected answer."}]
```

Inactive branch answers may be omitted or retained without fabricated reasoning;
the server commits only the dependency-closed active path.

## Scientific authority and source recovery

Use the official question elaborations and shared response guidance delivered
by `get_domain_context`, with the exact approved Result and activation path.
The opt-in `official_d3_prototype` profile replaces operational rules with
`official_guidance.sections`; cards identify the relevant source locator.
Follow its question-specific permitted options. The official source version,
hash and full-source URL accompany the text, including the distinction between
available outcomes excluded from analysis and measurements not obtained.

Full sources: [RoB2 guidance, 22 August 2019](https://www.riskofbias.info/welcome/rob-2-0-tool/current-version-of-rob-2)
and [Cochrane FAQs, Domain 3](https://www.cochrane.org/learn/courses-and-resources/cochrane-methodology/risk-bias/about-risk-bias-2-rob-2).
The FAQ's unknown-extent and method-list questions supplement the official
elaborations. This reference introduces no additional answer thresholds,
certainty requirements, method whitelist or mandatory sensitivity procedure.

Use `read_pages` to inspect returned source windows; retain source/page/line
coordinates and scoped retrieval limits in the draft.

When the availability premise remains unresolved, use the active comparison
card's full Source inventory to inspect unopened supplements or combined
protocol documents. Search for concrete study wording such as the outcome
status, withdrawal or loss-to-follow-up labels, and the reported time point;
`missing outcome data` alone may not occur in the report. Widen the Source
scope or continue a cached cursor only as needed, and stop when inspected
evidence supports a reasonable availability judgment or the remaining
uncertainty is bounded. Outcome-specific observed/expected follow-up time can
inform a probable judgment without becoming a participant-observation fraction;
vital status alone does not ascertain nonfatal components. If the captured
Sources and bounded page windows support no reasonable inference, document
that limit instead of treating an empty Source group or a no-hit search as
evidence of missing outcomes.

For a time-to-first-event composite, reconcile the report's definition of incomplete
follow-up with component-specific missing status. A dated, adjudicated qualifying
first event can establish that participant's primary event observation even if later
vital status is unknown. Later follow-up may still matter for a mortality or recurrent-
event Result. Do not add overlapping component-status and composite-follow-up
counts or transfer them to another endpoint. Retain the definition and overlap
uncertainty before supplying observed counts; this distinction supplies no automatic
answer or risk label.

## Reconcile availability

Keep these quantities distinct for each arm and time point:

- randomized participants;
- participants reported to complete study or follow-up (`completed`);
- participants with the outcome observed;
- participants included in the reported analysis;
- participants whose outcomes were imputed; and
- post-randomization exclusions; and
- outcome events, which are a numerator rather than an observed-participant count.

An analyzed count is not necessarily an observed count. Imputed outcomes count
as missing outcome data for RoB 2. Treatment discontinuation is not missing
outcome data when follow-up and outcome ascertainment continued.

When completion and endpoint availability are both reported, record them as
separate source-bound quantities before applying the official questions. The
existing preview accepts `completed` alongside `observed`, `analyzed` and
`imputed`; it does not turn completion into observed outcomes or infer overlap
between those groups. Preserve the row's outcome-status and censoring semantics
and inspect the cited passages when their relationship is unresolved.

Questions 2.3, 2.6, and 3.1 may include compact `missing_data` rows. Give each
row a comparable arm, population, unit, and time point. Use a row-level `basis`
only to narrow or add to the answer's Evidence. The server calculates
differences and fractions only after scopes match and preserves conflicting
reports without choosing the scientific answer. For D2.3 and D2.6, these rows
describe deviations or analysis populations; they do not become observed
outcomes. Only an explicit `observed` count participates in missing-count
arithmetic.

When participant-count comparisons support the 3.1 answer, retain the
source-supported `missing_data` rows in `save_domain_judgment`. Give each row its
named scope and keep the reported analysis population distinct from the approved
randomized target. Leave `observed` unknown when only analyzed or event counts
are established. Rate-only evidence and explicit ascertainment statements do
not require invented counts or denominators.

Use `get_domain_context` with those rows when a preview would resolve an arithmetic
or scope question. Every preview row needs a nonempty `basis` containing
current-Trial Evidence references: no answer exists to supply inherited Evidence.
Inspect `comparison_cards[].missing_data` for differences, fractions, and
conflicting reports. The preview changes no checkpoint or State revision and is
not an additional mandatory call. Retain the chosen rows with the answer; omit
row `basis` there only to reuse answer Evidence that supports those counts.

Check each input against its source passage before using the arithmetic. The
helper subtracts supplied observed counts from randomized counts; it does not
extract counts or sum grouped departures. Keep unknown observed counts unknown.
Skip the preview when an explicit ascertainment statement resolves availability
without arithmetic.

When a row includes typed `semantics`, treat it as scope metadata, not as a
shortcut to a signalling answer. `event_count` is an event numerator and never
means that every participant's outcome was observed. `analyzed`, `safety`, and
`per_protocol` roles are denominators or populations, not availability. Keep
administrative censoring, loss to follow-up, treatment change, imputation, and
post-randomization exclusions as distinct facts. The server preserves these
fields and only derives `randomized - observed`; it does not decide whether a
censored participant is informative.

## Draft and submit

Resolve the active question path from the official options and activation
predicates. Explain the source-grounded reasoning, unresolved information and
counterevidence for each active answer. Inspect relevant unopened Sources
before describing report absence, or state a bounded stopping rationale.
Use the official guidance to judge the evidence; the arithmetic preview and
source-reading receipts do not choose an answer or risk label.
