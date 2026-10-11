# Render the Assessment report beside the bundle, not inside it

Date: 2026-10-11

Status: Accepted

## Context

Finalized bundles carried a `report.html` bound into the bundle identity
(`report_format: rob2-kit.human-report.v1`). Both verifiers had to regenerate it
byte for byte, so the dependency-free `scripts/verify_bundle.py` carried its own
HTML renderer. That report printed the approved Result and claims largely as
JSON, which a reviewer cannot use, and every layout change would have been a
bundle-format migration in two verifiers.

Reviewers need a readable record. They need every signalling question's answer
beside the assessor's justification and quoted Evidence, plus a Batch summary
of Domain and Overall judgments.

## Decision

New bundles carry `report_format: "none"` and no `report.html`. Both verifiers
reject a `report.html` in such a bundle. Earlier bundles keep their own report
and verify exactly as before.

The **Assessment report** is rendered from a bundle only after that bundle
verifies. It is a folder holding a Batch page (`index.html`) and one Trial page
per Trial. `finalize_batch` writes it to
`<workspace>/reports/<finalization date>-<short bundle id>/` and returns its
path. `rob2 report BUNDLE` renders it again anywhere. A rendering failure never
fails finalization. The report records which bundle it was rendered from, and
it has no integrity of its own.

## Consequences

- The bundle is pure record: canonical JSON, claims, Evidence, images and hashes.
- Report presentation can change without a bundle-format version or verifier changes.
- A report's content is trustworthy only through the bundle it names. Verify the bundle, not the page.
- The renderer reads only current-format bundles (those with a report-format
  marker). Older bundles verify, but `rob2 report` declines to render them.
