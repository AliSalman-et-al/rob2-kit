# Conditional overall aggregation correction

The former rule escalated every vector with at least two Some concerns Domains
to High. [Cochrane Handbook §8.2.4/Table 8.2.b](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-08)
requires considering how the combination affects confidence in the specific
result. [ADR 0039](../../adr/0039-conditional-cumulative-concerns.md) supersedes
ADR 0035 for new assessments.

New assessments propose Some concerns whenever at least one Domain has Some
concerns and none has High. The existing `review_trial` accepts an optional typed
cumulative assessment bound to the exact Result and ordered five checkpoints.
High requires an explicit substantially-lowers-confidence conclusion and
nonblank rationale. Omitted, unresolved and no-escalation statuses remain
distinct. All-Low and any-High labels cannot be overridden by this input. Receipts
expose proposal, adoption, rule, status, rationale/basis and host attribution.
A changed aggregate produces a new snapshot/review identity; previous snapshots
remain immutable, and stale closure references fail. A Domain revision drops
an assessment bound to the earlier checkpoints. Repeating an identical review
assessment is idempotent.

The conditional contract has its own version, independent of the unchanged
Domain question/decision pack and Result semantics. New bundles explicitly bind
the conditional contract and enumerate historical snapshot identities with their
legacy count contract. Both installed and standalone verifiers replay the proper
rule, validate the host assessment and reject marker/provenance inconsistencies.
Historical bundles are verified without modification. Diagnostic alternatives
use the proposal for changed Domain vectors; they do not transfer the cumulative
assessment to a new basis.

Validation includes all 243 Domain vectors, all 26 eligible multiple-concern
vectors under each of the three host conclusions, invalid/blank policy inputs,
stale Result/checkpoint bindings, synthetic native workflow through finalization,
immutable history, Domain revision invalidation, stale closure rejection,
idempotent retry, both verifier paths, descriptor parity, authentic historical
fixture verification, rehashed marker/policy/rationale/basis/provenance tampering,
bounded review receipts and release manifest checks. Synthetic workflow fixtures
exercise software behavior; they are not clinical benchmark cases.

A broader local run was interrupted after 62 passes and two failures: one read
old in-memory producer code against the concurrently updated standalone verifier;
the other synthetic v0.6 fixture still retained new aggregation metadata. The
historical-schema helper was corrected and both failures passed in the final
focused run. The final relevant focused suites passed 72 distinct tests. The previous checkpoint CI had one
missing-nested-input-description failure with 1,496 tests passing. Descriptions
were added for the affected account and cumulative-assessment fields; all nine
contract-budget/release checks passed (one release check overlaps the earlier
focused suites). Full source/test
type checking, touched-code lint and diff checks passed. No full CI wait, paid
model invocation, benchmark case, full benchmark or merge occurred. Historical
assessment/source files and the frozen Chua control were not changed.

This corrects rule fidelity and provenance. It supplies no measured Domain
accuracy improvement, benchmark agreement gain, or causal claim about model
behavior. A schema-valid host rationale still requires scientific review; bundle
identity provides content integrity, not an external author signature.
