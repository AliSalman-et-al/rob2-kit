# Bounded D5 source audit — 2 October 2026

This offline audit uses six original 1 October cases from `/home/ali/Documents/Code/rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01`. `retained-records.json` preserves approved targets, original accepted D5 submissions, cited passages, event coordinates, and canonical/log/source hashes. Lexical candidate pages are navigation aids, not proof of entailment. No reference labels were used to determine correctness. No new paid inference or full benchmark was run.

## Findings and limits

| Case | Source-level finding | Interpretation limit |
| --- | --- | --- |
| STOPDAPT-2 | The accepted 5.1 rationale treats failure to establish an early plan as evidence against early specification. Investigator access chronology is unresolved. | This is an unsupported rationale step, not proof that NI is the uniquely correct answer; supported trial circumstances could justify a probable judgment. |
| TESTING | Final SAP followed published unblinded interim results; the SAP committee was described as blinded. | Public availability supports a chronology concern. It does not itself establish result-driven selection. |
| Kang RECOVERY | The cited plan and selected reported analysis differ (Cox/log-rank versus Fine–Gray). | Non-correspondence can support 5.1 concern independently of uncertain dates; it does not prove a results-driven choice for 5.3. |
| Guitton | Planned and reported measurement windows differ; ITT and per-protocol results are both reported. | A window mismatch is distinct from evidence that a favorable result was selected. |
| CANVAS | Plan correspondence and blinded-period facts supported probable 5.1 Yes, with public interim access retained as counterevidence. | Missing a timestamp alone must not force NI. |
| Allsop | No located plan; available reports do not settle measurement or analysis selection. | NI is defensible. An unavailable plan does not establish a favorable choice or prespecification. |

The verified guidance gap was narrower than a wrong benchmark label: 5.2/5.3 evidence instructions asked only for protocols/SAPs. [Cochrane guidance, §8.3.2 and Box 11, printed pp. 61 and 63–65](https://www.cochrane.de/sites/cochrane.de/files/uploads/RoB_2.0_guidance_2019.pdf) also supports inference from report methods/results and companion publications. The revised guidance admits that evidence and keeps NI conditional on whether a reasonable judgment is possible. Section 8.3.1 additionally distinguishes confidential monitoring access, blinded analysis refinement, and public interim results. Unknown chronology does not become negative chronology.

The comparison card separates measurement selection (5.2) from analysis selection (5.3). Neutral paired facts preserve a positive control: no SAP, three eligible analyses, but an explicit author statement that only the favorable estimate was reported. No affirmative real-case selection finding was identified in this bounded sample; the control is synthetic and source-guided, not a benchmark gain.

## Counterpoint contract

A legitimate joint counterclaim can require several Evidence passages—for example, plan date plus investigator-access date. The public contract now takes distinct, nonempty `basis_indexes`; every index must select an Evidence basis. Scalar/negative/duplicate/out-of-range indexes and the old public singular spelling are rejected. There is one public spelling, with no compatibility alias. Existing durable/exported singular `basis_index` rows remain supported: a joint input expands to one row per citation with the exact same implication. The canonical representation preserves the citations and shared claim text, but does not introduce a separate group identifier.

`offline-an-original-call-control.json` records acceptance of the unchanged original rejected An arguments under the plural contract. It was captured before the subsequent monitoring-access wording clarification; the contract implementation is the same. The original paid run remains failed, and its High judgment remains scientifically unvalidated. This is an offline transport regression control, not an accuracy result.

## Verification and next hypothesis

Focused checks cover guidance/card distinctions, original failed-call parsing, joint support preservation, invalid index rejection, review/export round-trip through both bundle verifiers, contract/schema closure, and model-facing examples. Published historical pack descriptors are retained.

A later authorized model experiment should freeze identical supplied passages, target, model/settings, and tools, and vary only the reporting reason: unknown versus explicit favorable-only choice among the same eligible analyses. Compare old and revised guidance with those two states. That isolates recognition of report-derived selection without a SAP; an end-to-end benchmark would confound source retrieval, chronology, and transport. Do not provide expected answers to the model. Counterpoint acceptance is already isolated by the unchanged-call offline control and needs no paid rerun for that claim.

No accuracy improvement is claimed. Corpus alignment limitations, unresolved source chronology, and the unvalidated An scientific draft remain material limitations.

Validation: 61 distinct focused checks passed across the retained batches (55 initially, five additional contract/handoff checks, and one additional access/chronology check). The joint review/export test passed again after the final pack hash update. Changed Python files pass Ruff and ty; `git diff --check` passes. Broader Ruff/ty scans report 76 lint errors and 82 typing diagnostics in untouched benchmark scripts and archived audit code, so repository-wide cleanliness is not claimed. CI was not inspected or awaited in this pass.
