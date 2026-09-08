# Cycle 03 SUSTER reassessment

Date: 2026-09-08

This cycle tested the next three trials in the frozen SUSTER ranking after the
three trials used in cycles 01 and 02. It used only the frozen SUSTER source
pool, one Result named from each report's abstract, and `gpt-5.6-luna` at medium
reasoning. The kit was built from commit
`1b3b79000ac529f7393d129b4c659067b214f113` in a clean isolated runtime.

The available reference labels are joined at DOI level because the source
release does not expose the QIG suffix-to-Result mapping. They bound the trial
selection but are not gold labels for the new abstract-defined Results. The
vectors below are therefore auditable outputs, not accuracy scores.

## Frozen selection and procedure

The selection continued the preregistered optimistic-bound ranking:

| Trial and Result | Prior trial-level bound | Abstract target |
| --- | ---: | --- |
| Blalock 2013, depression through 6 months postpartum | 0.40–0.40 | Increasing childhood trauma was associated with greater benefit from CBASP while the health-and-wellness control did not show the same pattern; the abstract reported no numeric effect estimate. |
| McClanahan 2019, contact dermatitis | 0.33–0.47 | 9.3% with the study emollient versus 4.3% with control. |
| Grote 2014, PTSD severity through 18 months | 0.20–0.50 | Wald chi-square 4.61, df 1, p=.04; MOMCare n=83 and MSS-Plus n=85. |

For each trial, the model prepared a Proposal, stopped at the proposal-review
gate, and received an uncorrected researcher approval after manual inspection.
The same model session then resumed with only `Continue.` All three finalized
bundles passed both the product verifier and the independent
`scripts/verify_bundle.py` consumer.

## Observed Domain records

| Trial | D1 | D2 | D3 | D4 | D5 |
| --- | --- | --- | --- | --- | --- |
| Blalock 2013 | Some concerns | High | High | Some concerns | High |
| McClanahan 2019 | Low | High | High | Low | Some concerns |
| Grote 2014 | Some concerns | Low | Some concerns | Low | Some concerns |

Blalock's D1 record appropriately preserved uncertainty about sequence
generation and concealment. Its D2 record treated the exclusion of 18 of 266
randomized participants without CTQ data as an assignment-effect analysis
defect that could affect the treatment-by-trauma estimate. Its D3 record found
no Result-specific availability counts or missingness evidence. Its D4 record
correctly treated the participant as assessor of the self-reported CES-D and
separated possible from likely influence. Its D5 record tied the concern to the
secondary, exploratory interaction analysis and reported model iteration.
Material impact from the 18 CTQ exclusions remains a scientific judgment rather
than a server-verified fact.

McClanahan exposed two premise errors. D2 treated differential adherence as
proof of a protocol-inconsistent deviation caused by the trial context. The
official card says ordinary nonadherence alone supports a negative answer to
2.3 unless evidence connects it to the trial context. D3 relied on 28% loss for
the trial's primary endpoint to characterize availability for contact
dermatitis. That is not Result-specific availability, even though the adverse
event denominators and missing cases may still warrant a materiality judgment.
The model had the relevant cards and report text, so these are model reasoning
failures rather than missing kit guidance.

Grote's D1, D2, D3, and D5 records were internally coherent. D4 answered that
the assessor was blinded because a blinded interviewer collected outcomes by
phone. The approved PCL-C outcome is participant reported: under RoB 2 the
participant determines the outcome and remains its assessor, while the
interviewer records it. The question card and measurement reference already
state this distinction. This is another model evidence-use failure, not a
missing workflow rule.

## Workflow observations

| Trial | Proposal repair responses | Domain/final repair responses | Search calls | Zero-hit searches | Input / cached / output tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Blalock 2013 | 1 | 1 | 3 | 1 | 4,829,326 / 4,664,832 / 11,204 |
| McClanahan 2019 | 2 | 3 | 5 | 2 | 4,500,812 / 4,346,624 / 12,642 |
| Grote 2014 | 2 | 5 | 4 | 4 | 5,275,869 / 5,094,400 / 14,733 |

The updated #308 fallback did not eliminate dependent-question repairs. Trace
inspection showed a narrower mechanism than failure to answer every question:

- Blalock supplied the complete D3 draft but mistyped one option ID.
- McClanahan initially supplied a dependent answer, then dropped it while
  repairing another option.
- Grote initially supplied later D3 answers, then discarded them while adding
  the newly active D3.2 answer, which caused two more repair rounds.

The agent instructions now tell the model to apply every reported repair while
retaining other drafted answers, add missing questions to the existing set, and
resolve activation again before resubmitting. The optional all-question
fallback remains. Making every inactive branch mandatory would require evidence
work for scientifically irrelevant counterfactual questions and would not fix
invalid option IDs.

The first real import of these six proposal/assessment captures also found a
bug in the new #295 observation importer. Resumed Codex invocations can reuse
local IDs such as `item_2` inside the same persisted session. Keying operations
by `(session_id, local_call_id)` therefore conflated different calls. The
correct identity is `(transcript_id, local_call_id)`; `session_id` is grouping
metadata. Start/completion records still reconcile within one transcript, and
conflicting duplicates within that transcript remain errors.

The preliminary cycle 03 run used different, older Result prompts. Its repair
counts and vectors are diagnostic only and cannot be used as a paired causal
comparison with this run.

## Primary research and decision

[Pi-Serini](https://arxiv.org/html/2605.10848v1) separates surfaced,
previewed, opened, and cited evidence and reports a large gap between available
and actually used material. [BEIR](https://arxiv.org/abs/2104.08663) shows that
BM25 remains a strong heterogeneous baseline and that dense retrieval does not
generalize uniformly. These findings support measuring the retrieval funnel,
but this three-case audit did not identify a new missing-retrieval mechanism.

[Chain-of-Verification](https://arxiv.org/abs/2309.11495) and
[SelfCheck](https://proceedings.iclr.cc/paper_files/paper/2024/file/fa1edbc195336e29893cdae0939e495f-Paper-Conference.pdf)
support independently reconstructing and comparing premises rather than asking
the original reasoning to approve itself. The
[Cochrane Handbook](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08)
provides the governing result-specific, causal, materiality, assessor, and
chronology distinctions. A premise-ledger plus independent-verification
experiment remains appropriate under #282, but these sources do not justify a
new mandatory runtime critic without held-out, repeated-draw evidence.

The official [MCP tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
and [Anthropic's tool-writing guidance](https://www.anthropic.com/engineering/writing-tools-for-agents)
support compact typed responses, stable identities, and realistic trace-based
evaluation. This cycle therefore implements the observation identity fix and
the bounded repair-preservation wording. It does not add a new retrieval layer,
scientific judge, voting pass, or duplicate warning for rules already stated in
the cards.

