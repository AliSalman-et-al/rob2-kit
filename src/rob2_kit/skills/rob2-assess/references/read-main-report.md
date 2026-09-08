# Read the main report

Read each Trial's main report at two checkpoints:

1. Before choosing its Result and submitting the Proposal.
2. After approval, when that Trial becomes active, before answering its first
   Domain. Recover the approved Result first, then repeat the bounded reading.

Use the same full captured Source for both reads. Both passes
use text only and the same source-order prefix, up to 65,536 UTF-8 bytes of
source text per report per pass, stopping at whole-line boundaries. When the
Source text fits, read all of it.
Proposal Review remains the only researcher gate.

## Read consecutive windows

1. Call `get_status` and check `data.main_report_reading` for the Trial. Use
   `list_sources` to identify the captured main articles when needed.
2. While the Trial's reading status is `required`, call `read_pages` with its
   `trial_id` and `windows` set to the returned `required_ranges`. The server
   computes this bounded batch of prefix windows; do not tally UTF-8 bytes or
   model tokens yourself.
3. If `read_pages` returns nonempty `data.remaining_windows`, call it again
   with the same `trial_id` and `windows` set to that list. Omit `source_id`,
   `pages`, and top-level `start_line`. Repeat until no windows remain, then
   call `get_status` for further required ranges. A partial page remains
   unfinished until its required lines have been returned.
4. Stop the mandatory pass when `get_status` reports `complete` or
   `budget_limited`. At the ceiling, preserve the partial-coverage status and
   unread-range navigation, then continue the workflow.

Preserve exact page and line coordinates for unfinished ranges after an
interruption.

The `read_pages` arguments have this shape; replace the example identifiers
and range with the returned recovery values:

```json
{"trial_id": "fictional_trial", "windows": [{"source_id": "source_from_response", "page": 1, "start_line": 1, "end_line": 40}]}
```

For an independent read using `source_id` and `pages`, split page lists longer
than 10 into separate calls. For recovery, use the returned `windows` and
`remaining_windows` continuation instead.

`read_pages` packs windows into bounded responses and preserves whole lines.
A single line larger than its ordinary transport budget is returned intact.
The transport budget does not change the source-byte ceiling for either pass.

Inspect each returned window. `budget_limited` does not mean the full report was
read. Recorded delivery does not establish comprehension.
If a page has no readable text or is image-only, preserve that limitation.
`read_pages` supplies text; status and Source-list calls remain available during
the pass. Mandatory reading does not render images. Outside those passes, choose
`render_page` for a specific unresolved premise or poor extraction when visual
inspection is needed.
For facts taken from an image, follow
[Use visual Evidence](evidence.md#use-visual-evidence-for-visual-meaning).

If either pass is interrupted before its required prefix is covered, recover the
remaining required ranges before the next scientific save. When no main article
was captured, inspect the available Sources and any Intake conditions. Preserve
the missing report as a limitation rather than a completed reading.
If a repair reports incomplete reading, call `get_status` and read the Trial's
`required_ranges` before resubmitting. Selecting a search hit or an abstract
does not satisfy the required prefix.

`get_domain_context` also returns `reading_recovery`. When its status is
`required`, read its issued windows before answering. When it is
`budget_limited`, its windows navigate omitted text for targeted discovery;
they do not extend the mandatory pass.

Status may omit selected Evidence quotations to keep progress checks compact.
Recover an unfamiliar omitted passage with its `recovery.trial_id` and
`recovery.windows` before using it. An Evidence handle does not establish that
its text remains available in the current context.

## Keep the factual orientation

Identify the design, randomized groups, population and flow, ascertainment,
reported Results, and pointers to a protocol or SAP. Keep the orientation brief:
record useful Source terms beside their page/line references and unresolved
facts. Use these notes to guide targeted searches and recover exact passages.
Answers still need inspected Evidence. Retain useful passages through the
existing Evidence-selection operations.

After the first read, choose the Result. After the second, use the approved
Result to assess the Domains.
Inspect omitted methods, flow, tables, or other relevant passages when they could
resolve a needed premise. Include relevant supplements and plans in that discovery.
The reading ceiling limits the mandatory pass, not later targeted reads or
contradiction checks. A completed pass does not settle every Domain question.

## Recover after a later restart

Call `get_status`, then recover the approved Result, current checkpoint, and
Evidence with `get_domain_context`. Earlier coverage records prove earlier
delivery only. Recover exact passages needed for the current question when
their content is missing or uncertain in the current context.

Base recovery on the available context, not elapsed time or an assumed cache
lifetime. Cached-token accounting does not establish that missing passages are
available. Resume an unfinished read checkpoint, but do not start a complete
report reread for every later Domain.
