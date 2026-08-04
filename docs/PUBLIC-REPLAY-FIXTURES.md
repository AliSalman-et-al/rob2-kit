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
the repository. A golden file is compared in CI but never rewritten. To accept
a deliberate local change, call `accept_golden(..., accept=True)` or run the
local helper with `--accept`; inspect the semantic diff before committing it.

