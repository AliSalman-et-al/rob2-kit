# Bounded construction and citation findings

The four failed save calls are preserved in [construction-failures-and-D2-history.json](construction-failures-and-D2-history.json), with their original arguments and validation messages. These failures did not save an assessment or change a scientific answer.

| Attempt | Domain | Observed construction defect | Subsequent behavior |
|---|---|---|---|
| 1 | D2 | Two inline bases use shortened `sh_1f0972948ff7f` instead of issued `sh_1f0972948ff7f02f`. | Validation rejects malformed handles. |
| 2 | D2 | The same shortened handle is resubmitted in the same inline positions. | The model subsequently copies the complete handle and saves D2. |
| 3 | D3 | One role-wrapped inline basis again uses the shortened handle. | The model repairs construction and saves D3. |
| 4 | D4 | Three role-wrapped inline bases use that shortened handle. | The model repairs construction and saves D4. |

Both unwrapped inline passages and role-wrapped inline passages are supported input forms; switching form was not itself the defect. The raw union error includes missing `evidence`/`role`, visual-branch fields and extra-input reports alongside the decisive `source_id` pattern error. Those are alternative schema-branch diagnostics, not requirements that all fields be added. This distinction matters when assessing friction. A bounded general ergonomic follow-up would highlight the malformed Source-handle path and require copying the complete issued handle, while retaining every existing ID, reading and evidence-integrity guard. No guard was relaxed, no preferred answer or trial-specific recovery hint was supplied, and no behavioral benefit is claimed from a change that was not tested.

D2 has two saved canonical checkpoints. The model’s review revision says its second context passage used a one-page offset and referred to baseline data; it replaced that citation with article physical page 4, lines 102–145 (the participant-flow account). Its No information answer and Some concerns judgment remained unchanged. The exact old and revised warrants, ordered bases, identities and revision rationale are preserved. This was a within-session model revision, with no operator feedback.

A separate unrepaired D3 citation defect is visible in the frozen output: the direct-support basis is article physical page 5, lines 117–145, which contains baseline-characteristic cells rather than the completeness claim in its justification. The relevant follow-up statement appears at page 5, lines 24–38 and is provided only in the reviewer-recovery section. Product, standalone and exact quote-binding checks pass because they verify identity, structure and literal binding rather than the clinical entailment of the warrant. The original D3 warrant, citation, answer, unknowns and judgment remain unchanged. This observation does not decide the scientifically appropriate answer or Domain label.
