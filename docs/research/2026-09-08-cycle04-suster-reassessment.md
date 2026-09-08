# Cycle 04 SUSTER reassessment

Date: 2026-09-08

This cycle randomly selected three previously unused trials from positions 7
through 15 of the frozen SUSTER ranking. It used only the frozen SUSTER source
pool, one Result named from each report's abstract, and `gpt-5.6-luna` at medium
reasoning. The kit was built from merged commit
`9b676fc4317ebcd5bed1de9a4a06a21c13941022` in a clean isolated runtime.

The available reference labels are joined at DOI level because the source
release does not expose the QIG suffix-to-Result mapping. They informed trial
selection but are not gold labels for these abstract-defined Results. The
vectors below are auditable outputs, not accuracy scores.

## Frozen selection and procedure

| Trial and Result | Prior trial-level bound | Abstract target |
| --- | ---: | --- |
| Sekhavati 2020, mortality during hospitalization | 0.70-0.70 | No significant difference in mortality was reported; the full report gave 0/56 versus 1/55 deaths. |
| Huhn 2020, relapse of positive symptoms over 26 weeks | 0.67-0.67 | Relapse rates were not significantly different; 20 participants were randomized. |
| Kalil 2021, 28-day mortality | 0.53-0.73 | 5.1% with baricitinib plus remdesivir versus 7.8% with control; hazard ratio 0.65 (95% CI 0.39 to 1.09). |

For each trial, the model prepared a Proposal, stopped at the proposal-review
gate, and received an uncorrected researcher approval after manual inspection.
The same model session then resumed with only `Continue.` All three finalized
bundles passed both the product verifier and the independent
`scripts/verify_bundle.py` consumer. The deterministic observation importer
parsed the six proposal and assessment transcripts as three complete assessed
attempts with 239 records, 196 MCP records, 98 unique calls, and no source
searches.

## Observed Domain records

| Trial | D1 | D2 | D3 | D4 | D5 |
| --- | --- | --- | --- | --- | --- |
| Sekhavati 2020 | Some concerns | Low | Low | Low | Some concerns |
| Huhn 2020 | Low | Low | Low | Low | Low |
| Kalil 2021 | Some concerns | Low | Low | Low | Low |

Sekhavati's records were coherent with the inspected report. All reported
arrhythmia-risk scores were below six, so the table did not establish an actual
post-randomization exclusion. Huhn's low-risk records were also consistent with
the available report and approved relapse Result.

Kalil exposed a result-specific D3 premise error. The D3.1 answer treated the
flow diagram's composite count of participants who completed follow-up,
recovered, or died as nearly complete mortality ascertainment. Recovery does
not establish known vital status at a later mortality time point. Supplement
Table S5 reports mortality status unknown at day 29 +/-3 days for 67/515 and
75/518 participants. Its footnote says 49 and 52 of those participants had
recovered and that one recovered participant in each arm later died. The
recovered subgroup is relevant reassurance, but the unknown status and nearby
time window must remain explicit. The model did not inspect this supplement.
The final D3 judgment may still admit more than one defensible answer; the
unsupported availability premise is the error.

Kalil's D5 record was supportable because the captured original statistical
analysis plan predated the end of enrollment and specified mortality. The model
did not open that plan, so this was a fragile correct premise rather than a
complete evidence path.

## Workflow and context observations

| Trial | Proposal repairs | Domain/final repairs | Input / cached / output tokens |
| --- | ---: | ---: | ---: |
| Sekhavati 2020 | 1 | 4 | 3,158,068 / 3,013,888 / 9,422 |
| Huhn 2020 | 3 | 2 | 3,493,382 / 3,313,408 / 9,722 |
| Kalil 2021 | 1 | 2 | 6,210,177 / 5,959,680 / 8,790 |

The assessment runs produced five post-approval reading-gate repairs: two for
Sekhavati, two for Huhn, and one for Kalil. The gate preserved the required
second pass, but the Domain context placed its recovery instruction after the
questions and bulk Evidence. Two additional repairs supplied missing active D4
answers. Those retries retained the already drafted answers, which supports the
repair-preservation change from cycle 03.

Status responses also repeated selected narrative quotations during Proposal
reading. Huhn's three status objects totaled 108,104 serialized JSON bytes and
Kalil's seven totaled 190,440 bytes. These are response bytes, not provider
token counts. Replaying those same status objects through the bounded Evidence
projection reduces them to 52,240 and 89,801 bytes, respectively, while each
omitted quotation retains an exact recovery window. Sekhavati's short status
objects remain unchanged at 3,414 bytes. The existing equal-share `read_pages`
transport could leave capacity unused when a short window shared a response
with a long one.

An offline replay merged each phase's delivered source-line intervals, then fed
the same coverage through request-order packing and its exact continuations.
It reduced the 23 observed read calls to 14: Huhn from 4/3 to 2/2 calls,
Kalil from 5/5 to 3/3, and Sekhavati from 3/3 to 2/2 for Proposal/Assessment.
The replay preserved every delivered source line and removed Huhn's overlapping
line delivery. It measures transport behavior only; it does not predict how a
model will group future windows.

The two mandatory reads repeated 140,262 unique source-line bytes across
phases. That replay remains intentional. Kalil and Sekhavati returned identical
main-source blocks across the two passes; Huhn used different splits around the
same source prefix. Aggregate cached-input fractions were 95.97%, 95.43%, and
94.85% for Kalil, Sekhavati, and Huhn. These provider observations do not prove
that the repeated source text itself was served from cache. A cache receipt or
hash also cannot restore text to a fresh host context.

One pre-Proposal pass would be cheaper but cannot guarantee that its text is
available after researcher review, context compaction, or a changed Result. A
first-pass Methods/Results map would help navigation but is brittle as an
exclusion rule: Sekhavati's discussion resolved a concern raised by the Methods,
while Kalil's decisive mortality-availability counts were in a supplement.
Shared pages, table footnotes, and nonstandard headings add further boundary
risk. The server can validate coordinates, but it cannot validate that a
model-authored map is scientifically complete. The two bounded passes therefore
remain the simpler reliable workflow. Provider caching of supplied prefixes
does not make omitted sections available to the model.

Issues [#310](https://github.com/AliSalman-et-al/rob2-kit/issues/310),
[#311](https://github.com/AliSalman-et-al/rob2-kit/issues/311), and
[#312](https://github.com/AliSalman-et-al/rob2-kit/issues/312) capture the
bounded changes justified by this cycle: distinguish recovery from later vital
status in D3, keep mandatory reading continuation prominent while bounding
status Evidence text, and pack requested read windows against the remaining
transport budget. Both text-only passes, their source order, and the 65,536
UTF-8 source-byte cap per main report remain unchanged.

## Research implications

[ToolSandbox](https://aclanthology.org/2025.findings-naacl.65/) evaluates
intermediate state milestones and forbidden events in addition to final task
success. Its mutable utility tasks are not scientific assessments, but its
evaluation shape fits activation and repair-retention checks.
[tau-bench](https://arxiv.org/html/2406.12045) shows why repeated independent
trials reveal reliability that a single successful run hides. Its executable
end states cannot score scientifically valid alternative RoB 2 rationales, so
repeated evaluation should reserve deterministic checks for activation,
Evidence identity, and checkpoint lineage.

[LongMemEval](https://arxiv.org/html/2410.10813) separates retrieval, reading,
state updates, and abstention, and warns that over-compression loses detail.
[ALCE](https://aclanthology.org/2023.emnlp-main.398/) separates citation
presence from citation support. Together they support an offline premise and
repair audit: score whether Evidence supports each result-specific proposition,
whether repairs retain already valid answers, and whether the model abstains on
unavailable premises. They do not justify removing the second reading pass,
adding a memory layer, or introducing an automatic scientific judge.

The next evaluation work remains under
[#282](https://github.com/AliSalman-et-al/rob2-kit/issues/282): repeated fixed
conditions with premise-level annotations and multiple acceptable Evidence
sets. This cycle implements only the transport, sequencing, and mortality
guidance defects directly observed here.

## Candidate validation after the changes

Commit `4782085346395b800d6bb84d4b5b300b834001d0` was then evaluated in a
new isolated runtime. A recorded random draw from the remaining poorly
performing SUSTER candidates selected Ader 2022, Chalmers 2020, and Spencer
2020. The abstract-defined Results were day-15 WHO ordinal clinical status,
eczema at age two years, and posttest English proximal receptive vocabulary.
Each Proposal was manually checked before approval. Spencer required a
researcher correction because the first Proposal mislabeled an adjusted mean
difference as Hedges' g. After correction, the kit correctly classified the
cluster-randomized design as unsupported and stopped with `needs_input` rather
than forcing an individual-randomized assessment. A recorded replacement draw
selected Edalatifard 2020 mortality so that the validation still contained
three completed five-Domain assessments.

| Trial | D1 | D2 | D3 | D4 | D5 |
| --- | --- | --- | --- | --- | --- |
| Ader 2022 | Low | Low | Low | High | Low |
| Chalmers 2020 | Low | Some concerns | Some concerns | Low | Low |
| Edalatifard 2020 | Some concerns | High | High | Low | High |

Ader's high D4 judgment is defensible for an open-label ordinal clinical-status
outcome whose components include care decisions. Chalmers' records identify
incomplete adherence and control contamination without treating them as proof
of a substantial outcome effect; the D3 record also keeps roughly 13% missing
outcome data distinct from reassuring sensitivity analyses. Both assessments
are coherent with the inspected reports.

Edalatifard correctly kept the randomized population of 34 participants per
arm separate from the reported subset of 34 versus 28. Six standard-care
participants received corticosteroids and were excluded from the displayed
mortality analysis. The high D2 and D3 judgments therefore have direct
result-specific support, and the low D4 judgment is appropriate for death. Its
D5 judgment is overconfident. The record answered that analysis selection was
probably result-driven because ITT, per-protocol, imputed, and survival
analyses were available, while also stating that no pre-unblinding plan had
been established. The existence of alternatives alone does not show
result-based selection; `no_information` and a lower D5 judgment are better
supported. The Domain 5 reference already states this rule, so this is a model
reasoning error rather than evidence for more server machinery.

| Trial | Proposal repairs | Domain/final repairs | Input / cached / output tokens |
| --- | ---: | ---: | ---: |
| Ader 2022 | 2 | 1 | 4,415,815 / 4,229,632 / 9,440 |
| Chalmers 2020 | 3 | 9 | 5,297,020 / 5,076,736 / 14,191 |
| Edalatifard 2020 | 1 | 6 | 4,006,227 / 3,860,224 / 12,433 |

Neither Ader nor Chalmers hit the post-approval reading gate, compared with all
three cycle-04 runs. Edalatifard hit it once after attempting D1 before
finishing the second pass, then recovered through the prominent typed windows.
This supports the sequencing change while showing that the server guard is
still necessary. The remaining Domain retries came mostly from submitting only
the currently visible branch question, plus three mistyped opaque option IDs
and one required overall-judgment decision. Valid answers were retained across
the activation retries. Chalmers accounted for eight activation retries. The
optional all-question fallback already supplied the needed cards, but the model
repeatedly chose incremental saves. The final instructions therefore make one
answer for every returned Domain question the default and tell the caller to
copy each opaque option identity character for character. The server continues
to commit only the active path; no new state layer or relaxed validation was
added.

Five failed tool calls were schema-shape errors rather than typed repairs. Ader
first nested `target` inside `reported`, then omitted the required description
from quantified timing. Chalmers also omitted that description and separately
requested 12 pages through an input limited to 10. Edalatifard supplied
`expected_revision` to the zero-argument approval tool. The final guidance adds
a quantified timing example that preserves the time origin, an executable
windowed-reading example and page-list limit, and the literal empty approval
arguments. The timing description remains required because a value and unit do
not distinguish, for example, time since randomization from time since symptom
onset.

All three assessed bundles and Spencer's `needs_input` bundle passed the
product and standalone verifiers. The deterministic observation importer
reconciled the ten proposal, correction, and assessment transcripts as four
complete attempts: 341 records, 274 MCP records, 137 unique calls, and no
source searches. Repeated import produced byte-identical output. These are
selected development cases with one stochastic run each. The DOI-level label
sets remain unsuitable as Result-specific accuracy scores.

## Targeted repair confirmation

The final model-facing guidance was evaluated from commit
`b34745310b4dab2ddd77c05dfa654e31c3e40dbd` in another isolated Chalmers
runtime. The Proposal matched the same eczema Result and was approved without
researcher correction. The model then submitted every Domain answer needed by
the active path on its first attempt. All five Domain judgments were accepted
without a repair or failed assessment call, compared with eight activation
repairs in the preceding Chalmers assessment. The finalized vector was Low,
Low, Low, Low, Low. The change from Some concerns to Low in D2 and D3 is
scientifically defensible: deviations were consistent with a pragmatic trial
and the balanced missingness analyses included reassuring GP-record and
multiple-imputation sensitivity analyses. It also illustrates why one run is
not a Result-specific accuracy estimate.

One Proposal call still mistyped a character in a 71-character source identity,
and the server rejected it before reading. The model recovered by copying the
identity correctly. Relaxing source-identity validation or adding an ambiguous
shortcut would weaken provenance for a single observed transcription error, so
the implementation keeps exact validation. The Proposal required one ordinary
typed repair to add an exact-relation rationale and remove an unsupported
endpoint definition. The final bundle passed both the product and standalone
verifiers. The confirmation used 3,516,091 input tokens, of which 3,267,328
were reported as cached, and 10,838 output tokens.
