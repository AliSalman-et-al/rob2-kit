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
