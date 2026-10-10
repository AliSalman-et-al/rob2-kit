# Read the main report

The server requires a bounded, in-order reading pass of each Trial's main report
twice: before you choose its Result, and again when the approved Trial becomes
active, before its first Domain answer. Each pass covers up to 65,536 bytes of
source text. A current working checkpoint saved after the first pass can stand
in for the second pass after approval or a restart.

## Do the pass

1. Call `get_status` and read `data.main_report_reading[trial_id]`. Use
   `list_sources` to see Source roles; a declared `main_article` is the report.
   If no report is identified, inspect the Sources and intake conditions and
   record the limitation.
2. While the status is `required`, call `read_pages` with the Trial's
   `trial_id` and `windows` set to the returned `required_ranges`.
3. If `data.remaining_windows` is not empty, call `read_pages` again with
   `windows` set to that list. Repeat until it is empty, then check `get_status`
   for further ranges.
4. Stop when the status is `complete` or `budget_limited`. `budget_limited`
   means the report was longer than the pass; read the rest where it matters.

`get_domain_context` returns the same requirement as `reading_recovery`; read
its windows when its status is `required`.

## Request shapes

One Source and its pages (`start_line` applies to every page; there is no
top-level `end_line`; at most 10 pages per call):

```json
{"trial_id": "fictional_trial", "source_id": "sh_0123456789abcdef", "pages": [2], "start_line": 10}
```

Independent windows, each with its own Source and line bounds:

```json
{"trial_id": "fictional_trial", "windows": [{"source_id": "sh_0123456789abcdef", "page": 2, "start_line": 10, "end_line": 20}]}
```

Do not combine `source_id`, `pages` or top-level `start_line` with `windows`.
Read the text from `data.pages[].numbered_text` and continue with
`data.remaining_windows` until it is empty.

## What to take from the pass

Note, with page and line references: the design and unit of randomization; the
randomized groups; how allocation was generated and concealed; who was blinded;
the participant flow and analysed numbers; how and by whom outcomes were
measured; the statistical analysis and its population; the reported results;
and references to a protocol, SAP, supplement or registry entry. Use these notes
to decide what else to read. The pass is orientation, not the whole reading:
supplements, protocols, the registry record and the report's later pages still
need reading wherever a Domain question depends on them.
