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
