---
name: rob2-assess
description: Assess trial results with rob2-kit. Use for RoB 2 intake, source review, Result selection, Evidence capture, Domain judgments, restart recovery, problem terminals, and Batch finalization.
---

# Assess a trial result

Drive the assessment through the public rob2-kit tools. Treat `get_status` as the source of truth after every restart and review.

Call rob2-kit tools directly as tool calls; never type their names into a shell.

The server owns workflow state, record identity, and deterministic RoB 2 logic. You supply scientific choices and Evidence selections. The Proposal Review is the sole scientific researcher gate: before approval, the researcher may accept the displayed source-reported candidate or ask you in natural language to choose another candidate; revise the Proposal and present the fresh Review. After Proposal approval, do not ask for a final review or approval, whether to continue, or permission to pause. Follow the server's next action through every Domain until finalization or a typed `needs_input`/`failed` terminal.

## Result-choice invariant

Choose in this order: (1) an exact assessable Result; (2) the closest
complete non-exact assessable candidate or profile; (3) unavailable only when
no complete assessable candidate exists. Missing comparator values do not make
a fully reported one-arm categorical profile unavailable. For any such profile,
use `single_group_category_profile`, keep every randomized arm in `target`, set
`reported.group_id` to the supported arm, and never invent comparator
categories. Repair the draft toward the best complete assessable candidate;
do not use `unavailable` as a shortcut. The first valid, most salient, or
easiest-to-extract candidate is not necessarily closest: complete the mandatory
candidate phase below before stopping or proposing.

Every tool returns one closed receipt. Read `outcome` first, then the required
`head` (`phase`, `state_revision`, `next_action`, and authoritative wording).
Successful and review-required receipts put tool-specific fields under
`data`; repairs put only `repairs`, conflicts put `conflict`, and conditions
put `condition`. Do not look for tool fields beside `data`.

## Complete the Batch

1. Call `get_status` first. Pass `head.state_revision` unchanged as
   `prepare_batch.expected_revision`, then call `prepare_batch` with the user's
   requested clinical outcome concept. Remove task framing such as `assess risk
   of bias for` or `risk of bias of`. Also omit Trial names and scope phrases
   such as `in TRIAL-A`; Trial identity comes from the input directory. For
   example, `Assess risk of bias for a requested outcome in TRIAL-A` supplies
   `requested_outcome:"a requested outcome"`. The server
   discovers every immediate,
   non-hidden Trial directory under `input/{TRIAL NAME}/`, derives stable Trial
   IDs from those directory names, and recursively captures supported sources.
   Call `prepare_batch` directly. Do not use shell, glob, or file-listing tools
   to inspect or declare Trial directories. Never replace the user's requested
   outcome with a source endpoint. For example:
   `{"requested_outcome":"a requested outcome","expected_revision":0}`.

   Completion: `get_status` reports a Captured Batch and the next host operation is proposal work.

2. Intake conditions are typed constraints carried with the Captured Batch; they do not create a
   researcher gate. Continue to source review and Result construction. Proposal Review is the
   only researcher pause.

   Completion: status reports proposal work in `head.next_action`.

3. Use `list_sources`, `search_sources`, and `read_pages` to find the requested Result. Tool page numbers are 1-based source-page indexes, not printed journal or protocol labels. `read_pages` returns server-issued numbered lines; select text by page and inclusive line range. If the passage begins or ends within a shared line, copy only a unique `start_text` or `end_text` from that boundary line; never reconstruct PDF text. Search modes are `all` (every token on the same page), `phrase` (known adjacent ordered wording), `any` (at least one discovery term), and `prefix` (token-prefix). Use `all` or `any` for concept discovery; do not put noncontiguous concepts into `phrase`. A truncated search does not invalidate a positive exact passage, but refine it before treating candidate discovery as complete or using it as an absence basis. Use `render_page` when layout, axes, columns, symbols, or footnotes affect meaning; it returns pixels by default.

   `read_pages` accepts only the explicit `pages` list; it has no `limit` or
   range argument. Search hits name their Source role and label. Source-first
   ordering is a navigation priority, not an exhaustiveness claim: use a
   narrower follow-up query when the active question points to a protocol,
   SAP, registry, or other later-ranked Source.

   Use staged discovery. First search the main article with both the requested
   outcome wording and a broader event-family term. For example, search both
   `requested outcome` and `event family`. Read the bounded pages that
   contain complete quantitative candidates, including nearby table rows and
   footnotes. Inventory those candidates before consulting another Source. Do
   not stop at the first table row or at the first Source label that resembles
   the request.

   Next, use registry material for prespecified outcome identity, definition,
   and time frame. Use supplements, protocols, and SAPs for competing
   definitions, prespecification, methods, missing context, or when the main
   article lacks a complete result. A protocol label can define a reported
   endpoint, but it does not prove that endpoint is the closest match to the
   requested outcome. Before Proposal, perform a bounded cross-source check for
   materially competing complete definitions. Do not read entire supplements
   or protocols.

4. Before selecting Evidence, extracting values, or constructing the Result
   schema, complete this mandatory Result-choice phase:

   1. List every complete main-article candidate found, then add materially
      competing candidates from other Sources.
   2. Compare each candidate's event set, time origin or window, population,
      measurement, and added state criteria.
   3. Choose the complete candidate with the fewest added criteria that directly
      covers the requested construct. For an umbrella or composite request,
      prefer a complete candidate that covers the full reported event family
      over a complete component or narrower state-specific endpoint.
   4. If another candidate is better, revise the proposal instead of submitting alternatives.
   5. Only then select Evidence, extract values, and build the Result.

   Read only the pages needed to compare candidate definitions. Once a complete
   candidate is visible, read further only to find competing candidates or
   required context; do not read the whole article mechanically. Search beyond
   the abstract, summary, or first hit before concluding that no closer complete
   candidate exists. Do not rank by clinical salience, abstract accessibility,
   name similarity, or effect size. Never infer equivalence from identical
   numbers. An isolated component is a last resort when no complete profile or
   closer candidate is reported.

5. Before calling `save_proposal`, read [Specify the Result](references/result.md) and [Select Evidence](references/evidence.md). The proposal is one object with a `results` array:

   - every Result has `trial_id`; the server derives the captured `requested_outcome` from Intake;
   - an assessable Result has `kind`, `relation`, `target`, and `reported`; the server derives `clarity`, Evidence, and canonical bindings; a non-exact relation also has `relation_rationale`;
   - an unavailable Result has `kind`, `relation` (`ambiguous` or `unavailable`), and `missing_facts`. Each missing fact is one object with `fact` and a nested `basis`: use `missing_reporting` with a selected Evidence handle when the Trial has Sources, or use `intake_condition` with `code:no_supported_sources` only when the captured Batch contains that exact condition and the Trial has zero captured Sources. For `missing_reporting`, the server retains the selected quote or transcription as the complete exact source premise. The basis must be an explicit missing-reporting premise or the exact captured no-source condition, not merely a related endpoint. Unavailable is not an escape from Evidence or Proposal Review.

   Call `save_proposal` with `{"results":[...],"expected_revision":<current state revision>}`. The Result cards are top-level under `results`; there is no `proposal` wrapper and no nested revision. Do not put `trial_id` or `outcome` beside a Result's own fields. Do not send an `evidence` field, table or figure wrappers, `clarity`, `bindings`, or `value_digest`. Evidence selection is already durable server state: the server binds the Result against selected material and retains only Evidence that supports a Result field.

   The server derives canonical bindings for proof-critical Source-owned
   leaves under `target` and `reported`; do not send a `bindings` field. The
   server reconstructs `/target/outcome_definition`,
   `/target/measurement/metric`, and `/target/effect_of_interest` from Intake
   and the fixed contract. Target method, intended population, and intended
   effect measure are model/researcher interpretation fields shown at review,
   not duplicate quotation claims. Target timing and arm assignments require
   selected source support. Comparison-group IDs remain
   caller-supplied structural identifiers. Repeated `reported.group_id` and
   each reported `group_values[].group_id` or `values[].group_id` are structural
   references: they must match target IDs but do not need separate Evidence
   mappings. `category_axis_names` are structural dimension declarations;
   source-owned labels remain in each category value's `category_axes`.
   Reported endpoint fields, arm assignments, category labels, and reported
   quantities still require exact or normalization-equivalent support from
   selected typed Evidence. Each handle resolves to one immutable selected
   Evidence item; do not copy clauses, paraphrase the quote, or author
   source-to-value mappings.
   Keep the endpoint name and at least one complete quantitative result tuple in
   the same selected immutable Evidence item. Set `reported.endpoint.definition`
   only to the exact complete definition tied to that same endpoint label in a
   selected passage; otherwise use `null` (never borrow a component or related
   endpoint definition):
   effect measure plus estimate, or one complete group-value tuple
   (statistic/value/unit) for a comparative effect; statistic/value/unit for a
   group-bound value; or category axes/value for a category profile. Precision
   is checked independently and is not required in the anchor. Do not splice
   an endpoint from one passage with values from another.

   Mechanical result shape: do not repeat the captured request in a Result.
   The server reconstructs `requested_outcome`, `target.outcome_definition`,
   `target.measurement.metric`, and `target.effect_of_interest` from Intake and
   the fixed workflow contract. Send `target.measurement` as `{method}` only.
   Keep the
   Source-reported endpoint separate in `reported.endpoint`. When the reported
   endpoint differs, use a researcher-visible non-exact relation and explain
   the mapping, or use an evidence-bound unavailable result.
   Relations are relative to the requested target: `broader` means the
   reported event/population/time scope is a superset; `narrower` means a subset
   or additional restrictions; `component` means one constituent of a requested
   composite or category; and `related` means overlap without one of those
   ordered relations. Added criteria make a candidate narrower, not broader.
   Name the material differences in the rationale.
   Keep both randomized arms in the target even when a Source reports only one
   arm's profile. The selected Evidence handle is the provenance; do not add
   redundant model-authored premise text.
   For `single_group_category_profile`, set `category_axis_names` to the
   ordered non-treatment dimensions shared by every cell (one dimension is
   valid). Set the shared `denominator_basis` once on the profile. Each
   category value then contains only `category_axes` and the complete opaque
   source cell `value` (for example, `count (percentage)`), with exactly one source-owned
   label for each axis name, in source order. Do not invent statistic or unit
   labels that the selected material does not contain. If a source prints both
   counts and percentages in one cell, preserve the complete cell value.
   `reported.endpoint` is `{name,definition}` from the Source; its name is an
   endpoint label, not a summary statistic. Use `relation:"exact"` only when
   the target outcome name and reported endpoint name match after Unicode,
   whitespace, case, and hyphen normalization; do not infer synonyms. For
   `relation:"exact"`, omit `relation_rationale`; the server derives the
   server-provable rationale sentence. For a non-exact relation, provide a
   researcher-visible rationale explaining the mapping. Each endpoint field
   must be supported by selected Evidence; the fields may
   use different selected passages. This is a provenance requirement, not a
   server inference that the endpoints are scientifically equivalent.
   `target.measurement` is `{method}` and timing is the explicit
   `described` or `quantified` union. Each target comparison group is
   `{id,assignment}` with the complete randomized arm. A comparative report
   uses `effect_measure`, `estimate`, and optional `precision`,
   `group_values`; a group-bound report uses `values`. Each group value is
   `{group_id,statistic,value,unit}`, and reported group IDs must equal target
   group IDs. Do not send parallel quantities or group lists. Figure drafts
   are handle-only: `{"kind":"figure","handle":"..."}`.
   The selected visual Evidence owns the render identity, normalized region, and
   one exact self-contained transcription containing every applicable title,
   axis, series, label, value, unit, uncertainty, denominator, and footnote;
   never invent typed visual fields or repeat/paraphrase the transcription in a
   Proposal. The server labels each selected figure `text_corroborated` or
   `host_visual`; never supply or infer this label. Prefer text corroboration:
   it is assigned only for a full-page region whose transcription has an exact
   normalized span in persisted page text. `host_visual` remains valid for
   image-only figures and diagrams. Transcription is literal visible content
   only; put interpretation in the Result relation rationale or Domain
   rationale/basis. Every figure-bound Result leaf must occur in the selected
   transcription. Host-visual Evidence may bind only literal
   endpoint/name/definition, reported values or category axes, arm-assignment
   labels, and stated time points or windows. Intended population,
   analysis/measurement method, prespecification, and conduct claims require
   text-corroborated or narrative Evidence. The review record exposes
   provenance, transcription, render, and region.
   Preserve paired values; do not invent or collapse labels or values. The server
   supplies render identity, region, and transcription. Fix every repair in the
   same draft and retry; do not declare the result unavailable
   merely because a draft needs repair. This package assesses the effect of
   assignment to intervention; the server supplies the exact closed effect
   discriminator. Never put an intervention name in that field.

   Completion: each Trial has one complete Result card or one complete unavailable disposition in the proposal `data`. Every Source-derived structured fact, including every unavailable missing fact, has one nested typed Evidence basis. Before submission, perform a premise audit: each exact cited fragment must entail the field or question proposition it is attached to. If it does not, revise the claim conservatively or use a concrete missing fact. Do not cite a lead-in or unfinished list, and do not use an inference about missingness when the source does not state the relevant premise. If a related endpoint or profile contains enough data, revise and resubmit one complete assessable non-exact Result rather than declaring it unavailable solely because names differ.

6. After a restart, call `get_status` first. During proposal phase it returns bounded `selected_evidence` records (handles plus the selected material metadata); deterministically reselect a missing passage before rebuilding the typed Result card. Do not repeat handles in the card. Call `save_proposal` with top-level `results` and the current State revision in required `expected_revision`. Repair every returned defect together. If the server prepares a Proposal Review, ask the researcher to review that exact record.

   Completion: `get_status.head.phase` is `assessment` or every affected Trial
   has an automatically committed terminal disposition.

7. Call `get_domain_context`. Use the returned cards for the selected Domain:

   Before the first save for every Domain, complete bounded question-specific
   discovery. Treat operational retrieval concepts in each active question card
   and terms in the linked Domain reference as optional leads, not a required
   query list or checklist. These are example concepts expressed with official
   wording, not fixed queries. Choose, combine, reformulate, or ignore them
   based on the active question, documents read, observed terminology, and
   unresolved evidence gap. Use the exact words, synonyms, related concepts,
   document-specific terminology, or another query that addresses the active
   evidentiary question. Search relevant method Sources such as the protocol or
   SAP when present, not only the main article and not only already selected
   Result Evidence. When an active question points to a protocol, SAP, registry,
   or another named later-ranked Source, consider passing that Source's ID to
   `search_sources` instead of repeatedly broadening an all-Source query. Read
   every positive hit that could answer the question. If the bounded search has
   no hits, retain its untruncated no-hit receipt. Do not
   author a limitation or `no_information` answer merely because the needed
   premise is absent from the current context.

   The returned `result` is a compact approved Result projection: it omits
   canonical `bindings` while retaining target, reported result, and Evidence
   handles/identities. Use the separate returned Evidence records
   for the selected material; do not expect proof-oriented binding arrays in
   Domain context.

   Treat each returned `questions[*]` compact card as the authoritative contract
   for that question. Its `official_guidance` is the complete official source
   excerpt and its `source_locator` identifies the official location. Its
   actionable operational fields are `decision_rule`, `evidence_needed`,
   `answer_anchors`, `no_information_rule`, and `invalid_shortcuts`. The
   scientific pack retains the full nested official and operational guidance for
   artifact and audit use; the card deliberately omits operational metadata that
   is not needed on this answering path. Apply the card directly; loading a
   Domain reference file is optional. Do not equate missing direct evidence with
   `no_information`:
   use firm `yes`/`no` only when the evidence supports that definitive answer,
   use `probably_yes`/`probably_no` when the circumstances support a reasonable
   judgement, and use `no_information` only when insufficient details prevent
   either probable answer and it would be unreasonable to choose either one.
   Do not substitute a generic endpoint label, ITT statement, or relationship
   label for the card's premise rule.

   Exact quotation is necessary but not sufficient: the selected premise must
   state the proposition being answered. Treatment assignment or visibly
   different interventions do not by themselves prove participant or personnel
   awareness. Different treatment or visit schedules do not by themselves
   prove differential outcome measurement. One endpoint definition does not
   prove that there were no multiple eligible measurements or analyses.

   - Domain 1: [Assess randomization](references/randomization.md)
   - Domain 2: [Assess deviations from intended interventions](references/deviations.md)
   - Domain 3: [Assess missing outcome data](references/missing.md)
   - Domain 4: [Assess outcome measurement](references/measurement.md)
   - Domain 5: [Assess selection of the reported result](references/selection.md)

8. Call `save_domain_judgment` with top-level `trial_id`, `domain_id`,
   `expected_revision`, `answers`, and (when requested) `multiple_concerns`.
   Include every initially active question plus each dependent question whose
   activation predicate is met by your earlier answers. The server ignores and
   never commits extra inactive branch answers, so one conservative superset is
   safe when a branch is uncertain. Each active item in `answers` is one nested response with `question_id`,
   `answer`, and non-empty `bases`. A basis is a limitation, a server-issued
   absence receipt, or a selected Evidence handle. For a `limitation`, pass
   the opaque `sr_...` `handle` returned by `search_sources` as
   `search_receipt`; it must be a non-truncated receipt from the current Trial
   corpus (positive or no-hit). For an `absence` basis, pass the opaque
   `sr_...` `handle` returned by
   `search_sources` as `search_receipt`; do not copy the receipt's `identity`.
   The receipt must be an untruncated no-hit result (`truncated:false`,
   `total_matches:0`, `condition:no_hits`); refine a truncated or positive
   search before using it to support absence.
   Limitations, absence, context, and inference alone cannot justify a
   definitive answer; apply the p.3 response framework and the question card
   before choosing a probable answer or `no_information`. The missing-outcome
   evidence question deliberately disallows `no_information`, so provide a
   direct Evidence basis there. Apply all Repairs before you continue.

   **Premise audit.** A Domain Evidence selection must contain one complete
   exact premise; the server retains that selected quote or transcription as
   `source`, not a summary of the whole Domain or a hoped-for answer.
   Before saving, compare the active question's proposition with the exact
   cited premise. If it does not entail the answer, choose the appropriately
   conservative probable or `no_information` response as allowed, or use a
   limitation or scoped absence account. `direct_support` states what the
   passage says; `indirect_support` states only the premise that the passage
   supports through an explicit link; `context` states scope or meaning;
   `contradiction` states the conflict; and `inference` is reserved for a
   conclusion directly warranted by the selected premise. The relationship
   label never licenses a broader answer.

   Keep method plans separate from conduct. A protocol or SAP can establish
   what was planned, but not what participants or assessors actually did unless
   the same passage reports conduct. A time origin, analysis population, or
   endpoint definition does not establish complete follow-up, equal assessment,
   objective measurement, blinding, prespecification, or no alternative
   analyses. Stratification does not establish allocation concealment. Claims
   about a protocol or SAP require the exact selected passage from that dated
   protocol or SAP, with the date and document scope clear in the selected premise.

   Select one complete premise, sentence, or list for each Domain Evidence
   use; never cite a header or list-introducing lead-in alone. Reuse Result
   Evidence only when its exact source fragment supports that question. Nest
   each basis under its answer. A direct basis sends only the selected Evidence
   handle. The server derives and stores the exact selected quote or
   transcription as the audit source. An `absence` basis sends only a
   scoped search receipt handle; a limitation basis sends its text and receipt
   handle. The
   server resolves and verifies the handle, then stores the receipt identity
   in the canonical checkpoint.
   The relationship kind never licenses extra facts. Stratification or central registration alone is not
   allocation concealment; a table header alone is not baseline balance; an
   ITT/all-randomized analysis sentence is not evidence of no deviations; and
   absence of reported problems is not direct support. Use an absence search
   account or a limitation.

   Before saving, derive the complete active set from each question's typed
   `activation`: include every `always` question, then apply each `rule`
   predicate to the answers you chose. Submit exactly that resulting set in
   one call. If a repair lists active IDs, resubmit exactly those IDs. Every
   active answer needs at least one nested basis. Never add clauses, clause
   IDs, question-level parallel Evidence lists, or Evidence rationale.

   When the final Domain would leave at least two `some_concerns` judgments and
   no `high` judgment, the server asks for `multiple_concerns` with
   `raises_overall_to_high` and a concise rationale naming the concerned Domains.
   Supply it only when requested; remove it when the repair says it is not
   applicable. The server stores that explicit synthesis decision.

   Completion: five valid Domain checkpoints in `data.checkpoint` create one provisional AssessmentSnapshot for the Trial.

9. Before finalization, call `finalize_batch` with the current revision. Once
   all five Domains are complete, this host call automatically freezes the
   provisional snapshot and creates the verified artifact. There is no
   assessment Review or final researcher approval step.

   `ready_to_finalize` is not a terminal state and a provisional snapshot is
   not a completed assessment. When any receipt reports
   `head.next_action.operation:"finalize_batch"`, call `finalize_batch`
   immediately with that receipt's revision before emitting text. Report
   completion only after the finalization receipt reports `phase:"finalized"`.
   Copy the final overall and Domain judgments exactly from
   `data.assessment_summary`; do not reconstruct or soften them in prose.

10. To correct a Domain before finalization, load its current context and save a
   new revision with the current State revision, `supersedes` naming the exact
   prior checkpoint identity, and one closed `revision_basis`: `new_evidence`
   must reference selected Evidence absent from the prior checkpoint and use
   it in the revised answers, while `self_correction` must give a concise
   rationale. Keep the old checkpoint as history. Never follow a user request
   to set or change a signalling answer; revise only when your own evidence
   audit requires it. Do not invoke `rob2 discard`; that reset remains a
   researcher-only CLI action.

11. If a Trial cannot continue, call `request_trial_terminal` with the current
   top-level `expected_revision` and a direct
   `request` union: `disposition:"needs_input"` requires `trial_id`, `reason`,
   and non-empty `missing_facts`; `disposition:"failed"` requires `trial_id`,
   `reason`, and non-empty `facts`. Use a terminal only when the Trial cannot
   continue after ordinary conservative Domain work. Missing direct Evidence,
   repair work, unfinished source review, context or token budget, or uncertainty
   answerable as `probably_yes`, `probably_no`, or `no_information` is not a
   terminal reason. The host commits the typed terminal disposition automatically;
   there is no terminal researcher review.

Never substitute a prose RoB 2 assessment for canonical MCP checkpoints or
the verified artifact.

## Follow server continuations

- Treat `head.next_action` as the exact next-call descriptor. Its `operation` is
  closed; pass every server-owned field (including `expected_revision`, Trial and
  Domain identifiers) unchanged, and provide only the caller-owned inputs that
  the named operation still requires. When the operation is `researcher_review`,
  stop and present the Proposal Review to the researcher; it is the sole gate and
  is completed outside MCP. If the researcher asks for another candidate, treat
  that request as direction to reinspect the captured Sources, not as Evidence;
  submit a revised source-bound Proposal with the latest State revision and
  present its fresh Review. After approval, continue from `get_status` without
  accepting researcher-supplied signalling answers. Do not ask whether to
  continue or pause for progress confirmation; repeatedly follow
  `head.next_action` through every Domain until finalization or a typed
  `needs_input`/`failed` terminal.
- Pass server-issued handles and references unchanged.
- After Proposal Review approval, call `get_status` first, then follow every
  `head.next_action`; do not report Domain judgments before saving their typed
  checkpoints.
- Use the latest State revision for each mutation.
- On a Workflow conflict, discard the stale draft. Call `get_status` and rebuild from current state.
- On a transport retry, resend the identical mutation. Do not confuse a transport
  retry with a researcher-directed Proposal revision before approval.
- Treat `needs_input` and `failed` as unassessed outcomes.
