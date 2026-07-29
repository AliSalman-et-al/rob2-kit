# Public-v1 release evidence checklist

`release-gate.toml` is the authoritative one-to-one map from every blocker in
V1-SPEC section 17.2 to automated evidence and named manual checks. CI validates
that map and runs the same package/core checks on Windows, macOS, and Linux.

Automated evidence is necessary but does not declare public v1 ready. Before
issue #27 can close, each manual check must have evidence placed in its named
slot:

- **Real-host Windows:** the release owner links Codex and Claude Code
  Preparation-attempt receipts for the frozen candidate, including normalized
  submissions and ledger results.
- **Keyboard critical flow:** the release owner records completion without a
  pointer device, visible focus, logical focus order, and absence of traps.
- **Screen reader critical flow:** the accessibility reviewer records labels,
  landmarks, status announcements, errors, and the sign-off scope as announced.
- **Zoom and contrast:** the accessibility reviewer records 200% zoom/reflow,
  text and non-text contrast results, and any critical-flow defects.
- **Uncoached lab flow:** the study owner records blockers and dangerous
  misunderstandings from the convenience sample and links retest evidence.
- **Clean install:** the release owner records installation, launch, canonical
  exports, and offline archive verification from the frozen wheel.

Any known defect that prevents the critical workflow, permits a nonhuman
sign-off, exposes a non-loopback boundary, loses work, or dangerously
misrepresents evidence blocks release. Minor friction is recorded as follow-up.
The private `eval/reference/` corpus is never attached to this evidence, and its
judgments are never used as a correctness oracle.
