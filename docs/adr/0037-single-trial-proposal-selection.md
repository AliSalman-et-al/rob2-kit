# Submit one Trial selection with its scientific reasoning

Status: accepted

## Context

The v0.10 proposal input mirrors two internal records in three public collections: complete Results, missing Results and reasoning assessments. The same Trial ID, scope explanation and selected citations are repeated. Actual EMPEROR requests extracted the HR/CI but supplied prose in evidence fields, repeated selected handles as advanced Evidence objects and placed unresolved candidate facts into a second Result. Explicit source scope remained unestablished; these construction failures cannot be solved by declaring exactness from the estimate.

## Decision

The v0.11 MCP operation is `validate_proposal(selections, expected_revision)`. Each Trial selection contains an explicit relation, one complete candidate or null with grounded missing facts, scope rationale, population rationale, one general source-passage list, unknowns and counterclaims. It has no separate assessment array or evidence-basis list. Candidate-specific design citations and advanced numerical proofs remain explicit. The server copies the selection's scope rationale and source citations into the existing canonical Result and reasoning representations; it does not infer their scientific correctness.

The candidate retains independently supplied target measurement/window/comparison and reported endpoint/population/quantitative tuple. Exactness and all eight clarity facets remain caller assertions checked by existing gates. Missing measurements, scope relation, source units, design and unavailable facts are never invented. Unknowns about a complete candidate are not another missing Result.

The public Result/MissingResult input models are replaced, not retained as aliases. Raw v0.10 requests are rejected. Package and generated contract versions advance to v0.11. Canonical storage, identities, source binding, Proposal Review, reasoning receipt/save, deterministic judgments and historical bundle semantics remain intact. Scientific repair paths and scope-review projections retain their canonical scientific field vocabulary; they are not instructions to submit canonical records.

## Consequences

Hosts construct one scientific choice rather than coordinate duplicate record collections. Some source citations apply jointly to selection and reasoning; the host explicitly chooses this shared set. Design-specific attribution remains separate. Exactness still costs eight declarations because no numeric extraction establishes the missing scientific facets. Source quantities still require faithful strings; the server does not repair numeric objects or convert unknown-field dictionaries into scientific assertions.

This reduces input obligations and branch-placement ambiguity, not model calls or guaranteed accuracy. The declaration includes fuller field descriptions and is slightly larger than the prior declaration; schema bytes are not inference usage. Existing hosts must use the new shape. Canonical historical verification does not require keeping old public input contracts alive.

This amends the proposal input portion of ADR0031; ADR0030's researcher gate and ADR0036's atomic Domain submission and separate proposal validation/save remain in force.

## Source labels and population correspondence

`candidate.reported_outcome` is the existing raw quantitative-anchor endpoint label and `candidate.precision` preserves the source interval expression. Interpreted equivalence and separately sourced endpoint criteria belong in scope rationale, not a second raw-label field. Target measurement/window and analysis-population reasoning remain interpreted prose. Binding failure establishes a missing literal proof, not incorrect scientific meaning. Repair details name the public fields while canonical paths remain unchanged.

With no baseline subgroup the target is all randomized participants in the Trial. Enrollment eligibility alone does not make an all-randomized analysis narrower than that Trial target. External generalizability is separate; a broader population target must be explicitly established. The server does not infer the scope relation.
