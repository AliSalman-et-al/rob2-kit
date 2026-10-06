# Separate scientific Evidence from information limits in MCP submission

The MONARCH-plus trace contained five invalid submissions. The last draft was
accepted offline by repairing only its limitation object's wire shape. The old
MCP input reused the durable DomainAnswer: a three-way tagged union mixed
Evidence roles, lexical search receipts and unresolved information in one bases
array. Putting a limitation at answer level or nesting it under its tag was
repeatedly rejected before scientific validation.

The MCP input now uses DomainSaveAnswer. Its bases contain only selected
Evidence plus an explicit scientific role. Zero-hit receipt handles go in
absence_searches; unresolved propositions and stopping rationales go in
limitations. The server derives their canonical absence/limitation tags and
appends them after the ordered Evidence bases. Counterevidence indexes refer
only to Evidence bases. No Evidence role, answer, scientific inference, missing
count, uncertainty statement or counterpoint text is inferred. Canonical storage,
CLI DomainDrafts, existing evidence identities, branch checks and deterministic
judgments keep their representation. No compatibility aliases accept malformed
use/kind, nested objects, empty citations or invented scientific answers.

This changes the MCP submission interface for callers using absence/limitation
objects in bases. They must use the explicit collections. Evidence-only valid
submissions keep their shape. The release acceptance caller, public contract and
production skill were migrated. Test fixture translation is confined to tests,
which share durable DomainDraft fixtures with application-level checks; it is
not a permissive production adapter.

The five exact failed argument sets are retained as regression fixtures and
remain rejected. Rewriting the last limitation into the new field preserves its
answer, justification, unknowns, selected Evidence identities and explicit
limitation content. Invalid scientific answer values, malformed Evidence,
whitespace information limits, integer counterpoints and invalid counterpoint
indexes remain rejected. A definitive Yes with only a limitation still receives
the existing answer_requires_direct_basis repair. Eight prior scientific/boundary
checks failed initially because the raw test caller still used the retired shape;
after migrating that caller all eight passed. The first negative test also used
a probable fixture answer; it was corrected to exercise definitive Yes.

Validation: 13 submission tests and 5 release tests passed; 45 other domain and
answer-option tests passed plus the eight migrated raw-boundary tests. Source,
test and release typing, focused lint/format and contract regeneration passed.
An attempted test command included a nonexistent test_workflow_models.py and
collected no tests; it was replaced with the actual suites. No paid rerun has
been used to support these structural conclusions. Model completion or scientific
accuracy benefit remains unmeasured at this checkpoint.

## Final named fields after the sole bounded follow-up

At 4dd280d, source-only bases retained their earlier field name kind. The
follow-up still failed: the model used role for scientific Evidence and premise
within limitations. The final public contract adopts those clear names with no
aliases. Source-only MCP callers must also use role now; canonical records keep
kind. The server copies explicit roles and premise text without inferring their
scientific meaning. The unchanged first call passes transport in an offline
control but still receives complete_claim_has_unresolved_premise for definitive
D3.2 No with a declared information limit. No further paid check ran. See the
separated-submission diagnostic for exact usage and retained failures.

## D3.2 scientific correction after the offline control

The initial interpretation of `complete_claim_has_unresolved_premise` as a correct
remaining rejection was too broad. Cochrane Box 8 (full guidance p. 45) asks
whether there is evidence that the result was not biased. Its response set omits
No information; a No identifies lack of reassuring evidence, not proven bias.
The retained MONARCH-plus draft explicitly said that bias was not demonstrated,
and preserved unknown mechanism and incomplete source coverage. Those limits do
not contradict its No at D3.2.

The gate now treats only D3.2 No as a scoped negative evidence claim. It can retain
information limits and cite inspected context or a valid scoped no-hit receipt.
A limitation alone still cannot support the answer. D3.2 Yes and other definitive
missing-data claims still require supporting Evidence and resolved premises.
Receipt validation, source/Trial identity, counterpoint requirements and the
risk algorithm remain active; submitted answers are never changed automatically.

An offline copy of the retained case, after refreshing context for the changed
pack, accepted the exact first separated submission without changing any answer,
justification, unknown, citation role or limitation. The resulting algorithmic
judgment is High (D3.1 NI, D3.2 No, D3.3 NI, D3.4 NI). This is a gate correction,
not evidence of benchmark accuracy or a successful model run. The missing raw
registry source remains unavailable. The earlier failed receipt is preserved;
the new receipt is `2026-10-02-monarch-plus-separated-submission/offline-d32-negative-control.json`.
No paid inference was performed for this correction.

Primary guidance: https://www.cochrane.de/sites/cochrane.de/files/uploads/RoB_2.0_guidance_2019.pdf

Validation: 23 submission tests and 18 input-contract/reasoning tests passed;
`ty check`, Ruff lint/format and `git diff --check` passed. Positive controls
cover inspected context/direct citations; negative controls cover D3.2 Yes,
D3.1/D3.3 No with unresolved premises, unsupported D3.2 No, and invalid Evidence
and SearchReceipt handles. The public wire schema is unchanged.
