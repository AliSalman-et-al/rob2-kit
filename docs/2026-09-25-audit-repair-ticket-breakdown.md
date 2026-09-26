# Audit repair ticket breakdown

Approved and published on 2026-09-25 under [specification #442](https://github.com/AliSalman-et-al/rob2-kit/issues/442).
The 22 tickets are native subissues with 45 native blocking links. Each has the
`ready-for-agent` label and its own acceptance criteria. The first available
ticket is #443. This plan supersedes the programs under #413 and #427 without
changing either parent issue.

| Slice | Ticket | Blocked by | Delivery |
| --- | --- | --- | --- |
| 01 | [#443 Restore CI visibility](https://github.com/AliSalman-et-al/rob2-kit/issues/443) | None | Formatting and independent test gates report real outcomes. |
| 02 | [#444 Preserve counterevidence targets](https://github.com/AliSalman-et-al/rob2-kit/issues/444) | 01 | Counterpoints survive normalization and export with the same basis. |
| 03 | [#445 Complete D2 participant-flow round trips](https://github.com/AliSalman-et-al/rob2-kit/issues/445) | 01 | Accepted D2 rows reach independent verification. |
| 04 | [#446 Import ordered live observations](https://github.com/AliSalman-et-al/rob2-kit/issues/446) | 01 | Current receipts retain scope, repairs, handles, answers, and chronology. |
| 05 | [#447 Count every planned draw](https://github.com/AliSalman-et-al/rob2-kit/issues/447) | 01 | Reliability includes failures and missing draws. |
| 06 | [#448 Require cohort provenance](https://github.com/AliSalman-et-al/rob2-kit/issues/448) | 01 | Completed states require completed reviewer records. |
| 07 | [#449 Resume the intended host session](https://github.com/AliSalman-et-al/rob2-kit/issues/449) | 01 | Recovery resumes the recorded session or gives a diagnosis. |
| 08 | [#450 Record one replayable attempt](https://github.com/AliSalman-et-al/rob2-kit/issues/450) | 07 | Attempt identity binds inputs, resumptions, outcomes, and artifacts. |
| 09 | [#451 Reject the wrong Result](https://github.com/AliSalman-et-al/rob2-kit/issues/451) | 08 | Wrong-scope artifacts remain visible but unscored. |
| 10 | [#452 Report evidence and support truthfully](https://github.com/AliSalman-et-al/rob2-kit/issues/452) | 01 | Delivery, notes, host claims, and validation are distinct. |
| 11 | [#453 Surface Result-scope conflicts](https://github.com/AliSalman-et-al/rob2-kit/issues/453) | 01 | Material conflicts and unknown facets cannot silently become exact scope. |
| 12 | [#454 Carry working observations forward](https://github.com/AliSalman-et-al/rob2-kit/issues/454) | 10, 11 | Valid facts persist; dependent reasoning stales on actual changes. |
| 13 | [#455 Apply D2 reasoning to the endpoint](https://github.com/AliSalman-et-al/rob2-kit/issues/455) | 03, 11 | Deviations, exclusions, and flow answer their distinct D2 questions. |
| 14 | [#456 Keep D3 mechanisms distinct](https://github.com/AliSalman-et-al/rob2-kit/issues/456) | 03, 10, 11 | Availability, censoring, follow-up, and uncertainty remain separate. |
| 15 | [#457 Tie D4 measurement to the endpoint](https://github.com/AliSalman-et-al/rob2-kit/issues/457) | 11 | D4 identifies the selected endpoint's ascertainment mechanism. |
| 16 | [#458 Bind D5 plans to the Result](https://github.com/AliSalman-et-al/rob2-kit/issues/458) | 11 | Plan chronology and alternatives apply to the selected Result. |
| 17 | [#459 Navigate long documents](https://github.com/AliSalman-et-al/rob2-kit/issues/459) | 01 | Relevant sections and embedded versions remain reachable. |
| 18 | [#460 Keep edge-case sources searchable](https://github.com/AliSalman-et-al/rob2-kit/issues/460) | 01 | Large scopes and degraded projections remain usable and safe. |
| 19 | [#461 Optimize measured retrieval costs](https://github.com/AliSalman-et-al/rob2-kit/issues/461) | 17, 18 | Profiles justify any speedup without weakening integrity. |
| 20 | [#462 Review decisive claims](https://github.com/AliSalman-et-al/rob2-kit/issues/462) | 12–17 | Existing review checks the source-to-answer link before closure. |
| 21 | [#463 Run controlled development comparisons](https://github.com/AliSalman-et-al/rob2-kit/issues/463) | 02–06, 09 | Frozen comparisons distinguish evidence access and reasoning effects. |
| 22 | [#464 Qualify the integrated successor](https://github.com/AliSalman-et-al/rob2-kit/issues/464) | 12–21 | Held-out runs support a bounded promote-or-hold decision. |

## Replaced child tickets

The following issues were closed as superseded, with a comment linking to the
new ticket or tickets. Closure does not claim their work is implemented:

| Old | Replacement | Old | Replacement |
| --- | --- | --- | --- |
| #414 | #459 | #428 | #449 |
| #417 | #454 | #429 | #450 |
| #418 | #454 | #430 | #451 |
| #419 | #452 | #431 | #452, #454 |
| #420 | #456 | #432 | #454 |
| #421 | #457 | #433 | #445, #455, #456 |
| #422 | #453, #454 | #434 | #455 |
| #425 | #458 | #435 | #456 |
| #436 | #457 | #437 | #458 |
| #438 | #454 | #439 | #459, #460 |
| #440 | #462 | #441 | #464 |

#415 and #416 retain separate search-deduplication and counterfactual behavior.
#423 and #424 retain independent-adjudication work that this program excludes.
They remain open. The original parent issues #413 and #427 remain open and
unchanged under the ticket workflow's parent-issue rule.
