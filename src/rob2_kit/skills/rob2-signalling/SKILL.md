---
name: rob2-signalling
description: Complete active RoB 2 signalling questions from an exact approved work packet and commit each validated Domain judgment.
---

# RoB 2 signalling

Start from the exact `work_packet` reference returned by authoritative status. Resolve that reference with `read_record`. The packet fixes the Trial, Result, Domain, question guidance, source inventory, reusable Evidence, and prior checkpoints. Each guidance item supplies its ID, exact wording, allowed answers, and structured activation. The generated public contract defines draft fields. Preserve every packet, Evidence reference, candidate, and Transition unchanged.

## Answer and commit one Domain

1. Read the exact packet with `read_record`. Stop and return the packet condition if `question_guidance` IDs or order differ from `active_question_ids`. Treat the matching lists as the permitted canonical order, not the final answer set. For `activation.kind` `always`, include the question. For `rule`, compare each predecessor answer with its predicate's accepted tokens. `any` needs one match. `all` needs every match. Keep packet order. Complete when the draft contains every and only active IDs in that order, and each answer token is allowed by that question's guidance. This is an internal gate, not server-observable state.

2. For each active question, restate it as an asserted proposition. Include every conditional, causal, likelihood, selection, and comparison clause. Split a compound predicate into clauses. A prerequisite does not establish the conclusion. Complete when each clause has a named source fact or a documented source gap. This is an internal gate.

3. Read `reusable_evidence` first. Reuse persisted Evidence from the packet and prior records whenever it supports the active Domain. List the missing predicates. Retrieve one specific missing fact at a time through the workflow Evidence recipe. Complete when every proposition clause has supporting, contradicting, indirect, or absent source-specific evidence. This is an internal gate.

4. State source-specific facts. An Evidence use must entail its claim. Its claim and rationale must answer the whole proposition. Absence of reporting, routine practice, trial reputation, similar group sizes, stratification, a statistical method, outcome objectivity, or lack of reported problems cannot establish an unreported mechanism or complete follow-up. Complete when each claim cites an entailing fact and no conclusion uses generic expectation. This is an internal gate.

5. Choose an allowed token from the proposition. `yes` supports it. `no` contradicts it. `probably_yes` and `probably_no` need source-specific indirect evidence in that direction. If an unresolved source gap leaves neither direction supported, use `no_information`. Complete when the token and first rationale sentence state the same polarity. This is an internal gate.

6. Write the answer rationale and each evidence-use claim and rationale. Name the exact fact that answers each proposition clause. Include an Evidence reference for every evidence use. Complete when a reader can match each claim to an exact quote or literal visual transcription. This is an internal gate.

7. Perform this mechanical internal gate for every answer before validation:

   - Read question, token, and first rationale sentence as one statement. Their polarity agrees.
   - Check every quote against its claim. The quote entails the claim and the relationship agrees.
   - Check every conditional and qualifier. Each is resolved by source-specific evidence or the answer is `no_information`.
   - Check the canonical activation rule. The ID belongs in the complete active list and has the packet's relative order.

   Complete when every active answer passes all four checks.

8. Call `validate_domain_judgment` with the exact packet and audited draft. A success response returns a candidate and Transition. Read its exact candidate with `read_record`, repeat step 7 on the serialized candidate, then call `commit_domain_judgment` with the exact Transition. Complete when a returned response supplies the next continuation.

9. A repair response returns pointer, code, and detail. Repair every returned defect, including independent defects. The packet's typed activation remains authoritative. Recompute the complete active list from packet guidance and prerequisite answers, then apply the repair to that list. If the defect cannot be resolved from the packet guidance and record evidence, stop and return the exact repair. Validate again. Complete when validation returns a candidate and Transition.

10. Consume a returned packet at once. Repeat immediately for each active Domain. A packet returned by `commit_domain_judgment` must be consumed at once. On a condition or conflict with a continuation, follow that continuation. Otherwise stop and return the exact condition. Once all Domains are committed, return the synthesis or finish continuation to `rob2-workflow`. Complete when the workflow receives that returned continuation.

## Activation and judgment

Answer dependency-driving questions before their descendants. Leave the Domain judgment to deterministic policy unless a scientifically necessary override is documented in the contract field. Use each packet item's activation rule. A conditional descendant stays out of the draft when its premise is false. Example: if a prior question's `no` token fails a descendant's `yes` premise, omit the descendant and keep the remaining permitted order.

## Examples

These are reasoning demonstrations, not answer templates.

- Polarity. The question asks, "Did differences suggest a problem?" Evidence says, "groups were similar." The proposition is "differences suggested a problem." Answer `no`. Answering `yes` would contradict the rationale.
- Compound selection. Several analyses exist. That satisfies only a prerequisite. It does not show that the reported estimate was selected because of results.
- Entailment. Stratified randomization does not establish allocation concealment. If the concealment mechanism is unreported, answer `no_information`.
- Typed repair. A repair says a conditional question is inactive. Remove it, recompute the rest from its activation condition, audit the complete list, then validate again.
