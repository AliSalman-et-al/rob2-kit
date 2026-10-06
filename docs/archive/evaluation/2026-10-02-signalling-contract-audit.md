# D2/D3/D5 response and certainty audit

Primary source: Cochrane RoB 2 full guidance, 22 August 2019,
https://www.cochrane.de/sites/cochrane.de/files/uploads/RoB_2.0_guidance_2019.pdf.
Page numbers below are printed document pages. Scope: individually randomized
parallel trials, effect of assignment; the adherence/cluster/crossover variants
are not covered by this pack.

| Questions | Primary pages | Active response set | Meaning relevant to the gate |
| --- | --- | --- | --- |
| D2.1–2.2 | 28 | Y/PY/PN/N/NI | Awareness, not bias itself |
| D2.3 | 28 | Y/PY/PN/N/NI | Trial-context cause must be assessed; unknown cause can be NI |
| D2.4–2.7 | 28–29 | Y/PY/PN/N/NI | Impact, balance and assignment analysis are distinct premises |
| D3.1 | 45 | Y/PY/PN/N/NI | Observed outcome availability, not analysis membership |
| D3.2 | 45 | Y/PY/PN/N | No reassuring evidence does not prove bias |
| D3.3–3.4 | 45–46 | Y/PY/PN/N/NI | Possible versus likely dependence are separate |
| D5.1–5.3 | 63–65 | Y/PY/PN/N/NI | Chronology, eligible alternatives and results-driven selection are separate |

NA is represented by omission of inactive questions. D2/D3 activation matches
Boxes 6/8; D5 questions are unconditional. General guidance p.3 describes firm
versus probable answers and limits NI to situations where a probable response
would be unreasonable. D5 pp.61–62 allows justified inferences from incomplete
plans. Neither supports a universal No-as-absence exemption.

## Boundary findings and changes

The scientific pack, save application, evaluator and standalone verifier already
exclude D3.2 NI. The public input enum contains all five values because one
submission type serves every question; the application checks the selected
question's allowed set before saving. The schema description now names this
constraint explicitly. No answer is converted or silently mapped to No/PN.

Four durable verifier checks (current records and history, in-process and
standalone) still required direct/indirect/contradictory Evidence for all firm
answers. They now share the narrowly scoped D3.2 No exception introduced in
e44162d: verified context/inference or a validated scoped no-hit receipt may
support the scoped negative claim; a limitation alone remains insufficient.
All existing handle, Trial, exact-fragment and receipt checks run first.

The standalone verifier's pinned scientific-pack identity was stale following
the operational guidance update. Its current identity now matches the pack,
while the previous v0.9 descriptor and previous v0.8 descriptor remain accepted
for historical bundles. Archived receipts and canonical `kind` fields are kept.

Seven prior CI failures reflected public-model migration: input schema assertions,
missing descriptions, obsolete examples, and three raw consumers/counterpoint
fixtures. Public tests use Evidence `role` plus separate limits/search receipts;
canonical fixtures and exported records still use `kind`. Counterpoints index
selected Evidence, not information limits. No production compatibility aliases
were added.

## Qualifications

The unresolved-premise gate is a local evidence policy, stricter than Cochrane's
statement that firm responses typically imply firm evidence. `limitations`
identifies a premise needed for that question; secondary unknowns belong in
`unknowns`. The host validates structure and identity, not whether a cited fact
scientifically establishes a premise, whether an unknown is material, or whether
a stopping rationale represents adequate source coverage. Free text does not
prove a contradiction. This audit found no further source-supported blanket
exemption in D2/D3/D5; it does not prove every possible gate decision correct.

No paid inference, full benchmark, merge or source recapture was performed.
No accuracy gain is claimed. Missing raw registry bytes remain unresolved.

Validation: all seven affected CI tests passed after migration; three new export
controls passed with context, inference and scoped absence bases through both
verifiers. Fourteen question-option controls, five D3.2 evaluator/export-option
controls, four D3.2 activation controls, fifteen save-boundary certainty/NI
controls and the pack-identity check passed (49 unique focused checks total).
Ruff lint/format, type checking including the standalone verifier, and diff
checks passed. CI is checked once after push and runs in the background.
