# Conditional cumulative concerns for overall risk of bias

Status: accepted; supersedes ADR 0035 for new assessments

[Cochrane Handbook §8.2.4 and Table 8.2.b](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08)
allow multiple Some concerns Domains to support High when their combination
substantially reduces confidence in the specific result. Counting Domains alone
omits that condition. This is a rule-fidelity correction, not evidence of improved
Domain accuracy or benchmark agreement.

All five valid Domain judgments are required. All Low proposes Low; any High
produces High; all other vectors propose Some concerns. An optional typed
`cumulative_concerns` assessment in the existing Trial review binds the exact
approved Result identity and ordered five Domain checkpoint identities. For
multiple Some concerns with no High, the host can adopt High only by explicitly
concluding `substantially_lowers_confidence` with a nonblank, result-specific
rationale. `no_escalation`, `unresolved`, and omission remain distinct; the latter
two leave Some concerns without inventing certainty. The host must record an
unresolved assessment's limitation in its rationale. There is no mandatory form,
researcher gate, or selectable count policy for new work.

Snapshots record proposed/adopted labels, applied rule, assessment status,
rationale/basis and algorithm/host attribution under
`rob2-kit.overall.cochrane-conditional.v1`. A changed assessment produces a new
snapshot and review identity. Earlier snapshots remain immutable. A closure
against the old review reference fails. Domain or Result revisions invalidate
review and replace the aggregate's basis; a bound cumulative assessment is not
carried forward. Closed Trials must use the existing reopening workflow first.

Historical snapshots without this marker retain the former count policy
(`rob2-kit.overall.count-policy.v1`) for verification only. New bundle descriptors
bind the conditional contract and explicitly enumerate unmarked historical
snapshot identities and the explicit historical count contract in
`legacy_aggregation_snapshots`. Both verifiers require
that exact enumeration, reject unknown aggregation contracts and mismatched
assessment provenance, and independently replay the adopted judgment. Removing
a snapshot marker without updating its historical provenance fails. The original
historical bundle schema/descriptors remain recognized; no existing record or
bundle is rewritten. Bundle identity detects content changes; it is not an
external signature proving the author's identity.

Sensitivity alternatives in new receipts show the default proposal for a changed
Domain vector. They cannot inherit an assessment bound to another checkpoint set.
Historical alternatives replay their historical rule. Scientific interpretation
of the rationale remains the assessor's responsibility; schema validation does
not prove that the combined concerns substantially lower confidence.
