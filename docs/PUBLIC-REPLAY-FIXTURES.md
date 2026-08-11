# Public replay fixtures

Issue #97's deterministic replay seam lives under
`tests/public_fixtures/dossier/` and `tests/public_fixtures/traces/`.

`dossier/manifest.json` names one synthetic AURORA Trial, its result-bearing
full text, protocol, SAP, supplement, registry projection, and evidence
snippets. The manifest also names the ten adversarial overlays and ten prompt
families used by cross-Harness tests. Overlay files are source data, never
instructions to a Harness.

Normalized traces are semantic records, not host transcripts. They retain
ordered tool calls, semantic arguments, response classes, state, next action,
Workflow events, checkpoints, identities, integrity, and usage signals. The
normalizer replaces volatile paths, tokens, cursors, timestamps, and generated
artifact/event IDs with stable handles while preserving call order and
scientific Trial/Result identities.

Raw commercial-host transcripts and credentials are intentionally not stored in
the repository. Golden fixtures are compared by focused tests but never
rewritten automatically. To accept a deliberate local change, call
`accept_golden(..., accept=True)` or run the local helper with `--accept`;
inspect the semantic diff before committing it.

## Bounded blinded-verifier experiment

`tests/public_fixtures/verifier/source-conflict.json` is the public, model-free
comparison fixture for issue #112. It supplies only frozen scope, Evidence,
Guidance, and the decision need to the initial verifier context. Its scripted
replies make verifier-present and verifier-absent records reproducible without
network access, credentials, paid calls, or a claim of independent human review.

Trigger policy `blinded-verifier-experiment:1` admits only a valid
No-information basis, a pivotal Source conflict, a pivotal probabilistic
inference with counter-evidence, pivotal Visual or Derived-fact dependence, or
a hotspot named by a versioned policy. Confidence, adverse judgment alone,
Domain number, missing evidence, and validation failures are recorded inputs
but never triggers. One evidence-linked reconsideration is the maximum;
unresolved material disagreement yields a diagnostic Result. If isolated
execution is unavailable or fails, the valid single-assessor baseline remains
the outcome of record and the experiment records the failure.

Decision: **defer** enabling or shipping a standing verifier. The deterministic
fixture establishes the experimental contract and measurement fields (type and
impact of disagreement, evidence effect, calls, tokens, latency, failures, and
repair turns), but no real-corpus owner evaluation has established that the
benefit justifies cost and complexity. This experiment is not a release gate;
the baseline stays unchanged unless the owner explicitly changes scope after
the private evaluation.
