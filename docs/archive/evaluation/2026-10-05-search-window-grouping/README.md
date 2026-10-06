# Literal search-window grouping: offline mechanism check

The previous candidate recipe coalesced match-line ranges before preview expansion. Separate anchors could therefore yield identical literal windows, each consuming a bounded response slot. The nine frozen MONALEESA-3 searches contained 23 such duplicate windows, including two duplicate slots in the first protocol “progression free survival” response.

## Change and scientific limits

Candidate recipe v0.10 expands local match clusters before applying the existing 80% overlap rule within one continuous Source page. Grouped candidates preserve the union of their literal windows and use the earliest constituent cluster for ordering. Unions must fit the existing 2,048-byte candidate cap. Oversized original clusters retain full bounds and explicit read_pages recovery. Distinct pages, Source identities and versions never merge, even when text is identical. BM25 page ranking and Source tie-breaking are unchanged; no answer-specific query or ranking rule was introduced.

The existing candidate start/end/line fields now describe the grouped literal window, or the complete oversized recovery range. The query, captured page and exact coordinates retain recoverable match anchors; no anchor is replaced by a summary. Preview and passage_ref Evidence share literal bounds. Candidate counts, distinct_passage_count, contiguous ranks, cursor offsets, Domain associations, coverage receipts and exhausted state use the grouped candidates. Matching-page and Source counts retain their previous meaning.

The recipe participates in the existing session identity. Old ranks/cursors cannot silently be interpreted as new ranks; restarting an old cursor requires a fresh search. Historical v0.9 receipts reconstruct the original recipe and remain verifiable. Unsupported recipe values fail closed. Existing frozen receipts and assessments were not rewritten.

This is an evidence-presentation improvement. It does not prove a missing-page cause, agent reading, better judgments, or accuracy. The [earlier scientific qualification](../2026-10-05-monaleesa-audit-qualification/README.md) remains applicable. No paid calls, new scientific assessment, MONALEESA retuning, or full benchmark occurred.

## Actual nine-query native replay

Two isolated copies of the frozen workspace were used: the preserved installed v0.9 wheel and current source code. They ran the actual two batches (five then four queries) with the original queries, modes, Source scopes and requested limits. The baseline reproduced every frozen delivered hit coordinate and preview SHA-256. All nine historical receipts verified in both conditions. New bounded-batch receipts verified, and exhaustive cursor traversal reached every candidate once in both conditions. Captured-source verification occurred through the normal native path; no network acquisition occurred.

| Source/query | Candidates old → new | First-response distinct pages old → new | Preview UTF-8 bytes old → new |
|---|---:|---:|---:|
| SAP: progression free survival / any | 101 → 84 | 2 → 3 | 2,983 → 3,158 |
| SAP: analysis plan / any | 215 → 189 | 2 → 2 | 2,921 → 2,973 |
| Protocol: progression free survival / any | 282 → 246 | 2 → 2 | 3,027 → 3,013 |
| Protocol: unblinded / any | 28 → 28 | 2 → 2 | 2,838 → 2,838 |
| Protocol: analysis plan / any | 201 → 187 | 1 → 1 | 2,775 → 2,775 |
| SAP: primary analysis / phrase | 14 → 14 | 6 → 6 | 3,845 → 3,845 |
| SAP: PFS analysis / all | 66 → 64 | 3 → 3 | 4,024 → 4,024 |
| Protocol: primary analysis / phrase | 19 → 19 | 4 → 4 | 3,838 → 3,838 |
| Protocol: unblinded results / any | 119 → 112 | 3 → 3 | 3,726 → 3,726 |

All 23 exact duplicate windows disappear across the complete rankings; the 1,045 candidates become 943 through exact and strongly overlapping grouping. Six first responses have identical windows. The first SAP progression search now includes physical page 102 instead of additional page 42/page 6 windows. Protocol progression search uses fewer page 153 windows but remains on pages 153/166. Delivered hit counts stay six per first batch query and eight per second batch query.

The complete structured transport envelopes, including the content/structured_content wrapper, are 31,123 → 31,191 bytes for batch one and 31,607 → 31,607 for batch two. Union preservation can increase quote size; this is not a response-size reduction claim.

**Neither SAP physical page 30 nor 43 moves into any first response.** In “analysis plan,” the cover moves from rank 20 to 19 and the page-43 assertion candidate from 182 to 156; both remain behind the cursor. The other page-43 candidate moves 181 → 155. In “PFS analysis,” page 43 moves 61 → 59, but its window does not include the separate before-lock/unblinding assertion. “Primary analysis” still does not match page 43. These changes do not establish that an agent would continue or read either page.

[Nine-query measurements](nine-search-summary.json) include exact page/line bounds, preview hashes, cursor/receipt checks and key-page ranks without copying the private transcript.

## Independent Code-repository projection controls

All 18 cached Albert-2013 and all 24 cached DAPA-HF searches from `rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01/cases` were compared, including no-hit queries. These are fixed-first-20 projection comparisons, not native batch replays or agent runs. Every original candidate reconstruction matched the cached v0.9 payload exactly. Every original literal window and every enumerated match anchor is contained in a new candidate or retained oversized recovery range. All eight Source page projections match their canonical extraction-recipe/hash bindings. Captured-source folders are absent in these archived case workspaces, so these controls do not claim a new raw-byte extraction verification.

| Control | Queries | Candidates old → new | Exact duplicate windows old → new | Summed first-20 preview bytes old → new | Summed first-20 distinct-page counts old → new |
|---|---:|---:|---:|---:|---:|
| Albert-2013 | 18 | 97 → 86 | 4 → 0 | 15,711 → 15,817 | 14 → 14 |
| DAPA-HF | 24 | 274 → 259 | 5 → 0 | 74,096 → 74,856 | 78 → 80 |

No control query loses first-20 page diversity; two DAPA-HF queries gain a page. The summed page counts are query-level counts, not unique corpus pages or an accuracy denominator. Synthetic contrast tests also keep identical text on separate pages and in separate Source versions separate, preserve widely separated local clusters through cursor traversal, and preserve oversized recovery.

[All control-query measurements](code-controls.json) and [Source projection bindings](control-source-bindings.json) accompany this report.

## Validation and preserved failures

47 affected search/candidate/cursor/Domain-boundary tests and one additional historical-recipe receipt compatibility test pass; changed-file Ruff/type checks and CI-equivalent formatting checks pass. Four earlier test assertions assumed separate anchors on a tiny page should create duplicate delivered windows. Their fixtures now use genuinely separated windows when testing cursor traversal; the short-page scenario instead checks grouping and both anchors in the literal quote. The initial failures and refined runs remain private and preserved. The historical-receipt fixture initially wrote JSON as SQLite text rather than the required BLOB; correcting the fixture encoding made the compatibility check pass.

An initial control checker incorrectly required the whole original match-bearing line to fit a new preview, although the original recipe already clipped long lines. The corrected checker compares the actual original literal window, full oversized recovery bounds, and exact match anchors independently. Its failed script/log remain preserved; no scientific data or case inputs were changed.

The prior review packet and all 71 frozen diagnostic output hashes were verified unchanged. This report is separately sealed. Full benchmark remains off.
