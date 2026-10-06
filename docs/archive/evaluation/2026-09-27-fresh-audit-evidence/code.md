# Read-only code and trace audit — 2026-09-27

## Scope and conclusion

Read `AGENTS.md`, `CONTEXT.md`, ADRs 0031–0036, the current and prior 2026-09-27 evaluation audits, the portable assessment skill, the public MCP boundary, core Evidence/Domain/checkpoint paths, the scientific pack and evaluator, and the relevant open issues. This is a targeted architecture and trace audit, not line-by-line review of every module or scientific adjudication of every case. No production files changed. No tests or paid model runs were performed; no new code defect was alleged that warranted a test run.

The architecture has strong authority, identity, provenance, and deterministic-logic safeguards. I found no confirmed retrieval, storage, MCP lifecycle, or deterministic decision-table defect in the reviewed paths. The principal remaining risk is whether hosts apply already rich scientific guidance correctly to the approved Result. Existing issues #475–476 own the source-grounded adjudication and residual reasoning repair; the traces do not justify another general reasoning framework or domain rule.

## Current campaign evidence

The current-HEAD campaign is `eval/runs/2026-09-27/rob2-trial-benchmark-fresh-4e03e798`, distinct from the earlier audited `latest-8ae8016` campaign. Its `accuracy-report.md` reports 83/130 exact Domain-label matches (63.8%), 96/130 binary matches, and 2/26 exact overall labels. The provisional catalog contains 104 Low Domain labels and no High labels, so an all-Low response gets 104/130. These are agreement scores, not adjudicated scientific accuracy. The report says 26 scopes are exact, while per-case scope adjudications include `equivalent` decisions; use #480’s corrected scope reporting before interpreting an exact-scope denominator. Do not compare these figures causally with the older run’s 78/130.

I independently parsed the original fresh-run JSONL files (before replacement-attempt selection): 56 segments and 2,464 MCP call records (2,378 completed, 86 failed). Separate PEACE-1 retry logs contain six additional segments and 120 records. Original-tree call counts include 602 `get_domain_context` calls, 436 with a cursor; 406 `read_pages`; 170 single searches; 165 batches; 217 text Evidence selections; 131 renders; and 22 visual selections. Serialized MCP result data totals about 59.3 MB, including image payloads and structured/text forms. It is transport volume, not measured prompt tokens or retained model context. Of 170 single searches, 54 returned zero matches; batch searches are excluded, and a lexical zero is not evidence of scientific absence.

### Failed-call and repair taxonomy

The 86 failed MCP calls are tool-input validation failures, not observed server crashes or state corruption:

| Tool | Count | Most frequent cause |
| --- | ---: | --- |
| `validate_proposal` | 40 | Seven empty relation rationales, seven missing applicability Evidence, and incomplete/malformed typed Result cards or arrays. |
| `save_domain_judgment` | 37 | Seven obsolete `kind: evidence` basis tags, seven scalar counterevidence values, four missing basis tags, three SHA-256 identities supplied instead of `eh_…` handles, and three Evidence lists where a single string is required. The remainder are other missing or wrongly shaped fields. |
| `prepare_batch` | 6 | Five requests included Result facets in the outcome-only field; one omitted the revision. |
| `read_pages` | 2 | One request exceeded the ten-page bound; one supplied unsupported `max_response_bytes`. |
| `get_domain_context` | 1 | An extra `missing_data.population_role` field. |

There were also 61 structured application repair receipts: 41 Proposal and 20 Domain. They are distinct from transport validation failures and generally enforce source/scope requirements, answer bases, active-question completeness, or post-approval reading. The skill already distinguishes missing structured receipts from typed repairs and tells hosts to correct the named shape.

I compared each of the 20 Domain repair receipts with the next accepted save. All had a successful follow-up. Nine accepted drafts changed at least one answer value: eight changed certainty while preserving answer direction (`no`→`probably_no` or `yes`→`probably_yes`) after `answer_requires_direct_basis`; those eight had no additional search/read between repair and save. One D5 answer changed `probably_no`→`probably_yes` after the trace shows new protocol-page renders and four visual-Evidence selections. Three repairs added missing active questions, and post-approval reading repairs were followed by successful saves. This is an observed repair-associated calibration pattern, not a demonstrated scientific error: same-polarity probable answers may be correct for an inference, and the one direction change followed new Evidence. Adjudicate these cases before changing repair language or answer rules.

The fresh finalized bundles contain only two repeated Domain histories. ARCHES adverse-events D4 moved Some concerns→Low with a `new_evidence` revision citing protocol Evidence for a shared 30-day follow-up. STAMPEDE adverse-events D2 impact moved Probably no→No with `new_evidence` citing the ITT toxicity analysis. Both are explicit Evidence-linked corrections, not automatic repair edits. Rejected submissions do not commit answer changes (`application/domains.py:2323`, `interfaces/mcp/server.py:3114`); the deterministic evaluator remains server-owned (`logic/evaluator.py:102`).

## Actionable vertical slices, in priority order

1. **Accuracy and warrant validity — keep work inside #475–476.** Independently classify exact Result, decisive question, source passage, host inference, counterevidence, and response mapping before editing guidance. Use the already identified contrasts: analyzed/event/censor counts versus actual outcome availability; ordinary non-initiation versus trial-context deviation; exposure duration versus outcome-specific ascertainment opportunity; and plan existence/applicability/chronology versus results-driven selection. Preserve defensible concern and uncertainty, including PEACE-1’s extra laboratory surveillance and the TITAN D3 no-information path. Measure unsupported reassurance as well as unsupported concern. The pack already states these distinctions (`packs/scientific.py:376`, `:454`, `:514`, `:610`); the live question is whether a host uses them. Do not tune toward catalog labels alone.

2. **Checkpoint continuity — #473.** The current-run traces contain zero `save_working_checkpoint` calls despite extensive context recovery. The skill describes restart recovery and saves before long delays (`SKILL.md:415`, `:429`), but the Proposal Review transition says to use source-bound context without spelling out the Result-bound re-save after Proposal creation (`:185–192`). Qualify that existing sequence and measure repeated reading/calls. The checkpoint implementation already binds source and Result identity (`application/working.py:185`); no second memory store is warranted.

3. **Complete context with less serial transport — #474.** Context pagination is a measured cost candidate (602 calls, 436 continuations), not a demonstrated cause of an answer error. Freeze complete context snapshots and supported-host captures; measure bytes, continuations, repairs, latency, and available model token counts separately. Try only bounded removal of repeated scaffolding. Retain complete official qualifiers, Evidence identity, counterevidence, uncertainty, and exact recovery. Hold unchanged if adjudicated premise validity cannot be shown non-inferior.

4. **Retrieval runtime cost — #461; qualification and cost — #463/#464.** Profile cold/warm retrieval and render reuse before optimization. The trace shows broad tool use, but zero-hit queries alone do not identify a retrieval bug. First qualify scientific accuracy on Trial-separated adjudications, then compare model/effort and optimize cost. A byte reduction or cheaper model is not a scientific gain.

The failed-call distribution is concrete host friction, but its causes span several typed fields and most guards protect the scientific boundary. Existing #474/#463 measurement can report transport validation failures separately from application repairs; the evidence does not yet support a separate issue or broader schema rewrite.

## Existing safeguards and simplifications

- `CONTEXT.md` keeps model reasoning with the host and workflow authority with the server. MCP exposes one complete Proposal validation/save path and atomic Domain writes (`interfaces/mcp/server.py:2595`, `:3114`); repairs return proposed fixes without selecting replacement answer values.
- Source capture, projection, exact-span Evidence, visual delivery, and search derivatives have separate identities and verification (`application/evidence.py:581`, `:801`, `:3713`; `projection_verify.py`; `application/source_archive.py`). Retrieval receipts are navigation facts, not semantic support or absence.
- Working notes are noncanonical and Result/source-bound; delivered reading is distinct from understood content (`application/working.py:185`; `workflow_models.py:162`). Domain context labels host-asserted sufficiency and retains recovery (`application/domains.py:2020`, `:3023`).
- The scientific pack retains official answer options, branch activation, and deterministic domain/overall rules (`packs/scientific.py`; `logic/evaluator.py`). Finalized output is independently verified (`application/finalization.py:3640`).
- Keep the existing host-owned loop, checkpoint, review projection, and evaluation harness. Add no mandatory second model, search quota, answer heuristic, or another provenance layer. ADRs 0032 and 0034 still say “implementation pending” despite the active contract and code; update those historical status notes when convenient, but this is documentation drift rather than a product issue.

## Coverage inventory

| Area | Source and test coverage inspected | Boundary of this pass |
| --- | --- | --- |
| MCP and workflow | `interfaces/mcp/server.py`, `application/contracts.py`, `proposal.py`, `domains.py`, `trials.py`, `working.py`; lifecycle, MCP, strict-boundary, idempotency, repair, approval, and working-checkpoint tests. | Targeted call/repair and lifecycle paths; not every error/concurrency branch. |
| Source capture and retrieval | `application/evidence.py`, `source_archive.py`, `source_handles.py`, `projection_verify.py`; search ranking/cache, projection integrity, PDF/JSON/DOCX, Evidence, visual-delivery, and source-handle tests. | No exhaustive PDF-render fidelity or cold/warm performance profiling. |
| Scientific model and host guidance | `packs/scientific.py`, `logic/evaluator.py`, `models.py`, `workflow_models.py`, portable `rob2-assess/SKILL.md` and nine references; logic, scientific semantics/guidance, result, missing-data, and answer-option tests. | Spot-checked guidance and outcomes; not an expert review of all five licensed question sets. |
| Evaluation and run evidence | `evaluation/{harness,cohort,adjudication,observations,coverage,qualification_report}.py`, benchmark/comparison/qualification scripts, current `fresh-4e03e798` scores and traces, prior audit artifacts. | Reproduced current trace counts locally; no paid rerun and no independent ground-truth adjudication. |
| Contract/docs | `CONTEXT.md`, ADRs 0031–0036, `docs/release/public-contract.json`, prior audit findings and #455–459/#461–464/#472–476 issue bodies. | Read-only status/overlap check; no GitHub changes. |

**Disposition:** no separate new implementation issue recommended. Reuse #473–476 and #461/#463/#464; add repair-failure and observed certainty-recode counts to their existing measurements, then let independent adjudication decide whether those patterns need a minimal change.
