# Optional reasoned Domain adjudication

Official permission was verified directly against the 22 August 2019 PDF,
p.4 and the Domain decision tables. See [ADR 0040](../../adr/0040-reasoned-domain-adjudication.md)
for the exact contract and limits.

The implementation extends atomic Domain save and existing revision/review
patterns. An adjudication is a departure attached to an unchanged saved answer
and Evidence snapshot; it preserves the algorithm's proposal and records the
host's adoption separately. It requires current Result, Domain, checkpoint and
pack identities, selected answer Evidence, an attributed assessor, a material-bias
rationale and explicit source-linked counterevidence. It cannot silently edit
answers, borrow foreign Evidence or reuse a stale parent. Defaults remain
algorithmic. Scientific support is asserted by the host, not proven by validation.

Adopted labels reach Trial review, overall aggregation, canonical export and
final assessment summaries. Evaluator traces remain explicitly proposed-only.
Bounded review summaries retain the departure, avoiding a reviewer-facing loss
that the first integration test exposed. Both verifiers replay domain defaults
and check immutable ancestor bindings. New descriptors enumerate historical
unmarked checkpoints; old bundles and source data are not rewritten. Independent
pack pins now include the prior exact descriptors and current D4.5 guidance hash.

Tests exercise initial deterministic save, explicit adoption in both directions,
unchanged canonical answers/trace/drivers, exact retry, foreign/stale Result,
Domain, rule, checkpoint and Evidence controls, answer changes that discard
adoption, review invalidation, adopted overall labels, visible review/export,
independent semantic checks after checkpoint rehashing, archive tampering and
untouched historical bundles. Synthetic rationale fixtures verify representation
and transport only. Diagnostic counterfactuals recompute the proposal, rather than
inheriting a host adjudication for changed answers.

No paid model calls, full benchmark, gold optimization or production-trial
re-adjudication occurred. No scientific accuracy or agreement gain is claimed.

The inherited composite-guidance caveat is separate: existing delivered D4 cards
and measurement reference do not explicitly supply official p.52 weighting by
component frequency/contribution and the most influential components. Mixed
subjective composites are not automatically High. That qualification is not
silently inferred from this adjudication capability and is not amended here.
