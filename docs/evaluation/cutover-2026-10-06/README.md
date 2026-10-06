# Final cutover operational test

Exactly ten cases were selected without replacement from the original Code benchmark106-case
OUTCOMES manifest using OS entropy frozen before selection. The full eligible manifest, seed,
algorithm and ordered sample are retained here. No exclusions, redraws or replacements.
This tests operational readiness, not clinical accuracy, and includes development-exposed cases.
The candidate, inputs, model profile, source boundaries, case outcomes and recovery strata
will be frozen and reported before merge. Historical diagnostics remain in `docs/archive/`.

The all-domain official guidance core is implemented. Current production code is
checkpoint `98f3ea7`; its fresh installed wheel passed release verification for all
five Domain projections. See `guidance-audit.md`, `experiment-disposition.md` and
`package-audit-receipt.json`. Independent content, prose/schema, architecture and protocol reviews closed at
`3c6660d`. The complete replacement regression at `f4912d8` ended with 14 failed,
1,629 passed and 8 skipped; all 14 failures now have passing focused followups.
`regression-failure-review.json` preserves classifications and followup strata.
There is no single full-suite green claim. The exact-head focused cohort passed 14/14; the unchanged installed runtime
and all ten final input/profile preflights passed. See `focused-closure-receipt.json`
and `final-medium-freeze.json`. One clean aggregate suite is still running, and its
green result is required before merge. Two final Medium cases have launched; see `first-medium-launch-receipt.json` and
`first-medium-proposal-completion.json`. Earlier Low pilots remain superseded
development evidence.
`execution-protocol.md` defines prospective run/reporting rules, not gate closure.

Albert’s first Medium workflow saved all five Domains and closed the Trial, then
failed bundle finalization on a retired basis-label/modality invariant. The
current-pack verifier fix passes four focused roundtrip/tamper/history checks
and an unpaid clone passes both verifiers. New case launches are held for
review, installed verification and an amended version-stratum freeze; see
`verifier-uniform-basis-recovery.json`. SUSTAIN’s original idle continuation is
retained and its same-session technical recovery is active. No successful
first-attempt completion or accuracy gain is claimed.
