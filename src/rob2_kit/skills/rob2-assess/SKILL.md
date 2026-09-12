---
name: rob2-assess
description: Assess one requested trial outcome with rob2-kit, from Batch intake and Result selection through evidence-grounded RoB 2 Domain judgments and finalization.
---

# Assess a trial result

Drive the complete assessment through the public rob2-kit tools, not shell
commands.

The server owns workflow state, identities, and deterministic RoB 2 logic. You
own source interpretation, Result selection, Evidence selection, and signalling
answers. Proposal Review is the only researcher gate. After approval, continue
without asking for signalling answers, progress confirmation, or final approval.

## Read one complete MCP receipt

Hosts may expose a tool result as `structured_content`, `structuredContent`, or
one JSON text content block. Use the structured object when it is available; if
it is not, parse the single JSON text block once. Keep that complete receipt as
working context, including `head`, `data.result`, `questions`,
`comparison_cards`, `evidence`, `evidence_workspace`, `reading_recovery`, and
any `recovery` or `next_action` fields. Do not render only `questions` (or a
`questions.map(...)` projection), and do not concatenate the structured and
text representations. Keep `render_page` image content blocks separate from
the deduplicated JSON; render and inspect the image when layout carries
meaning.

If the host reports `Warning: truncated output`, treat the receipt as
delivery incomplete. On a Codex host, repeat the identical context or read
request with a `functions.exec` `max_output_tokens` value large enough for the
measured output. Keep explicit `trial_id`, `domain_id`, and page/window
scope arguments applicable to that tool unchanged on every retry: Trial and
Domain for context, or source and page/window ranges for reads. Inspect the rendered output for truncation and
confirm that the decision-critical sections are visibly present before
interpreting evidence; parsing JSON alone does not establish complete host
delivery. If the cap persists, retry smaller exact page windows or render a
lossless section that preserves the same scope and fields. A truncated receipt
is a transport failure, not a no-hit or absence result. A Codex
`functions.exec` probe can render one copy:

```javascript
// @exec: {"max_output_tokens": 20000}
const r = await tools.mcp__rob2__get_domain_context({
  trial_id: "trial-id-from-head.next_action",
  domain_id: "domain-id-from-head.next_action",
});
const textPart = r?.content?.find((part) => part?.type === "text")?.text;
const receipt = r?.structuredContent ?? r?.structured_content ?? (textPart ? JSON.parse(textPart) : null);
if (!receipt) throw new Error("MCP receipt unavailable; delivery incomplete");
text(receipt);
```

## Follow the workflow

### 1. Recover or prepare the Batch

Call `get_status` first. Follow `head.next_action` and complete any required
reading before scientific work. Pass server-owned IDs and `expected_revision`
unchanged.

When the Batch is empty, call `prepare_batch` with only the clinical outcome
concept from the request. Do not include the Trial name, population, comparison,
effect estimate, follow-up, or other Result facets in `requested_outcome`; those
belong in the Proposal. If the researcher named Trials, pass their exact input
directory labels. Omit `trial_labels` only when the request covers every input
Trial.

Examples:

- `Assess risk of bias for a requested outcome in Trial A` maps to
  `{"requested_outcome":"a requested outcome","trial_labels":["Trial A"],"expected_revision":0}`.
- `Assess risk of bias for a requested outcome across Trial A and Trial B` maps
  to `{"requested_outcome":"a requested outcome","trial_labels":["Trial A","Trial B"],"expected_revision":0}`.
- A request covering every input Trial maps to
  `{"requested_outcome":"a requested outcome","expected_revision":0}`.

Confirm from the receipt that the captured Trial labels match the requested
scope.

### 2. Discover and choose one Result per Trial

Before choosing a Result, [read the main report](references/read-main-report.md)
in bounded consecutive text windows from the full captured Source. Finish the
required pass before targeted discovery and Proposal submission. At the reading
ceiling, preserve partial coverage and inspect relevant omitted passages during
targeted discovery.

Read [Specify the Result](references/result.md). Use targeted searches and reads
to compare complete reported candidates and resolve gaps from the main report.
Establish pack applicability from this Trial's source Evidence before proposing
an assessment. Follow [Establish pack applicability](references/result.md#establish-pack-applicability)
for unsupported or unresolved designs.
Use registry, protocol, SAP, or supplement Sources for material competing
definitions and missing context after the main-report reading. For search modes,
continuation, and no-hit recovery, follow
[Reuse inspected passage handles](references/evidence.md#reuse-inspected-passage-handles).

Choose in this order:

1. an exact assessable Result;
2. the closest complete non-exact assessable candidate or profile;
3. an unavailable Result only when no complete assessable candidate exists.

Compare event set, time origin or window, population, measurement, and state
criteria. Do not rank candidates by name similarity, effect size, clinical
salience, or abstract accessibility. Matching numbers do not prove equivalent
endpoints. Resolve material competitors; do not read every Source mechanically.

### 3. Ground and save the Proposal

Read [Select Evidence](references/evidence.md). Use exact passages you have
inspected. Search hits and `read_pages` windows already provide reusable
`passage_ref` handles. Put the chosen handles in an assessable card's optional
`passage_refs`; the server promotes them atomically to Evidence. Use
`select_text_evidence` only when you need a different line boundary. Use
`render_page` and `select_visual_evidence` when layout carries meaning.

Build Result cards from the live `save_proposal` schema. The first save contains
one card for every captured Trial. While Proposal Review is pending, submit only
complete replacement cards for corrected Trials; the server preserves the rest.

For an assessable Result, the server reconstructs the captured outcome and
closed effect of interest, then derives clarity, retained Evidence, and bindings.
Do not send those derived fields or put Evidence objects inside `reported`.
Every Source-owned reported field needs exact or normalization-equivalent support.

For an unavailable Result, give each concrete missing fact its closed basis:
selected missing-reporting Evidence, or `no_supported_sources` only for a
captured Trial with zero Sources. Unavailable Results still enter Proposal Review.

### 4. Complete Proposal Review

Present the exact immutable Proposal Review and stop for the researcher. If the
researcher corrects a Result, use it as source-review direction and save a
complete replacement card. Present the fresh Review.

After explicit approval in conversation, call `request_proposal_approval` with
the empty arguments object `{}`. Its
client elicitation binds approval to that Review. Then call `get_status`.
For each approved assessable Trial, recover its approved Result and repeat the
[bounded text reading](references/read-main-report.md) when the Trial
becomes active. Finish when reading status is `complete` or `budget_limited`,
before answering its first Domain. Researcher messages after approval do not
set or revise signalling answers.

### 5. Assess the next Domain

Call `get_domain_context` for the Trial and Domain in `head.next_action`. Treat
each returned question card as authoritative for wording, server-issued options,
activation, official guidance, decision rules, and uncertainty. Open
the matching scientific reference when working on that Domain:

- [Randomization](references/randomization.md)
- [Deviations from intended interventions](references/deviations.md)
- [Missing outcome data](references/missing.md)
- [Outcome measurement](references/measurement.md)
- [Selection of the reported result](references/selection.md)

For a comparison card, use `question_id` to find its wording and options in
`questions`. Before citing Evidence with `text_status:"omitted"`, confirm that
you have inspected its complete passage and can assess the cited premise. If
the passage is unfamiliar or its content is uncertain after a restart or
compaction, follow
[Recover omitted Evidence](references/evidence.md#recover-omitted-evidence).

Review inspected passages against each active proposition and check material
contradictions. Reuse adequate Evidence without another search. For an
unresolved premise, use bounded, premise-specific discovery across the
relevant Sources. Start with concrete wording from the study, call `list_sources`
only when the active context has no complete Source inventory. When a
comparison card is returned, use its inventory first to find unopened
supplements or combined documents. Treat Source roles as navigation hints
rather than proof of what a document contains. If a narrow search returns no useful
passage, broaden once with concrete study language and widen the Source scope
when the premise may be elsewhere. Continue an existing cursor when deeper
cached results are needed, then read the returned page windows before citing
them. Follow [Select Evidence](references/evidence.md#recover-an-unresolved-premise)
for the full recovery loop. Stop when the complete premise is grounded or
when the relevant captured Sources and bounded cursor/page windows have been
checked and the remaining information limit is documented with a current,
untruncated receipt. Do not search every question mechanically.

For each answer, copy exactly one server-issued `options[].id` from
the current question card into `answers[].option_id`, character for character.
Treat it as opaque text; do not reconstruct it from memory. The server
resolves that identity to the official RoB 2 code before constructing the
checkpoint. Do not submit both an option ID and a separate answer code, and do
not invent option IDs after a card or pack version changes. The checkpoint and
artifact retain the standard official answer code.

For each active answer, use at least one closed basis from the live schema:

- selected Evidence for `direct_support`, `indirect_support`, `contradiction`,
  `context`, or `inference`;
- an untruncated no-hit search receipt for `absence`;
- concise text plus a current-Trial untruncated search receipt for `limitation`.

Selected Evidence must contain the complete premise. A relationship kind adds
no facts. Definitive `yes` or `no` requires direct,
indirect, or contradictory Evidence. Probable answers may instead rest on a
limitation, absence receipt, or exact context/inference premise when the card
allows that answer. Apply `response_framework.no_information_rule`: consider
`probably_yes` and `probably_no` from the available facts and trial circumstances
before choosing `no_information`, subject to the card's rule. State any inference
in `justification`. Missing explicit text alone does not establish
`no_information`; silence alone does not establish `probably_no`. For D3.2,
`no_information` is unavailable, but `probably_no` or `no` may express that the
available evidence does not demonstrate freedom from missing-data bias; do not
invent affirmative Evidence.

### 6. Audit and commit the Domain once

Draft an answer for every question returned for the Domain, including questions
whose `active` flag is currently false. That flag reflects the saved state;
your new answers can activate further questions in the same call. Use current
card option IDs and supported bases for every answer. Submit the complete set
in one `save_domain_judgment` call. The server resolves activation from your
answers and commits only active answers.

Before saving, compare each active answer with the approved Result in the
current Domain context: outcome definition, population, comparison, and time
point. Check the selected passages against the exact proposition and guidance
on that question card. Choose the option whose literal meaning follows from
those passages and any stated uncertainty. Add a concise `justification` when
an inference, conflicting evidence, or uncertainty connects the passages to the
answer. The audit is complete when every active answer addresses that Result
and its bases support the claims attributed to them.

For D3.1, run the **availability audit** before saving: Yes/Probably Yes needs
actual outcome-availability evidence; analysis membership, planned or scheduled
follow-up, treatment continuation or discontinuation, and a generic censoring
rule alone do not suffice. For mortality, recovery or discharge alone does not
establish later vital status. Use [Missing outcome data](references/missing.md)
to reconcile outcome-specific counts, follow-up, and censoring.

Only question 3.1 may carry `missing_data` rows. Keep randomized, observed,
analyzed, imputed, and excluded counts distinct. The server reuses answer
Evidence as row provenance and performs only scope-matched arithmetic.
For an optional count preview before saving D3, follow
[Reconcile availability](references/missing.md#reconcile-availability).

Apply every reported repair and retain other drafted answers. Add missing
questions to the existing answer set; include every returned question before
resubmitting. The server ignores inactive answers.
When the final Domain triggers a `multiple_concerns` Repair, supply the
requested object and rationale. Do not
send that field otherwise.

### 7. Continue every Trial

Save each Domain before moving on. The fifth accepted checkpoint freezes the
Trial snapshot; confirm `data.trial_completed:true`, then follow the returned
`head.next_action` into the next Trial.

Use `request_trial_terminal` only for a concrete inability to continue after
ordinary conservative Domain work. Repairs, unfinished review, context limits,
or uncertainty answerable with a permitted probable or `no_information` answer
are not terminal reasons. Terminal Trials are unassessed.

### 8. Finalize and report

When `head.next_action.operation` is `finalize_batch`, call it immediately with
the current revision. `ready_to_finalize` is not completion. Report results only
after the receipt says `phase:"finalized"`, copying judgments from
`data.assessment_summary` without reconstructing them.

## Recover from interruptions

- After a restart or context compaction, call `get_status` before any other
  workflow call and resume its exact next action. Use `get_domain_context` to
  restore Domain Evidence and the active checkpoint. Do not recreate completed
  work from memory.
- Earlier read coverage proves delivery in that read checkpoint, not retained
  context. Recover needed passages whose content is missing or uncertain, and
  resume any unfinished main-report read. Follow
  [Recover after a later restart](references/read-main-report.md#recover-after-a-later-restart).
- If a text passage handle was lost before commit, read the exact window again.
  Canonical checkpoint Evidence remains recoverable.
- On a workflow conflict, discard the stale draft, call `get_status`, and rebuild
  against current state.
- On an uncertain transport retry, resend the identical mutation. A scientific
  correction is a new save, not a transport retry.
- To revise a pending Trial's saved Domain, name the current checkpoint in
  `supersedes` and use the closed `new_evidence` or `self_correction`
  `revision_basis`. Do not use researcher coaching as a revision basis.
- Never invoke the researcher-only `rob2 discard` command.

Never substitute a prose RoB 2 assessment for canonical checkpoints and the
verified artifact.
