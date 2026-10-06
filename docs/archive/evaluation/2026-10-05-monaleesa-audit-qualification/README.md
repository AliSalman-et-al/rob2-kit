# Independent warrant qualification and offline navigation audit

This report qualifies the single development-exposed MONALEESA-3 in-place source-admission diagnostic. It is not a new adjudication, clean October 1 replay, or accuracy estimate. The frozen agent condition, canonical D5 answers, receipts, and [review packet](../2026-10-05-monaleesa-in-place-review/README.md) remain unchanged. No paid retest was performed.

## Scientific qualification

The actual acquire/admit/read capability succeeded. The agent saved PY/N/NI and Some concerns; that combination follows the D5 algorithm correctly.

For 5.1, the warrant incorrectly turns the protocol's future statement “will be unblinded” into an accomplished event and uses patient/investigator blinding as a proxy for analysis-team access. It also treats a July 2018 interior header as proof of a substantive post-publication amendment. Those are chronology and access-warrant defects; PY itself is not disproved. The 2015/June 2017 history and October 2017 amendment history remain valid evidence. Separately recovered SAP physical page 43 explicitly asserts that decisions preceded database lock and unblinding, but this page was not delivered to the agent and must not be credited to its saved warrant.

For 5.2, No has defensible positive reassurance: primary local and supportive central results were both numerically reported, and the central audit sample has a dated methodological rationale. This is more than absence of evidence of selective reporting.

For 5.3, NI remains a defensible conservative answer, but its warrant underweights correspondence between the predesignated primary FAS/Cox analysis and the reported analysis relative to unreported sensitivity results. This does not demonstrate a wrong label and does not justify forcing Probably No. No blanket warning, NI gate, or posthoc label replacement was added.

## What the actual search/navigation trace establishes

The offline audit reads the existing durable search sessions/candidates, immutable page projections, and captured PDF bookmarks. It makes no new searches or model calls. All nine searches had remaining cursors; none was continued. The agent did not call source navigation/list_sources or render_page. The 62 delivered hits were bounded slices of larger retained candidate sets.

In the SAP “analysis plan” search, the embedded cover at physical page 30 was candidate rank 20; page 43 was ranks 181–182, including its assertion at line 17. In “PFS analysis,” page 43 was rank 61. The phrase “primary analysis” did not match “primary PFS analysis.” No SAP search targeted unblinding or database lock. Broad searches delivered multiple windows from common-term pages; some protocol windows were identical despite distinct match anchors. These facts support crowding and unused recovery paths, not dropped or inaccessible pages, nor proof that a ranking change would have caused the agent to read the missing pages.

The existing v0.3 literal source outline already contained page 30 and page 43 entries. The SAP PDF has 144 bookmarks, including cover entries pointing to physical page 30 and “1 Introduction” pointing to physical page 43. The protocol has no PDF bookmarks. Bookmarks are not surfaced by current navigation. Both PDFs also have printed contents pages.

## Small general improvement

The literal heading detector missed section numbers extracted on a separate line immediately before a short title (for example, `1` followed by `Introduction`). It now exposes these adjacent lines as a qualified heading candidate with their exact page/start/end coordinates and literal newline text. This uses the existing navigation path; it does not assign dates or infer prespecification. Navigation version advances to v0.4 because entry offsets can change. Synthetic coverage checks exact coordinates and excludes version/date rows and long prose. Existing navigation tests check bounded delivery, cursor stability, metadata recovery, and furniture handling.

This fixes an observed outline omission. It does not establish the cause of the scientific warrant defect or a behavioral/accuracy gain. Full benchmark remains off.

Validation: 11 local navigation tests passed. Changed-file Ruff and type checks passed. The initial integration check exposed an unchanged response-schema version literal; updating that literal to v0.4 resolved all nine failures. No scientific output was altered. [Offline trace evidence](offline-navigation.json) preserves v0.3 baseline navigation observations. The prior review-packet seal and all frozen raw output hashes were checked unchanged.
