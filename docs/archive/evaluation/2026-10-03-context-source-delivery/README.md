# Separate source reading from immutable Domain context

**Offline fix; no paid rerun.** New Domain contexts recover primary-report text through `reading_recovery`/`read_pages` instead of embedding it in frozen context pages. Verified persisted source-delivery receipts now inform `coverage.read`, independently of whether a quote was selected for the current Domain. This reuses existing coverage storage, source identities, hashes, typed tools and citation recovery. It does not change signalling rules or answers.

## Exact cause in the retained Allsop trace

The 18 context calls comprise nine successful D1 pages, four D2 pages, four D3 pages and one D2 header-size condition. D1's initial snapshot contained then-unread primary-report text. The model received the header, read the report separately through two `read_pages` calls, then followed the remaining frozen context chain. That immutable cursor correctly preserved the original snapshot, including six source-text pages, even though some ranges had subsequently been returned by `read_pages`. D2 and D3 had **no inline primary-report text**: there was no demonstrated per-domain whole-report replay.

The server already recorded successfully returned context source ranges as delivery coverage. Constructing a snapshot did not itself mark text delivered. Context text was source-located and selectable through existing `select_text_evidence` recovery; it did not automatically select an evidence handle for every paragraph. The duplicate reading path was partly a model choice, but the frozen text remained server-owned and could not retire after the separate source reads. Premature D1/D2 saves while context continuations remained were model choices; their rejection/recovery is preserved and is not assumed eliminated by this fix.

The paginator greedily packs multiple items **within each section** to the byte budget. It does not put every small item on a separate page: after removing report text, all three D1 question cards fit on one continuation and all five evidence items on another. Sections remain separate; there is no new mixed-section paginator or speculative flag.

## Controlled exact-content replay

[Replay script](replay-allsop-context-delivery.py), [summary](replay-summary.json), [D1 after pages](randomization-after-pages.json), [D2 after pages](deviations-after-pages.json), [D3 after pages](missing-after-pages.json). The original native pages are retained in [the paid trace](../2026-10-03-allsop-full-assessment/events.jsonl).

The script reads the retained immutable snapshots without modifying the paid workspace, reproduces their exact native structured-byte totals using the real short-cursor wire shape and original 18k/24k budgets, then runs the current paginator without inline primary text. It asserts exact equality of every question, selected-evidence item, comparison card, approved Result, answer, official-guidance field and reading-recovery locator. The comparison deliberately retains the old completion wording to isolate removal of source text; current production has shorter source-reading instructions and verified coverage statuses. This is a controlled transport replay, not a prediction of the next model's actions or tokens.

| Domain | Context calls before → after | Structured bytes before → after |
| --- | --- | --- |
| D1 | 9 → 3 | 126,790 → 42,474 |
| D2 | 4 → 4 | 69,790 → 69,790 |
| D3 | 4 → 4 | 59,990 → 59,990 |

The D2 header-size condition remains counted: **18 → 12 total context calls**, saving 84,316 structured bytes. The removed report payload contains 71,913 UTF-8 bytes of *numbered* text, not raw PDF bytes.

Removal alone would omit necessary source delivery. Of the 1,895 inline lines, **1,118** had already been returned by the original native source calls; **777** had not. The replay uses current direct MCP against a disposable database/source copy to deliver those uncovered ranges in **two additional bounded `read_pages` calls** (33,407 structured bytes). It verifies every one of the 1,895 source-located lines is exactly recovered by original plus additional source responses. [Additional deliveries](additional-source-deliveries.json).

Holding every other paid-trace action fixed, equivalent source exposure needs **31 → 27 total MCP calls** and saves **50,909 structured bytes** after accounting for the additional source reads. These are constrained offline counts, not a completed assessment or measured model-efficiency/accuracy gain. No save rejection is assumed removed.

The original Allsop bounded report pass covered 65,497 raw source-text bytes; two final copyright/download footer lines lay beyond its 65,536-byte cap. Read receipts spanning all 11 pages were therefore **not proof of every physical line being delivered**. A separate offline positive control reads those exact two remaining lines in one further native call and verifies both main and supplement become `read_complete`. [Complete-report control](complete-report-control.json). Including that stronger whole-source control gives 28 calls versus 31. No prefix, response or paid token budget was increased.

## Implementation and controls

`primary_report` remains a supported legacy public field for existing frozen receipts but is empty in new contexts. `reading_recovery` continues to expose the required prefix and explicit unread tail, including after receipt loss; primary-reading save guards remain. `source_reading_status` validates the current captured bytes and projection against Canonical identities before reusing source-bound, batch/phase/Trial-scoped read receipts. It marks complete delivery only when the union covers every projected line (or an explicit empty-page receipt). Cached text, selected quotes and working notes alone cannot make source-wide coverage complete. Missing raw bytes are not upgraded to verified complete delivery.

A changed Result invalidates the scientific context basis and calls for renewed relevance assessment; identical verified source content need not automatically be reread. Changed source bytes fail integrity verification. Losing delivery receipts restores exact unread-window recovery. Read completeness remains a delivery fact, not model comprehension, retention, clinical sufficiency or evidence entailment. Scientific counterevidence retains its handle, quote, locator and implication despite complete source delivery.

**21 focused tests passed**: source/context separation and interleaved reads, reuse across Domains/new clients, lost receipts, omitted endpoint passage, changed source, changed Result identity, counterevidence preservation, bounded long-report tail, source-coverage contract, complete conditional question reconstruction, decisive-evidence preview, cursor continuity across unrelated saves, failed-delivery non-advancement and postapproval reading guard/recovery. Ruff, scoped type checks and diff checks passed. The implementation adds no new table, cache identity, launcher flag or scientific branch. Pack guidance and direct MCP schema visibility remain intact.

No clinical answers were repaired, no paid case was rerun, no other case was selected, no broad suite/full benchmark ran, and no CI wait or merge occurred. The remaining uncertainty is actual model enactment and whether the full D1–D5 path will finish within the same guards; this offline result does not establish either.
