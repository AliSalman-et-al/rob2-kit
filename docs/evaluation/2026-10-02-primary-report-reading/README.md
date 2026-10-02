# Offline primary-report and participant-flow recovery

No model inference, benchmark campaign, automatic risk-label change, or paid retry was performed. Work resumed from the preserved local diff; the prior direct-route run and all original Code benchmark databases remain unchanged. This checkpoint reduces a demonstrated source-delivery gap; it does not establish model accuracy or scientific agreement.

## Diagnosis of the completed direct-route run

The approved DELIVER Result is the randomized-group, time-to-first worsening-HF/CV-death composite through median 2.3-year follow-up. All five retained PDFs were available with matching source/projection identities; registry raw bytes were explicitly unavailable. The main article reports discontinuation 444/442 and unknown vital status two per arm on p3 lines 70–76. These do not establish composite endpoint availability by themselves.

The available appendix p27 contains `Figure S2. Patient flow.` at line 6. It gives incomplete primary-endpoint follow-up 29 at line 19 and 23 at line 29, alongside allocation denominators 3131 at line 25 and 3132 at line 35. Survival-status unknown counts are at lines 20/30, with reasons at 22–24/32–34. Their overlap with incomplete primary follow-up is not resolved by adding counts. This is an existing captured source fact, not hidden reference-label certainty.

[Exact prior queries and ranking](prior-query-diagnosis.json):

- Appendix phrase `loss to follow-up` exhausted with zero hits. The text says **Lost** to follow-up; lexical absence was not scientific absence. Its returned navigation covered p1/p2 and had a continuation, which the model did not follow.
- Protocol `sensitivity analysis missing` (all terms) returned nine ranked passages over seven pages; top ranks were p213 and p259 SAP plans. The model read those, but plans do not establish actual trial follow-up accounting or performed sensitivity analyses.
- Appendix `missing outcome data` (all terms) returned one passage, p23 lines 1–9, about KCCQ symptom-score missingness. The primary composite's disposition figure uses **Incomplete follow-up for primary endpoint**, so this query did not match it.
- Main phrase `vital status known` exhausted with zero hits, despite those three terms each occurring on a page; intervening words defeat the phrase. The main p3 passage was nevertheless delivered through reading/selection.

The model only read main p1/p2/p3 and p5 through line 135. Context supplied a ten-page required reading recovery, but retained D1/D2 bypassed the gate that previously checked only the Trial's first checkpoint. Thus an accepted D3 draft could assert a required pass had been inspected despite missing report ranges. Its No information stopping rationale left available flow accounting unread. No defensible High disagreement can be inferred from that acceptance.

The existing literal Source navigator also excluded candidate headings ending in punctuation. `Figure S2. Patient flow.` consequently lacked a heading entry, though its page might appear later as an ordinary page excerpt. The fix recognizes general numbered figure/table captions in that existing navigator. Navigation advances to v0.3 so old cursor offsets are rejected rather than silently applied to a changed index.

## Minimal general change

`get_domain_context` now projects the unread portion of the existing bounded primary-report pass into typed `primary_report` PageData records. It uses the existing 65,536 UTF-8 source-byte prefix and exact source/physical-line coordinates, verifies retained raw bytes and projection identity, and splits ordinary text into bounded whole-line chunks. No source is overwritten and these projected pages are not selected scientific Evidence.

The existing context pagination delivers those report chunks before question/evidence/card deltas. A manageable report therefore arrives completely in the context chain; longer reports retain `budget_limited` tail recovery. Physical lines that exceed the inline chunk budget retain explicit read_pages fragment recovery. Valid Result/source-bound working checkpoints retain their ADR0032 resumption behavior. Constructing a context does not record future pages as delivered: only the primary_report ranges in a successfully returned response enter the existing page_reads table. This proves source delivery, not comprehension, retention, or scientific sufficiency.

The bounded-prefix requirement now applies when saving any **new** Domain, rather than only when the Trial has no checkpoint. Prior Domains cannot substitute for actual coverage. Existing accepted saves keep idempotent replay semantics, and valid working checkpoints still permit resumption. No unlimited whole-document gate is introduced.

For D2/D3, the current Source coverage projection offers up to 20 unread, bounded flow/disposition or outcome/follow-up heading windows per captured supplement. It reuses the literal navigator and standard read_pages recovery, not trial-specific phrases or reference labels. Already delivered windows stop recurring. The projection is advisory: it neither extracts counts nor creates absence receipts, selects Evidence, answers a question, changes a risk label, or requires reading every appendix page. Hosts can still submit a scoped unknown with an explicit stopping rationale. The current bounded data model remains the authority.

## Offline evidence versus host reading

[Replayed fixture](replay-fixture.py) uses a separate copy of the preserved Code-benchmark diagnostic workspace, clears only that copy's derivative delivery records, and makes local FastMCP calls without a model. [Canonical preservation](canonical-preservation.json) proves the canonical database is byte-for-byte unchanged.

The replay's six context pages are: stable header; two primary-report pages; questions; Evidence; comparison cards. Together they deliver all ten main-report physical pages and all 45,601 source-text bytes, recording the existing status as complete. [Full delivered context](context-pages.json), [coverage summary](summary.json).

Structural navigation independently found appendix p27 lines 6–38 without a DELIVER-specific query. The replay then used that exact recovery window in an ordinary read_pages call, delivering the 29/23 counts with a source-bound passage reference. [Found windows](structural-navigation.json), [actual delivered flow text](flow-page-delivered.json).

The prior paid model did **not** read those counts. The offline replay **did** deliver them to a client. No new model interpreted them or submitted a judgment. Available, navigated, delivered, selected, and scientifically understood evidence remain distinct.

## Validation and limits

Four new behavioral cases cover complete manageable-main delivery before question deltas, projection-versus-delivery coverage, prior-Domain bypass prevention, the existing long-report bound, and a no-counts flow-caption control. The no-counts control creates navigation but no quantities or selected Evidence, and preserves submission of a scoped unknown rather than forcing every appendix page. Existing read-first, typed schema, coverage, sequential/frozen context, validation-failure, large-budget, and literal-navigation checks pass. Focused test outputs are retained in the task record; Ruff, ty and diff checks pass. The working-checkpoint handoff test now counts inline report delivery separately from explicit read_pages calls: only the stale handoff receives repeated source text, while a valid Result-bound handoff receives none. Its context request uses the default 24,000-byte budget; this enriched checkpoint header exceeds its former explicit 16,384-byte budget (16,499 bytes), for which the existing larger-budget condition remains honest recovery.

Navigation is a document-structure aid, not an exhaustive semantic search. Image-only or unusually formatted flow information can still require rendering or broader reading. Relevant appendix windows remain host-owned choices, with honest scientific stopping rationales rather than automatic risk coercion. The added report delivery can cost context and calls; no paid token or accuracy improvement is claimed. A subsequent bounded model diagnostic needs separate authorization and must record actual reading and warrants again.
