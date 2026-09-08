# SUSTER reassessment after Proposal simplification

The simpler Proposal contract eliminated schema rejections in these three clinical
runs, but did not establish a D1–D5 accuracy improvement. All three assessments
finalized and passed both verifiers. Scientific rationales remain inconsistent,
including changes to both higher and lower risk without the necessary premises.

## Conditions

This repeats the same three development cases and abstract-defined prompts from
the [first paired reassessment](2026-09-08-paired-suster-reassessment.md).
The simplified revision is `9e25a94a4a11504ac08af0d42e19b53cbc38c79e`.
It implements #304–#306: a validated Proposal example, bounded full-Source reading
without caller-supplied boundaries, and applicability routing from design without
a redundant status field. Official Domain algorithms are unchanged.

Each condition used a clean workspace, Codex CLI 0.153.4, requested Luna Medium,
Python 3.13.13, and the same 72 non-kit dependency versions. Supplied input hashes,
prompts, captured Source bytes, and extracted-text hashes match across all three
conditions. Registry retrieval times differ. The logs do not independently confirm
the realized model and reasoning effort.

The parent reviewed each exact Proposal against its selected Source passages,
approved it through the researcher CLI, and resumed the same session with
`Continue.` No Result correction or Domain-answer coaching was needed in this
condition. The baseline included the previously documented Result corrections.

Local artifacts are in sibling directory
`rob2-kit-testing/suster/20260908-cycle02-simplified/`: frozen manifest, source
copies, installed wheel, dependencies, JSONL logs, researcher approval records,
finalized bundles, `analysis.json`, `review-observations.json`, and
`three-condition-summary.json`. The summary includes raw-log hashes and source
comparability checks. Each new bundle passed the installed kit verifier and
standalone verifier; their outputs are retained beside the logs.

## Domain outcomes

Cells list D1 through D5. `L` means Low, `SC` Some concerns, and `H` High.

| Result | Baseline `f2304` | Updated `b045803` | Simplified `9e25a94` |
|---|---|---|---|
| Holm: 28-day mortality, OR 0.49 [0.08, 2.79] | SC, H, H, L, SC | SC, H, SC, L, SC | SC, L, L, L, SC |
| Al Qahtani: ventilation, RR 0.67 [0.22, 2.0] | SC, L, L, L, SC | SC, L, L, L, L | SC, SC, L, L, SC |
| GLUCOCOVID: primary composite, 14/35 versus 14/29 | SC, L, L, H, L | SC, L, L, L, L | SC, H, L, H, L |

These are one stochastic draw per condition on inspected development trials, with
several changes bundled together. The available prior references do not provide an
unambiguous Result-specific gold join for all three new prompts. Label movement
does not establish correctness, causality, or generalization.

## Scientific premise audit

**D1 remains unchanged in label.** GLUCOCOVID still treats the concealed
medical-record-number formula as establishing a random mechanism and interprets
age imbalance plus prognostic importance as a randomization problem. The recorded
rationale does not establish the random component or explain why chance is an
insufficient explanation for imbalance in this small trial.

**D2 moves in both directions.** Holm now accepts the analysis as probably
appropriate because participants remained in assigned groups after two immediate
exclusions. This avoids the earlier automatic rejection of modified ITT, but still
does not establish whether excluded mortality outcomes were unavailable or were
available and omitted. Neither rationale resolves that distinction.

GLUCOCOVID changes from Low to High because five participants received fewer than
three doses after rapid deterioration and one control participant received rescue
corticosteroids. The rationale calls these trial-context departures without showing
that trial participation caused a protocol-inconsistent change. It also treats
their connection to early ICU/NIV events as evidence they could affect the outcome,
without resolving temporal direction. The delivered 2.3 card explicitly requires
trial-context causation and rejects nonadherence alone as a shortcut. Al Qahtani
instead uses NI about trial-context deviations and changes to Some concerns. These
different applications do not demonstrate a stable improvement.

**Holm D3 changes to Low without an adequate nearly-all argument.** The model now
records the correct arithmetic, 31/33 participants or about 94%, and stops at 3.1.
Its rationale does not relate the two missing outcomes to the five observed deaths
or assess whether plausible missing outcomes could materially change the estimate.
Arithmetic completeness is not sufficient for this rare binary endpoint. The
read-only D3 preview was again unused; counts were submitted with the answer.

**D4 still confuses distinct questions.** Al Qahtani remains Low because the model
treats whether ventilation was required as an objective threshold, then uses
unlikely influence to answer the possibility question. It does not adequately
examine the unblinded clinical decision to initiate ventilation.

GLUCOCOVID returns to High through a probably-yes answer to differential
ascertainment, based on open-label treatment and possible influence on ICU/NIV
decisions. The same rationale acknowledges that no direct differential assessment
process was reported. The cited age/resource mechanism does not
by itself establish different measurement methods between randomized groups. This
differs from the previous run's unsupported reassurance, but the changed label is
not proof of sound reasoning. The existing reference and question cards already
separate method differences, awareness, possible influence, and likely influence.

**D5 chronology remains inconsistently applied.** Al Qahtani now uses NI because
the available protocol and methods do not establish plan finalization before
unblinded outcomes, returning to Some concerns. GLUCOCOVID still accepts an
a-priori interim analysis statement and ITT label as probable pre-specification,
while acknowledging the missing timing basis. Holm retains the explicit change
from registered three-month mortality to the reported 28-day window. A separate
dated SAP is not always required, but a probable answer needs affirmative evidence
or a supported indirect chronology argument.

These are observed failures to apply available facts and guidance. This experiment
does not distinguish model capability from attention, context composition, or
stochastic variation. It establishes no new missing-retrieval defect that a search
feature would resolve, and no reliable deterministic replacement judgment.

## Workflow measurements

| Measure, three clinical runs | Baseline | Updated | Simplified |
|---|---:|---:|---:|
| Proposal saves, including baseline corrections | 11 | 25 | 11 |
| Proposal schema rejections | 1 | 18 | 0 |
| Search calls | 105 | 9 | 12 |
| Zero-hit searches | 46 | 4 | 3 |
| Failed tool calls | 2 | 21 | 5 |
| Structured repairs | 8 | 9 | 18 |
| Domain-context response bytes | 728,859 | 1,021,879 | 1,158,789 |
| Input tokens | 11,943,311 | 13,354,496 | 13,038,278 |
| Cached input tokens | 11,258,368 | 12,846,336 | 12,458,240 |
| Uncached input tokens | 684,943 | 508,160 | 580,038 |
| Output tokens | 36,174 | 41,697 | 37,064 |

Completed MCP events and CLI turn-usage records supply these counts. Failed calls
and structured repairs are separate categories. Context bytes measure compact
decoded responses, not tokens. Total input fell slightly relative to the first
update, while uncached input and context bytes increased. These observations do
not establish a general cost reduction or quantify subscription charges.

All three first Proposal saves passed the request schema. Eight Proposal repairs
remained, largely for paraphrased endpoint definitions, exact quantitative wording,
and combining fields that lacked a complete supporting Result tuple. The remaining
repairs included unfinished post-approval reading, active-question matching, and
the required multiple-concerns decision. Five failed calls involved reading or
search arguments and identifiers. None prevented completion.

Result representation still loses structure. Holm and Al Qahtani dropped optional
arm values after support repairs. GLUCOCOVID retained the requested arm values but
duplicated them in the statistic field and embedded precision in its estimate.
The target outcomes and comparisons remained intact. Source-support validation
can reject an unsupported literal tuple; it does not validate scientific inference.

## Fresh synthetic Proposal check

The unchanged one-page CEDAR fixture concerns standing balance at six weeks,
adjusted mean difference 5.8 seconds [2.4, 9.2], with 84 randomized participants.
It uses different subject matter from both the documented example and SUSTER.
Both runs stopped at unapproved Proposal Review, with correct Trial facts and live
Evidence handles. Neither first save passed the schema.

| Measure | Before `4deb159` | After `9e25a94` |
|---|---:|---:|
| Proposal saves | 4 | 3 |
| Schema rejections | 2 | 1 |
| Structured repairs | 1 | 1 |
| Input tokens | 1,010,430 | 320,929 |
| Cached input tokens | 940,032 | 285,696 |
| Output tokens | 4,673 | 1,973 |

The remaining schema rejection omitted the required description of quantified
timing. The later repair rejected a paraphrased endpoint definition, which the
model removed. The example did not contaminate the final Trial facts, but this
single paired result does not establish reliable first-call acceptance. Example,
scope, and applicability changes were evaluated together. Artifacts and the paired
summary are in `20260908-cycle02-synthetic-before/` and
`20260908-cycle02-synthetic-after/` beside the clinical cycle.

## Decision

Keep the simpler contract and validated example. The change removes unnecessary
caller choices and preserves the Evidence, reading, approval, and verification
boundaries. Fresh review also found and corrected a v0.6 verifier regression; a
self-contained rehashed tamper test now protects the historical contract.

Conclude this implementation cycle without adding more scientific warnings or
model-specific rules. The evidence supports a Proposal ergonomics improvement on
these cases, not an accuracy claim. The next useful accuracy experiment remains
#282: Result-specific expert adjudication, repeated draws, and supplied-evidence
comparisons across models to separate discovery from interpretation. The
[research review](2026-09-08-agent-evidence-research.md) supports that separation.
