# Submit Domain assessments atomically

Status: accepted

## Context

The v0.9 live Domain path required `validate_domain_assessment` followed by
`save_domain_judgment` with the returned revision. Both calls were made by the
same host, with no researcher decision between them. Five Domains therefore
required at least ten submission calls. The separate validation receipt also
created transient live state that did not establish scientific correctness.

## Decision

The v0.10 public MCP contract has one `save_domain_judgment` operation for a
complete Domain draft. The server checks question activation, answer reasoning,
Evidence ownership and provenance, context delivery, correction lineage, and
the official deterministic decision tables before committing at the requested
State revision. A rejected draft leaves canonical assessment state unchanged.

The existing revision transaction is the concurrency boundary: competing
different drafts at one revision cannot both commit. Retrying the identical
accepted draft with its original revision returns the same checkpoint, including
after a lost response and process restart. A changed draft follows the explicit
supersession rules. Proposal validation and Proposal Review retain their separate
roles. Structural validation does not certify the scientific inference.

The public contract and package advance from v0.9 to v0.10. The durable
workspace state shape and scientific bundle semantics do not change. Previously
finalized bundles remain verifiable according to their recorded versions.

This supersedes the live Domain receipt part of ADR 0031 and issue #352; their
Proposal requirements and historical records remain in force.

## Verification

Exercise one-call submission, repairs without mutation, concurrent revisions,
identical retry after restart, correction, complete Trial review and closure,
export, and independent bundle verification through the public lifecycle.
Measure the saved call count against the v0.9 baseline in controlled comparisons
before making any accuracy claim.
