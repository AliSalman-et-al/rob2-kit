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

Most tools return the typed receipt in `structuredContent`. Keep the complete
receipt as working context, including `head`, `data.result`, `questions`,
`comparison_cards`, `evidence`, `evidence_workspace`, `reading_recovery`, and
any `recovery` or `next_action` fields. Keep `render_page` image blocks beside
the structured receipt and inspect the image when layout carries meaning.

If `structuredContent` is missing, branch before transport recovery. When
`isError` is true or the result contains a validation error without
`structuredContent`, read the text in `content`, correct the named argument
using the published schema, and retry the corrected call. When the result has
`outcome:"repair"`, fix every listed path and resubmit the complete draft.
Raise the output limit only when the host explicitly reports truncation. Do
not treat a missing structured receipt as a no-hit or absence result.

Use this Codex probe to inspect either a receipt or an error:

```javascript
// @exec: {"max_output_tokens": 20000}
const status = await tools.mcp__rob2__get_status();
const head = status?.structuredContent?.head;
if (!head?.next_action || head.next_action.operation !== "get_domain_context") {
  text(status?.structuredContent ?? status?.content ?? []);
  throw new Error("get_status did not return a get_domain_context action");
}
const r = await tools.mcp__rob2__get_domain_context({
  trial_id: head.next_action.trial_id,
  domain_id: head.next_action.domain_id,
});
const receipt = r?.structuredContent ?? null;
if (receipt) {
  text(receipt);
} else {
  text(r?.content ?? []);
}
```

For pagination, cursor recovery, and output-size handling, read
[Receipt and continuation recovery](references/evidence.md#receipt-and-continuation-recovery).
Keep the first page and every continuation in separate host-visible outputs.
Pass each returned cursor unchanged. Do not assess from page zero while a
continuation remains.

Use separate `functions.exec` calls when the host renders each page alone. The
first call stores the returned cursor:

```javascript
// First functions.exec call: use Trial/Domain from head.next_action.
const status = await tools.mcp__rob2__get_status();
const head = status?.structuredContent?.head;
if (!head?.next_action || head.next_action.operation !== "get_domain_context") {
  text(status?.structuredContent ?? status?.content ?? []);
  throw new Error("get_status did not return a get_domain_context action");
}
const r = await tools.mcp__rob2__get_domain_context({
  trial_id: head.next_action.trial_id,
  domain_id: head.next_action.domain_id,
});
const page = r?.structuredContent ?? null;
if (!page) {
  text(r?.content ?? []);
} else if (page.outcome !== "success") {
  text(page);
} else {
  text(page);
  store("domain-next-cursor", page.data?.context_page?.next_cursor ?? null);
}
```

```javascript
// Separate functions.exec call: load and pass the cursor unchanged.
const cursor = load("domain-next-cursor");
if (!cursor) {
  text("No continuation cursor is stored.");
} else {
  const r = await tools.mcp__rob2__get_domain_context({ cursor });
  const page = r?.structuredContent ?? null;
  if (page?.outcome !== "success" || !page?.data?.context_page) {
    text(page ?? r?.content ?? []);
  } else {
    text(page);
    store("domain-next-cursor", page.data.context_page.next_cursor ?? null);
  }
}
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
scope. Inspect intake conditions before concluding that evidence is unavailable.
Search covers captured text projections only. Supplied files listed as
unsupported, unreadable, or missing were not searched. A declared role does not
establish document contents. DOCX support covers ordinary paragraphs, table
headers and cells in order, and footnotes through a synthetic page-1 projection;
that is not Word pagination and does not extract all embedded content. Legacy
`.doc` remains unsupported. Image-only PDFs can be recovered with `render_page`
even when they have no searchable text.

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
For a source-scoped miss, inspect its literal navigation entries, use term
feedback and captured wording to choose whether to reformulate or read the
relevant section directly. Batch searches only when their query inputs are
already known; wait for a result before choosing a dependent reformulation.
Continue navigation when the displayed entries do not identify a useful page
or query. Stop when the premise is resolved or the captured material has been
inspected enough to state what remains unavailable; no fixed search count
proves completeness.

Choose in this order:

1. an exact assessable Result;
2. the closest complete non-exact comparative candidate;
3. an unavailable Result when no complete comparative candidate can proceed to
   RoB 2 assessment.

Compare event set, time origin or window, population, measurement, and state
criteria. Do not rank candidates by name similarity, effect size, clinical
salience, abstract accessibility, family size, or profile completeness. Matching
numbers do not prove equivalent endpoints. Resolve material competitors; do not
read every Source mechanically. A one-arm category profile is descriptive, not
comparative: preserve its exact source passage as Evidence and submit an
unavailable Result with the missing comparator result as a concrete missing fact.

### 3. Ground and save the Proposal

Read [Select Evidence](references/evidence.md). Use exact passages you have
inspected. Search hits and `read_pages` windows already provide reusable
`passage_ref` handles. Put the chosen handles in an assessable card's optional
`passage_refs`; the server promotes them atomically to Evidence. Use
`select_text_evidence` only when you need a different line boundary. Use
`render_page` and `select_visual_evidence` when layout carries meaning. Select
visual Evidence only with the `delivery_receipt` returned alongside an actual
`ImageContent` block; metadata-only renders do not issue a receipt.

Build Result cards for the live `validate_proposal` schema. The first validation call
contains one card for every captured Trial. While Proposal Review is pending,
submit only complete replacement cards for corrected Trials; the server preserves
the rest.

For an assessable Result, the server reconstructs the captured outcome and
closed effect of interest, then derives clarity, retained Evidence, and bindings.
Do not send those derived fields or put Evidence objects inside `reported`.
Every Source-owned reported field needs exact or normalization-equivalent support.

For an unavailable Result, give each concrete missing fact its closed basis:
selected missing-reporting Evidence, or `no_supported_sources` only for a
captured Trial with zero Sources. Unavailable Results still enter Proposal Review.

Before saving a Proposal, submit its Result cards and a brief evidence-based
assessment for each submitted Trial with `validate_proposal`. For an assessable
Result, provide separate `scope_justification` and `population_justification`;
for an unavailable Result, provide `missing_fact_justification`. Explain why the
reported result supports the target relation and chosen time point or window.
Distinguish baseline eligibility from exclusions or missing observations in the
reported analysis. Identify material conflicting evidence and unresolved facts;
do not infer unavailable facts. The server validates structure, Evidence
references and workflow requirements, not scientific correctness. Save using the
returned `reasoning_id`.

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

### 5. Assess a Domain

Call `get_domain_context` for the active Trial and Domain in `head.next_action`,
or pass an explicit `domain_id` to inspect or assess another Domain before
committing the next one. Read `data.pack.version` and treat every returned
question field, including wording, options, activation, and official and
operational guidance, as authoritative. Domain receipts remain usable while you
investigate or commit another Domain in the same Trial, provided the approved
Result, pack, preview, and requested Domain checkpoint stay unchanged. Search
results and unrelated Domain commits do not invalidate an existing page chain.
Recoverable discovery candidates are omitted by default; use
`include_candidates:true` on a fresh request when those candidates are needed.
Revalidate after changing an assessment dependency. Treat each returned
question card as authoritative for wording, allowed answer values, activation,
official guidance, decision rules, and uncertainty. Open the matching
scientific reference when working on that Domain:

Before the first `validate_domain_assessment` call, read
[Build a Domain answer](references/evidence.md#build-a-domain-answer) for the
complete answer and basis shapes.

- [Randomization](references/randomization.md)
- [Deviations from intended interventions](references/deviations.md)
- [Missing outcome data](references/missing.md)
- [Outcome measurement](references/measurement.md)
- [Selection of the reported result](references/selection.md)

If `data.context_page` is present, fetch ordered pages until `next_cursor` is
null. Verify the same Trial, Domain, frozen page revision, page count, and
contiguous page indexes across the sequence. The current `head.state_revision`
may advance after unrelated workflow changes. Pass each cursor unchanged and
do not assess while a cursor remains. Use [Receipt and continuation recovery]
(references/evidence.md#receipt-and-continuation-recovery) when a cursor is
invalid or stale, structured content is missing, or the host reports
truncation. Keep each page host-visible and reconstruct the complete question,
comparison, Evidence, and recovery fields before deciding. If the server
returns a header or item oversized condition, retry the same explicit scope
with the larger `required_page_size`; an unrecoverable condition requires
review without dropping a field. Recover the Evidence needed for each premise
with `read_pages`, and render `render_page` image blocks separately when layout
matters. Inspect the actual image block and pass its `delivery_receipt` to
`select_visual_evidence` before using a transcription.

For a comparison card, use `question_id` to find its wording and options in
`questions`. Before citing Evidence with `text_status:"omitted"`, confirm that
you have inspected its complete passage and can assess the cited premise. If
the passage is unfamiliar or its content is uncertain after a restart or
compaction, follow
[Recover omitted Evidence](references/evidence.md#recover-omitted-evidence).

Review inspected passages against each active proposition and check material
contradictions. Reuse adequate Evidence without another search.

Before a new material discovery attempt, follow the
[unresolved-premise loop](references/evidence.md#recover-an-unresolved-premise).
Use it for material facts realistically discoverable in captured Sources, and
keep the search or read in the same working assessment. Before
`validate_domain_assessment` and `save_domain_judgment`, revisit material unknowns
against the Source inventory, identify the section inspected and facts still
unavailable, then make one bounded search or read or document a bounded limit.

For each answer, submit `answers[].answer` as one of the official values listed
in that question card's `options` (`yes`, `probably_yes`, `probably_no`, `no`,
or `no_information` when permitted). These values retain their literal polarity:
`yes` and `probably_yes` express the proposition; `no` and `probably_no` reject
it; `no_information` means neither probable answer is reasonable under the
question's rule. The server rejects values not allowed for the stated question.
When a repair reports that an answer is unsupported or otherwise invalid, keep
the submitted proposition literal in the repair; do not change `no` to
`probably_yes`, or infer a different answer from the repair wording. Reconsider
the scientific conclusion only from the evidence and your own reasoning.

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

Draft every active question in the dependency-closed path implied by the drafted
upstream answers and activation predicates. Preserve unresolved upstream facts as
unknown; do not invent a downstream premise or answer. Include an inactive
answer when it is already available; it needs no fabricated reasoning and the
server ignores it. Use allowed card answer values and supported bases for every
submitted answer. Submit the complete active set in one
`validate_domain_assessment` call. The server resolves activation from the draft
and commits active answers after `save_domain_judgment` consumes the returned
`reasoning_id`.

Before saving, compare each active answer with the approved Result in the
current Domain context: outcome definition, population, comparison, and time
point. Check the selected passages against the exact proposition and guidance
on that question card. Choose the option whose literal meaning follows from
those passages and any stated uncertainty. Every active answer must include a
concise `justification`, an `unknowns` array, and a `counterevidence` array. The audit
is complete when every active answer addresses that Result and its bases support
the claims attributed to them.

Do not make `save_domain_judgment` the primary next action. The next scientific
step is `validate_domain_assessment` after `head.next_action`, `reading_recovery`,
and any required Evidence reading are complete; follow another continuation
first when it is present.

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

Commit the exact draft stored by `validate_domain_assessment`. Supply its
returned `reasoning_id` and revision to `save_domain_judgment`. To change the
draft, call `validate_domain_assessment` again with the complete revised draft.

Apply every reported repair and retain other drafted answers. Add missing
questions to the existing answer set. Resubmit the complete resulting active
path. Keep an inactive answer when it is already available and has valid
reasoning. Do not invent inactive questions or reasoning. The server ignores
inactive answers.
When the final Domain triggers a `multiple_concerns` Repair, supply the
requested object and rationale. Do not
send that field otherwise.

### 7. Review and close every Trial

Save each Domain before moving on. The fifth accepted checkpoint makes the
Trial ready for review and returns `data.trial_ready_for_review:true`; it remains
correctable until closed. Call `review_trial` with the current Trial and
revision. With all five checkpoints, review it as assessed. Unavailable Results
and unsupported designs receive their specific unassessed outcome. For a real
blocker on a supported Trial, provide a typed `needs_input` or `failed` request.

Inspect the review's exact Result and checkpoint identities. If a Domain or
Result needs correction, make the correction and request a fresh review. Search
and reading activity alone does not invalidate it. Close the Trial with the
exact `review_reference` and current revision returned by status. Closure is
immutable and advances to the next Trial or Batch finalization; do not skip it.

Normal review and an automatic unavailable or unsupported-design review use the
same callable request. Omit `request`:

```json
{"trial_id":"trial-a","expected_revision":12}
```

For a genuine post-approval blocker on a supported Trial, include one complete
typed request. Missing or unestablished design facts belong in the Proposal;
they trigger the automatic unsupported-design review and must use the normal
request with `request` omitted. Use an explicit blocker only when the current
supported Result and completed Domains cannot be reviewed because a separate
operational fact is unavailable:

```json
{"trial_id":"trial-a","expected_revision":12,"request":{"disposition":"needs_input","trial_id":"trial-a","reason":"The approved Result is supported, but the review export is unavailable.","missing_facts":["Review export"]}}
```

Use the current `trial_id` and `expected_revision` from `head.next_action` for
both forms. Do not send `request` when the Result or five completed Domains
already determines the review.

After a successful review, close with the exact returned review identity:

```json
{"trial_id":"trial-a","expected_revision":13,"review_reference":"sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
```

Use the current revision from the review receipt and copy
`data.review.identity` directly into `review_reference`.

### 8. Finalize and report

When `head.next_action.operation` is `finalize_batch`, call it immediately with
the current revision. `ready_to_finalize` is not completion. Report results only
after `head.phase:"finalized"`, copying judgments from
`data.assessment_summary` without reconstructing them.

## Recover from interruptions

- After a restart or context compaction, call `get_status` before any other
  workflow call and resume its exact next action. Use `get_domain_context` to
  restore Domain Evidence and the active checkpoint. Do not recreate completed
  work from memory.
- If `data.working_checkpoint.status` is `current`, use its source-located
  notes to resume the investigation, then reread each cited passage before
  relying on it. Preserve recorded uncertainty. A draft answer is not a saved
  answer, and these notes are not Evidence or a Domain checkpoint. If the status
  is `absent` or `stale`, reorient from current Sources and do not transfer old
  drafts across a Result change.
- Before a long delay or context compaction, call `save_working_checkpoint` for
  an open Trial when useful observations, interpretations, terminology, unread
  ranges, open questions, or unfinished drafts would otherwise be lost. Cite
  exact page and line ranges (or `0,0` for a whole-page visual locator). Saving
  replaces the prior notes and does not change workflow revision or assessment
  state; `get_status` exposes them only while the Source scope and Result match.
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
