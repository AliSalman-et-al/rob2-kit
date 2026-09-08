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
3. Call `get_status` again after reading the returned windows to obtain the
   remaining required ranges. A partial page remains unfinished until its
   required lines have been returned.
4. Stop the mandatory pass when `get_status` reports `complete` or
   `budget_limited`. At the ceiling, preserve the partial-coverage status and
   unread-range navigation, then continue the workflow.

Preserve exact page and line coordinates for unfinished ranges after an
interruption.

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

## Keep the factual orientation

Identify the design, randomized groups, population and flow, ascertainment,
reported Results, and pointers to a protocol or SAP. Keep a brief factual
orientation with source coordinates and unresolved facts. Retain useful passages
through the existing Evidence-selection operations.

After the first read, choose the Result. After the second, use the approved
Result to assess the Domains. Use Source terminology for targeted discovery.
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
