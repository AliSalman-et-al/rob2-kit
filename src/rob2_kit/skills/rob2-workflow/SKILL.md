---
name: rob2-workflow
description: Run a RoB 2 batch through the typed rob2-kit MCP workflow, from source intake through external researcher review and artifact finalization.
---

# RoB 2 workflow

The generated public contract defines every payload and schema. Use it when a field is unclear. The server issues status, Records, Evidence, Transitions, and acknowledgments. Preserve each issued value byte for byte.

## Run this state machine

1. Start from the launcher's injected `Verified rob2-kit entry status`. On a later invocation, start from its new injected status. During one run, use each tool response's status or typed continuation to choose the next operation. If the host exposes `rob2://current-batch`, you may read it for recovery. It is not required.

   | Current review | Typed continuation | Action |
   | --- | --- | --- |
   | `researcher`, unsatisfied | Any | Stop. Return the exact review purpose and record. |
   | `host`, `none`, or satisfied | Present | Call the typed operation now. |
   | Any | Absent | Make no mutation. Return the authoritative status. |

   Researcher review is an external CLI or UI boundary. Do not run it, create an acknowledgment, or continue past it. On a later invocation, the launcher supplies the satisfied status, acknowledgment, and Transition. Continue from that returned continuation. On a condition or conflict with a continuation, follow it. If uncertainty has no continuation, stop and return the exact condition. Complete when the next action came from a server response or you returned its unresolved condition.

2. For `preflight_sources`, take the authorized root path, alias, and Trial ID from the researcher prompt or launcher context. Take `expected_head` from the typed continuation when it is present. If a required root field is absent, stop and name that missing input. Call `inspect_candidate_sources` only to resolve a listed candidate or source question. Complete when `preflight_sources` returns the current preflight reference.

3. For `save_intake_plan`, save a complete plan for that preflight. If status then requires researcher review, stop under step 1. On the later invocation, call `capture_batch` with the exact plan and injected acknowledgment. Complete when a returned continuation offers `save_proposal` work.

4. Build the exact Result target from the current prompt, status, and Records. Preserve the researcher outcome label. Keep the exact outcome separate from a broader endpoint, narrower endpoint, component, protocol-planned endpoint, and related endpoint. Use an operational definition only when a source explicitly supports it. Complete when the draft identifies the definition, measurement, time window, intended population, effect, and two comparison groups without filling a gap from expectation. After a restart, reconstruct this draft only from authoritative records and the current prompt.

5. Create Evidence in separate round trips for every target and result fact.

   1. Call `list_sources`. Use `retrieve_evidence` for search or exact page reads. Use `render_page` when image appearance matters. These outputs navigate a source.
   2. In a later `retrieve_evidence` call, submit an exact normal, manual, or visual selection to mint Evidence.
   3. Call `read_record` with the returned Evidence identity. Cite that returned identity in the Proposal.

   Search-hit identities and render identities are navigation handles, not Evidence. For a Proposal, only the Evidence identity returned by `retrieve_evidence` after an exact normal, manual, or visual selection may be used in `save_proposal`. Structured values need text Evidence. For a manual offset, first read the exact page text. For a visual selection, transcribe only the literal visible text. Resolve a text, OCR, and image conflict before binding the value. Complete when every submitted claim has selected, read, source-entailing Evidence.

6. Build each Result card from one semantic table unit. Inspect its title, analyzed population, row, columns, units, denominators, and footnotes before extracting a value. Make an internal axis map: population, randomized group, category, and measure. Bind a number to a comparison group only when its source label states that mapping. Categories are not arms. Unsupported comparison coverage becomes evidence-backed `needs_input`. Complete when every group binding has an explicit source label.

   Choose stable comparison group IDs once and reuse them exactly in `target.comparison_groups`, `reported.comparison_groups` or group bindings, and `population.outcome_measurement_coverage`. For coverage, when the source reports the requested outcome for both target comparison groups, include a `measured` entry for both target comparison groups only when Evidence supports outcome measurement; otherwise use the appropriate `needs_input` disposition.

7. Construct the Proposal in this submission order. Use the generated public contract for exact fields. Do not invent candidate fields.

   - Set stable group IDs and exact target fields.
   - Set reported form, analyzed population, and source table meaning.
   - Put one exact contiguous source passage in `reported_text`. It must name the outcome label or definition and contain every structured reported component.
   - Preserve source-reported precision and denominator bases for a comparative effect and every group quantity.
   - Set outcome-measurement coverage and each clarity field.
   - Bind target basis, reported values, reported context, and population basis Evidence.

   If one passage cannot support all structured reported fields, reduce the structured fields to that passage or use source-backed `needs_input`. Do not combine passages into a fabricated `reported_text`. When the researcher supplies `<label>, defined as <definition>`, use that exact full text in `ProposalInput.outcome_statement` and use the exact suffix as `target.outcome_definition`. Preserve the researcher label. If a source explicitly gives an expanded definition, write `Effect on <researcher label>, defined as <exact source definition>` as the outcome statement. Otherwise use the researcher-supplied definition and make `effect_of_interest` `effect on ` followed by it. Complete when each Trial has one exact Result card or one source-backed preapproval disposition.

8. Use an absence disposition only after an absence review. Before considering `outcome_not_measured` for a researcher-supplied `<label>, defined as <definition>`, search the primary report abstract and results for the complete definition and its distinctive component phrases. A broader, narrower, component, protocol-planned, or merely related endpoint is not evidence that the exact requested outcome is absent and must not replace it. Do not select `outcome_not_measured` while an exact requested-outcome result is reported in any included source. Before using `outcome_not_measured`, inspect every included main report/result source likely to report the requested outcome and cite complete passages that establish the unresolved absence or definition problem. At that point, search hits and clipped line fragments are not sufficient Evidence for a terminal scientific disposition. When the exact requested-outcome result is found, build the Result card from that result even if another related endpoint is more prominent or appears elsewhere. Complete when the disposition and its Evidence address the exact outcome, not a neighbour.

9. Call `save_proposal`. Repair every returned field defect, then save again. On success, read the exact returned Proposal with `read_record`. If status requires researcher review, stop under step 1. When a later status is `proposal_approval_ready`, call `approve_batch` with the injected exact Transition and acknowledgment. The exact researcher acknowledgment has resolved any compatibility review, so do not reinterpret or reopen it. Complete when returned status supplies an approved Batch or terminal continuation.

10. For `needs_input` or `failed`, use `prepare_trial_finish` only with the typed packet and a source-backed candidate that matches the generated contract. Stop when it returns researcher review. On a later invocation, use its injected Transition and acknowledgment with `finish_trial`. Complete when returned status records that Trial as terminal.

11. For `validate_domain_judgment`, hand its exact `work_packet` reference to `rob2-signalling`. The packet contains canonical question guidance with wording, allowed answers, and structured activation. The returned typed continuation chooses the next tool call. An `assessment_in_progress` status describes progress. A returned `next work_packet` is an immediate instruction to continue in this same run. After each `commit_domain_judgment`, consume its returned `next work_packet` immediately. Reuse persisted Evidence whenever it supports a later Domain. Retrieve one specific missing signalling fact, never by rescanning the full corpus per Domain. RoB 2 has five Domains, but returned status and continuations decide whether this Trial or another Trial is next. Complete when the returned continuation is synthesis, Trial finish, another packet, or an exact condition.

12. At synthesis review, stop only when returned status requires the researcher. On the later invocation, call `finish_trial` with the injected Transition and acknowledgment. When returned status says every Trial is terminal, call `finalize_batch`. Complete only when authoritative returned status says finalized and the response includes the artifact receipt. Report the returned summary and ordered outcomes.

## Examples

These are reasoning demonstrations, not payload templates.

- Evidence handle. Search a source, select the exact text in a later retrieval call, receive Evidence, read that Evidence, then cite its identity.
- Table axes. Columns labelled spring, summer, and autumn are time periods, not treatment arms. A value needs an explicit group label before group binding.
- Endpoint identity. "Weekly practice time" is not automatically "performance rating." Treat them as equivalent only when the source directly defines that relationship.

## Tool boundary

The public tools are exactly `preflight_sources`, `inspect_candidate_sources`, `save_intake_plan`, `capture_batch`, `list_sources`, `retrieve_evidence`, `render_page`, `save_proposal`, `approve_batch`, `validate_domain_judgment`, `commit_domain_judgment`, `prepare_trial_finish`, `finish_trial`, `finalize_batch`, and `read_record`.
