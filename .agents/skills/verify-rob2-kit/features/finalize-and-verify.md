# Close, finalize and verify

The host reviews and closes each trial, then finalizes the batch into a
deterministic `.rob2.zip` bundle. Anyone can verify the bundle with
`rob2 verify` or with the dependency-free `scripts/verify_bundle.py`. Source
bytes can be archived and verified separately.

## Sub-features

- `review-close` runs `review_trial`, then `close_trial` with its `review_reference`, for each trial.
- `dispositions` ends each trial as `assessed`, `needs_input`, `unsupported_design` or `failed`.
- `finalize` is `finalize_batch`, which returns `data.artifact.path` and `data.assessment_summary`.
- `verify` checks a bundle with `rob2 verify <bundle>` and `python scripts/verify_bundle.py <bundle>`.
- `tamper` makes any change to `canonical.json` (even a rehashed one) fail both verifiers.
- `archive` covers `rob2 archive-sources --output <zip>` and `rob2 verify-sources <zip>`.

## How to get to it (user POV)

- The host calls the close and finalize tools when `next_action` names them.
- The researcher runs `rob2 verify`, `rob2 archive-sources` and `rob2 verify-sources` in a terminal.

## Driving it with the e2e Agent

Preconditions: every domain is saved, or the trial reached a terminal disposition.

- **Close.** Run `agent.close_trials()`. Afterwards, `next_action` is `finalize_batch`.
- **Finalize.** Run `agent.finalize()`. `assessment_summary["prevent-tia"]["overall"] == "low"`, and `get_status` reports phase `finalized`.
- **Verify.** `rob2(ws, "verify", str(bundle)).returncode == 0`, and the standalone verifier prints `bundle verified`.
- **Tamper.** Rewrite one judgment in a copy of the bundle's `canonical.json`. Both verifiers must exit non-zero. See `tests/e2e/test_high_risk.py`.
- **Archive.** `rob2(ws, "archive-sources", "--output", "s.zip")` succeeds, and `verify-sources` passes. After a source byte changes, `verify-sources` fails with `changed == 1`.

All of this is `drive.py assess`.

## Gotchas

- Bundles exclude source files. The archive is the only copy of the source bytes.
- A bundle produced under a different scientific pack fails with `scientific pack descriptor differs`. That is intended.
