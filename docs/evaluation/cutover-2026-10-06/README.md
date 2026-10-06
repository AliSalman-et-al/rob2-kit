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
`package-audit-receipt.json`. Independent review closure, regression failure review
and immutable final input/build freeze remain pending. No final Medium case has
launched; earlier Low pilots remain superseded development evidence.
`execution-protocol.md` defines prospective run/reporting rules, not gate closure.
