# Three-Trial reassessment after issues #298–#303

The updated kit completed all three assessments with substantially fewer searches,
but this run does not establish a D1–D5 accuracy improvement. One changed D4 judgment
rests on a rationale that contradicts the question's possibility criterion.
Proposal construction also became more error-prone. These findings justify a
small schema-example experiment, not more scientific rules or retrieval machinery.

## Conditions and artifacts

The development cases were selected by the prior campaign's worst optimistic
five-Domain agreement bounds. Prompts used abstract-defined Results. See the
[selection analysis](2026-09-08-suster-domain-analysis.md) and
[research review](2026-09-08-agent-evidence-research.md).

Baseline used `f2304` and updated used committed revision
`b045803df9ee82e1133a3443d7cb50cdc80acc07`. The subsequent documentation-only commit
`4deb159` describes the fresh-workspace upgrade boundary. Both conditions used
Codex CLI 0.153.4, requested `gpt-5.6-luna` with medium reasoning, Python 3.13.13,
and matching versions of all 72 non-kit dependencies. The CLI logs do not expose
independent runtime confirmation of the model and effort.

All supplied files, captured registry bytes, and extracted text hashes match
between conditions. Registry retrieval timestamps differ. Both used clean
workspaces and the same frozen short prompts. A researcher reviewed and approved
each Proposal through the CLI, then resumed that same session with `Continue.`
The baseline needed Result corrections for Holm's target population and the
GLUCOCOVID arm values; updated Proposals needed no such correction. There was no
Domain-answer coaching. Baseline totals below include those correction turns.

Local audit artifacts are under sibling directory `rob2-kit-testing/suster/`:

- `20260908-cycle01-ranked-baseline/`: manifest, installed wheel, dependencies,
  source copies, JSONL logs, finalized bundles, and parsed `analysis.json`.
- `20260908-cycle01-ranked-updated/`: the corresponding updated artifacts,
  researcher approval logs, `review-observations.json`, and `paired-summary.json`.

The paired summary records each raw log's SHA-256 and both sets of metrics.
All three updated bundles pass the kit verifier and standalone verifier. Earlier
baseline v0.5 bundles also pass both updated verifiers. Bundle validity establishes
integrity and contract compliance, not scientific correctness.

## Domain outcomes

`L` means Low, `SC` Some concerns, and `H` High. Each cell lists D1 through D5.

| Abstract-defined Result | Baseline | Updated |
|---|---|---|
| Holm 2021: 28-day mortality, OR 0.49 [0.08, 2.79] | SC, H, H, L, SC | SC, H, SC, L, SC |
| Al Qahtani 2020: ventilation, RR 0.67 [0.22, 2.0] | SC, L, L, L, SC | SC, L, L, L, L |
| GLUCOCOVID: primary composite, 14/35 versus 14/29 | SC, L, L, H, L | SC, L, L, L, L |

The prior outcome references do not supply an unambiguous gold join for all three
new abstract-defined Results. Do not score these as 15 independent gold-labeled
cells or reuse adverse-event labels for these endpoints. This is one stochastic
draw per condition on inspected development trials, with several interventions
bundled together. Neither causality nor generalization can be estimated here.

## Scientific premise audit

**D1 remained unchanged.** GLUCOCOVID's rationale still interprets a concealed
medical-record-number formula as probably random, without establishing the random
component. It also treats age imbalance and prognostic importance as evidence of a
randomization problem. A chance imbalance in a small trial does not by itself
establish that problem. The kit delivered the relevant material; this is an
interpretation failure rather than demonstrated missing retrieval.

**Holm D2 remains unresolved.** The model attributes an inappropriate assignment
analysis to two exclusions among 33 randomized participants. One withdrew consent;
the other could not receive ABO-compatible plasma. The rationale does not establish
whether their mortality outcomes were available but excluded from analysis, or
missing. That distinction matters. Existing D2 guidance explicitly separates
missing outcomes from inappropriate exclusion of available outcomes. The observed
reasoning skips that premise; this audit does not assign a definitive replacement
Domain label without it.

**Holm D3 changed from High to Some concerns.** The model now distinguishes possible
dependence of missingness on outcome from likely dependence and cites the stated
exclusion reasons against likelihood. Its possibility rationale still relies
largely on inability to rule out dependence. The new arithmetic preview was used
zero times, so this run provides no evidence of its effect on judgments.

**D4 contains the clearest unsupported reassurance.** GLUCOCOVID's updated 4.4
rationale acknowledges possible influence on judgment-based ICU/NIV components,
then answers probably no because mortality is objective and the report provides
no evidence that assessment actually differed. The question asks whether knowledge
could influence assessment. Reassurance about one composite component does not
resolve the others, and actual influence is a separate question. This answer ends
the branch before 4.5 and changes D4 from High to Low. Al Qahtani's ventilation
rationale similarly emphasizes recording the event and absence of demonstrated
ascertainment effects without adequately examining the decision to initiate
ventilation. The existing reference and question cards already explain both
distinctions. These are failures to apply delivered guidance; adding the same
warning again has no demonstrated value.

**D5 still accepts incomplete chronology arguments.** Al Qahtani changes from Some
concerns to Low after the model accepts protocol specification of the endpoint
while acknowledging that timing of plan finalization relative to unblinded
outcomes is not established. The inspected protocol identifies itself as Version 8;
an endpoint citation alone does not establish the necessary plan chronology or
analysis detail. GLUCOCOVID remains Low based on Methods and an a-priori interim
analysis statement while acknowledging that the finalized plan is unavailable.
The recorded rationale supplies no affirmative chronology premise. This does not
mean a dated standalone plan is always mandatory; a supported indirect inference
can suffice. The kit's existing guidance already requires a timing basis and says
that an a-priori label alone is insufficient. Holm appropriately retains the
reported discrepancy between the registered three-month and analyzed 28-day
mortality windows in its reasoning.

## Workflow measurements

| Measure, all three runs | Baseline | Updated |
|---|---:|---:|
| Search calls | 105 | 9 |
| Zero-hit searches | 46 | 4 |
| Tool calls marked failed or carrying an error | 2 | 21 |
| Structured repair responses | 8 | 9 |
| Domain-context response bytes | 728,859 | 1,021,879 |
| Input tokens | 11,943,311 | 13,354,496 |
| Cached input tokens | 11,258,368 | 12,846,336 |
| Uncached input tokens | 684,943 | 508,160 |
| Output tokens | 36,174 | 41,697 |

Counts come from completed MCP call events and CLI turn-usage records. Failed
calls and structured repair responses are separate categories. Context bytes are
UTF-8 sizes of compact decoded responses, not tokens. Search reduction is consistent
with the changed reading/discovery workflow, but total input and output increased.
These are observed CLI tokens, not subscription charges or whole-task costs.

The updated run attempted 25 Proposal saves, including 18 Pydantic schema
rejections, six per Trial. Initial baseline Proposal phases attempted nine saves
with one schema rejection; baseline later corrections add two more saves. Errors
repeatedly used obsolete or invented field shapes: missing `kind`, scalar
measurement, wrong timing discriminators, group `label` instead of `assignment`,
`applicability.passage_refs` instead of `evidence`, and an extra reported wrapper.
The inspected published schema contains the required nested definitions and matches
the installed code. Actual host receipt of that schema is not observable, so a
publication defect is not established.

Holm's Domain retries included an enforced post-approval reading pass, malformed
option text, omitted active questions, and an unsupported definitive answer basis.
The existing repairs recovered. No finalization defect occurred. Updated Result
representation still has weaknesses: Al Qahtani omitted structured precision even
though its Evidence includes the CI, and GLUCOCOVID duplicated numeric content in
the statistic field. Researcher approval found the requested quantities and target
scope intact; these are representation losses, not different assessed outcomes.

## Decision

Retain the tested contract improvements without claiming an accuracy gain. File
and test [#304](https://github.com/AliSalman-et-al/rob2-kit/issues/304), a compact
validated `save_proposal` example in the existing Result reference. Astra Low
approved the issue before filing. The hypothesis is reduced field-shape invention;
it changes no scientific rule and must not introduce copied Trial facts.

Do not add deterministic interpretation checks, another critic model, or more
D4/D5 warnings on the strength of this run. The next accuracy experiment needs
expert-adjudicated Result-specific premises, repeated runs, and supplied-evidence
comparison across models, as scoped in #282. The research findings support testing
evidence delivery and use separately; they do not establish that another retrieval
system will repair reasoning that contradicts already-delivered guidance.
