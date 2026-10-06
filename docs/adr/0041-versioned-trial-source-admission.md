# Admit cited companions with immutable inventory versions

Status: accepted

## Decision

An approved, open Trial can acquire and explicitly admit one Source-bound public
companion in its current workspace at an exact state revision. Acquisition uses
the existing bounded PDF/DOI fetcher and stages immutable bytes and provenance.
Admission appends the PDF and provenance as Other Sources with
`cited_public_document` origin. Neither step establishes page delivery,
applicability, prespecification, actual conduct or a scientific judgment.

Each admission commits a new immutable Batch and preserves its predecessor in
the existing canonical history. Old Source bytes, IDs, projections, Result and
assessment records remain unchanged. Exports include the exact ordered inventory
versions and admission records; both verifiers authenticate append-only changes
and historical search accounts against their original inventory.

Receipt currency is per Trial: the first Batch in the trailing run of versions
with the current Trial identity. A different Trial's admission preserves this
basis. Target searches, context and working checkpoints require recovery from the
new inventory. Working checkpoints remain disposable. Previously delivered
immutable Source coordinates retain the initial Batch reading basis; they prove
delivery of those exact pages, never inspection of the newly admitted PDF.

A target Trial review binds the new Trial inventory identity. Its old immutable
review becomes non-current; unaffected reviews and closures retain their
bindings. Admission rejects closed Trials and finalized Batches. Signaling
answers, Domain and overall judgments are never rewritten automatically.

## Authority boundary

This extends source availability, not ADR0030's authority. The approved Result
remains fixed. If new evidence changes the Result mapping, the host must surface
the conflict for explicit researcher-authorized scope review; it cannot silently
replace the Result or reuse answers as an assessment of a different Result. A
post-approval Result-revision gate is not introduced by this decision. The
existing fresh Proposal Review workflow is distinct from in-place preservation.

The previous optional request/host staging route remains available before
approval or when a separate prospective dossier is intended. It must not be
represented as preservation of an active assessment.

## Reference recovery

Keep the exact Source citation, including its punctuation, and supply the DOI
identity without sentence punctuation or enclosing citation brackets. A filename
such as `Prot_000.pdf` is not a URL. For a captured ClinicalTrials.gov registry
Source, the existing validated document route is
`https://cdn.clinicaltrials.gov/large-docs/{last two NCT digits}/{NCT ID}/{filename}`.
It requires the captured Trial's matching registry ID and an exact quoted PDF
filename in that registry Source. Arbitrary constructed URLs do not qualify.
Recording a handoff does not fetch, admit or establish applicability of a document;
acquisition still applies the bounded public-host and DOI metadata checks.
