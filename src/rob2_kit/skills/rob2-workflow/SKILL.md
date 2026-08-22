---
name: rob2-workflow
description: Run the server-directed RoB 2 workflow from source intake to verified finalization.
---

# RoB 2 workflow

Follow the exact `continuation.operation` returned by verified status or the
last tool receipt. Never infer the next mutation from a phase name. Stop whenever
researcher review is unsatisfied.

## Intake

1. Call `preflight_sources` with the authorized root, alias, and Trial ID.
2. Review every candidate and the materialized registry source. Use
   `inspect_candidate_sources` only when a role or omission is genuinely unclear.
3. Save the complete intake plan. On a later invocation, pass the returned plan
   and acknowledgment unchanged to `capture_batch`.

## Evidence and Result construction

1. Call `list_sources`. Main article and registry come first; protocol, SAP, and
   supplements add context.
2. Search or read pages with `retrieve_evidence`.
3. Prefer `normal_selections`, `quote_selections`, and `table_selections`.
   Manual Unicode offsets are an exceptional fallback. Selected Evidence records
   are returned inline and may be reused directly.
4. For tables, preserve title, population, row axis, column axis, footnotes,
   group labels, units, and denominators. A grade/category is not an arm, and a
   single grade is not a cumulative threshold unless the source says so.
5. Keep the requested target separate from the source-reported endpoint. A
   broader, narrower, component, or related endpoint cannot silently replace it.

Every Result submitted to `save_proposal` needs `provenance` containing:

- `source_reported_outcome` and its relationship to the requested target;
- one field binding for every structured reported atom;
- table axes and cell bindings for table-derived Results.

The server checks values and labels against exact Evidence. Unsupported atoms
must be removed or rebound; do not shorten a quote merely to satisfy validation.
Use the returned `draft_id` and JSON patches to repair a Proposal without
resending the whole document.

## Review, Domains, and finalization

After Proposal review is acknowledged, call `approve_batch` with the exact
Transition and acknowledgment. For each Domain, hand the returned packet to
`rob2-signalling`. The server returns only the current active question wave and
persists prior answers. Commit only the admissibility-audited candidate returned
by validation.

When all Domains are committed, prepare and review the Trial finish. When every
Trial is terminal, call `finalize_batch`. Report the authoritative presentation
and prefer the verified `.rob2.zip` compact archive in the final receipt.

## Public tools

`preflight_sources`, `inspect_candidate_sources`, `save_intake_plan`,
`capture_batch`, `list_sources`, `retrieve_evidence`, `render_page`,
`save_proposal`, `approve_batch`, `validate_domain_judgment`,
`commit_domain_judgment`, `prepare_trial_finish`, `finish_trial`,
`finalize_batch`, and `read_record`.
