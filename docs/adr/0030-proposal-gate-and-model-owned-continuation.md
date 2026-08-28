# Use one Proposal Review gate and model-owned continuation

Status: accepted

## Context

RoB 2 assessment has two authority boundaries. A researcher must choose or
correct the Result mapping when the requested outcome and the source endpoint
differ. The model can then answer the deterministic signaling questions and
save the assessment from the committed evidence.

The server cannot infer whether a later user message is a scientific answer,
an instruction, or a request to change the workflow. Treating conversation
text as authority would make the audit trail ambiguous.

## Decision

- Use one researcher gate: `Proposal Review`. The researcher can approve,
  reject, or replace the proposed Result mapping.
- The first Proposal save contains one Result card per captured Trial. While
  Review is pending, a correction replaces only the submitted Trial cards;
  the server carries forward every unmentioned card into the fresh immutable
  Proposal and Review.
- After approval, signaling answers belong to the model. The model continues
  through Domain judgments and automatic finalization. There is no final
  researcher review.
- A model can revise a committed Domain only through exact revision lineage.
  Each revision must use newly selected Evidence absent from the prior
  checkpoint or state an explicit self-correction. The server preserves the
  complete history.
- Intake conditions do not pause for researcher review. Typed `needs_input` and
  `failed` terminals commit automatically. Neither creates another gate.
- Treat user answer instructions as non-authoritative. Refuse them as answers
  to scientific questions. After Proposal Review, the host and skill accept
  only the minimal `Continue.` prompt in the same session and do not pass
  scientific answer feedback to the server.
- Keep `rob2 discard` researcher-only. It preserves the audit evidence and
  resets the workflow so the researcher can start a new Result target.
- Qualification and dogfood runs must not coach Domain answers. Audit the
  final output, then retain it as evidence or discard it and restart without
  coaching.

This decision supersedes the prior Domain-correction and Assessment Review
assumptions, including the relevant #258 acceptance point.

## Consequences

The workflow has one clear human decision. Domain judgments remain attributable
to the model and traceable through revisions. A researcher who disagrees with a
completed assessment uses `rob2 discard` and starts a new Result target instead
of editing the conversation into an unprovable causal history.
