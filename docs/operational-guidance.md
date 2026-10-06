Packaged operational guidance through MCP
========================================

Tools-only clients can read `SKILL.md` and its local reference links through the read-only `read_guidance(document)` tool. Each response includes exact UTF-8 content, a content hash and resolved local links. Resource-capable clients can use `rob2://guidance/SKILL` or `rob2://guidance/<reference basename>` for the same content. This is instruction access, not Trial Source intake or scientific Evidence selection.

The tool reads only documents in the installed rob2-assess skill. It rejects arbitrary filesystem paths and unavailable documents; local links cannot leave that package. Reading guidance preserves canonical assessment and working state. The ordinary typed response contract and read-only annotations apply. The skill describes this route so a host without filesystem reading can follow mandatory reference instructions.

Native diagnostic preparation must test the actual stdio client and enabled-tool configuration: walk the skill's transitive local links, compare returned UTF-8 bytes/hashes with the frozen package, verify every required document is reachable, and freeze the receipts. Check that the root skill is supplied in actual client instructions. Client capability/availability does not establish that a later model consumed a reference; inspect that invocation's native receipts separately. No exhaustive unrelated document reading is imposed on the assessor.

This fixes a general integration defect exposed by a tools-only invocation whose root instructions required a local reference that no enabled interface could read. It adds no scientific rule, default prototype activation, case hint, Source substitution or shell access. The first failed invocation remains immutable; corrected attempts must be separately authorized and versioned.

## Host completion for scoped diagnostics

Use the existing `scripts/run_rsi_case.py`/`workflow_completion.drive` integration
for host-owned completion. Same-session resumes require explicit
`--completion-resumes N` and a shared `--timeout-seconds` budget; default is zero.
A partial assessment additionally takes `--completion-scope FILE`, containing only
`trial_id`, approved `result_identity`, and `domain_ids`. Both experimental routes
must use the same prospective policy. Partial scope completion is not batch
finalization or a scored full benchmark outcome. RSI handoff/runtime/isolation
checks remain required; frozen bespoke diagnostic directories are not RSI ledgers.

Model final text cannot complete actionable canonical work. RSI records a
receipt-based reading-delivery report, preserves every controller turn, and marks
missing usage unknown. Required reading and Domain checkpoints are operational
boundaries; their presence does not certify scientific correctness. See
[evidence and limitations](https://github.com/AliSalman-et-al/rob2-kit/blob/800f4afaadc1b1bb913fa3414b7e91e3b49d33f6/docs/archive/evaluation/2026-10-04-completion-integration/README.md).

Overall aggregation follows [ADR 0039](adr/0039-conditional-cumulative-concerns.md).
Multiple Some concerns propose Some concerns; High requires the optional host
combined-impact assessment for the exact approved Result and five checkpoints.
`review_trial.cumulative_concerns` records a supported escalation, no escalation,
or unresolved combined impact with a rationale. Omission remains valid. Review
receipts expose proposal/adoption and attribution; revised aggregates create new
identities, so a prior closure reference cannot silently bind a different judgment.
Historical bundles retain their count-policy interpretation. This correction
supports rule fidelity and makes no Domain-accuracy or benchmark-gain claim.
