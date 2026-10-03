# Simple primary Result proposal check: EMPEROR-Reduced

One model-owned proposal-only invocation ran on detached frozen
`bef6a06c133432ed3c45787bbaed4ebf5c6ae36a`, exact `gpt-6-luna` / Medium,
using the same direct-MCP launcher and controls as the failed Allsop check.
There was no operator repair, retry, second case, domain assessment, full
benchmark, production/schema edit or merge. Allsop traces remain preserved.

## Why this case

EMPEROR-Reduced was absent from the local development/proposal-probe inventory.
Selection used the primary published report and Code benchmark source metadata,
not RoB reference/gold labels. The paper explicitly identifies a prespecified
first-event cardiovascular-death/heart-failure-hospitalization composite, a
single primary hazard ratio and interval, randomized arms, an ITT population,
and trial follow-up. The original Code benchmark requested outcome is that
same primary composite and time-to-first-event concept.

The normal user target description names the composite, assigned comparison,
all-randomized population, hazard-ratio measure and trial-follow-up window. It
contains no published estimate/interval, desired relation or page locator.
Median follow-up is a summary, not a common fixed-duration event risk. The
candidate and selection criterion were reported before launch.

The required source was
`/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases/emperor-reduced`;
the five published PDFs came from that benchmark's corresponding Code corpus.
All PDF hashes match the original captured identities. The archived registry
raw JSON was not retained in the dossier. Reconstruction did not match its
hash and was not used. Fresh **normal production intake** therefore captured
all five unchanged published PDFs, with registry lookup undeclared rather than
substituting live or fabricated registry data. The archived case and partial
pre-inference setup are untouched. Two pre-inference preparation assertions
needed correction (missing registry file; absent optional state key); neither
setup invoked a model. The one final model run had no inherited candidate,
reasoning, approval, domains or previous model session.

## Result

**No proposal was validated or saved.** All four native validation attempts
failed, exhausting the proposal allowance after **97.868 seconds**. All 15
started MCP calls completed. One initial attempt to read all 12 report pages
exceeded the declared `maxItems:10` limit; the model recovered using bounded
calls. It then durably read all 12 main-report pages, and native status confirmed
the bounded main reading pass complete. Supplements were not read.

The first draft correctly extracted **HR 0.75, 95% CI 0.65–0.86**, from native
primary-source passages. All drafts claimed `exact`, and their rationale kept
full trial follow-up distinct from a fixed 16-month risk. Selected passages also
support the first-event endpoint, ITT analysis and randomized comparison.
Nevertheless, a full scientific exactness claim was never accepted or bound.

| Attempt | Actual blocking input errors | Total errors / unrelated missing-Result branch |
|---|---|---:|
| 1 | Invented target/outcome/population/arm/measure/CI fields; numeric estimate instead of source string; missing flat required fields; null counterevidence | 35 / 13 |
| 2 | Prose design instead of enum; arms as one string; Evidence handles as strings; invented confidence_interval and p_value | 24 / 16 |
| 3 | Arms as strings instead of objects; Evidence objects omit kind; assessment handles changed to objects | 25 / 14 |
| 4 | Arms use name/description instead of required id/assignment | 23 / 14 |

`proposal-attempts.json` and `events.jsonl` contain the complete exact arguments
and tool outputs. `structural-burden.json` separates the relevant errors from
unselected-union noise and includes the actual advertised field declarations.
The final attempt fixed narrative Evidence and assessment handles, but still
failed on arm objects. All later drafts omitted the explicit `effect_measure`,
all drafts omitted known-design `design_evidence`, and exact cards omitted
scope clarity. Those deeper requirements never reached application validation.

Some scientific field interpretation also remains wrong: later
`target_measurement:"hazard ratio"` confuses outcome ascertainment with effect
measure, and `baseline_subgroup` restates the entire requested population rather
than identifying a subgroup restriction. These are separate from the immediate
syntax failures. The full-source reading and correctly extracted point estimate
do not repair either problem.

Four selected source premises are archived in `selected-evidence.json`:

- Main physical page1 lines30–39: randomization/arms and primary quantitative tuple;
- page3 lines56–63: adjudicated primary composite and first-event analysis;
- page5 lines9–19: ITT all-randomized analysis and Cox model;
- page7 lines15–37: data cutoff, variable follow-up, vital-status/loss information,
  median duration, and repeated primary estimate.

There are **zero canonical Result leaf bindings**, no populated `scope_review`,
no approval and no domain records. Invalid-draft handles must not be described
as a validated scientific Result. The median-window distinction is source-based
recognition in prose, not a benefit attributable to scope review. No decision
benefit or accuracy/benchmark-agreement gain is established.

## What the comparison establishes

The frozen **actual advertised FastMCP declarations are byte-identical** to the
preceding Allsop run (SHA256
`fb2b982e40ebe87fef9bda6dd8135026bf6a7fe9a4fa7fb24f4bc0f0c2692ea8`).
The full declarations are in `frozen-mcp-tools.json`; the complete relevant
input/output declaration is also isolated in `validate-proposal-declaration.json`.
The native rollout verifies exact model and Medium effort (`model-settings.json`).

A simple explicit primary quantitative Result, genuinely matching the normal
requested target, and completed source reading did **not** remove construction
failure in this direct runtime. Allsop's complex/mismatched target therefore
cannot be the sole explanation. This does not isolate the cause to model
behavior, interface design or tool-schema delivery. Provider request/tool
payloads are absent from native logs, so complete schema visibility at the model
service boundary remains unverified. The launcher uses short custom instructions;
the complete installed skill example is not automatically included.

The declaration has conditional scientific requirements enforced only later:
`effect_measure` and `estimate` are individually optional properties but must
be paired for a comparative estimate; known design requires explicit Evidence;
exact requires eight specified clarity facets. The last two are still needed
for trustworthy interpretation. Current union error output adds 13–16 irrelevant
failures per attempt. These are concrete visibility/repair burdens to investigate,
not justification to guess aliases, silently coerce semantics or add more fields.

## Honest representation when exact support is absent

The offline inspection used existing frozen code and installed fictional
examples, without editing the model workspace. Five controls passed
(`no-exact-result-offline.json`):

1. `exact` with omitted clarity produces eight scope-facet repairs.
2. A complete nearby comparative Result can use explicit `related` with
   unresolved/conflicting clarity and a scope rationale; conversion preserves
   the requested window. Use broader/narrower/component only when those full
   scope relationships are source-supported, not just one matching dimension.
3. If no complete comparative Result can be supported, `MissingResultProposal`
   allows explicit `ambiguous`/`unavailable` and concrete source-grounded missing
   facts, with a separate missing-fact justification.
4. Empty missing facts are rejected.
5. `no_supported_sources` cannot be used when the captured Trial has Sources.

An absent exact candidate is **not** by itself an unavailable Result: retain a
complete non-exact candidate honestly when one exists. Missing-reporting basis
must use inspected same-Trial Evidence; registry/source absence cannot be
invented. Structural selection of a source handle does not prove that its quote
entails missing reporting. Absence after incomplete reading must stay unresolved.
The missing-Result canonical shape stores requested outcome and missing facts,
not a complete target tuple; detailed missing target scope therefore belongs in
those concrete facts/justification. For assessable candidates, target window is
caller-owned interpretation: preservation requires host/researcher review and is
not a server semantic entailment guarantee. Never retarget or fabricate a
numerical extraction to satisfy the parser.

## Usage and preservation

Actual durable token totals were checked against each response record:

| Usage | Tokens |
|---|---:|
| Input | 386,501 |
| Cached input | 334,592 |
| Uncached input | 51,909 |
| Output | 2,819 |
| Reasoning output, included in output | 470 |

Input was telemetry-only; 5k output, 20 tools, eight-minute wall, two-minute idle,
four proposal attempts and two identical-error controls remained. No overshoot
occurred. CLI exit0 does not mean task success. There is no final response file
because the host stopped after the fourth rejection. No billed-dollar charge or
verified per-token rate was present; no guessed dollar estimate is reported.
Original Code database and published PDF hashes are unchanged. No production
fields were added, and no further paid case is authorized by this one-run task.
