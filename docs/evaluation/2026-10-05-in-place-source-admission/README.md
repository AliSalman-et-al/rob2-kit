# In-place source admission: offline workflow proof

This change closes the source-admission boundary documented in the preceding
[Code-trace acquisition audit](../2026-10-05-companion-acquisition-audit/README.md).
It does not establish improved scientific judgments or benchmark accuracy.
The [concrete design checkpoint](../2026-10-05-companion-acquisition-audit/admission-design.md)
was committed and pushed before implementation. [ADR0041](../../adr/0041-versioned-trial-source-admission.md)
records the implemented inventory and authority contract.

## Native behavior

For one named approved open Trial, `acquire_companion_source` requires an exact
revision and a Source/page/citation-bound public URL or DOI. It uses the existing
bounded acquisition machinery and stages immutable PDF bytes and provenance.
No Sources, answers or Result mapping are changed. Failed access admits nothing.
`admit_companion_source` requires the staged candidate identity and a current
revision. It appends the PDF and provenance as Other Sources with explicit
`cited_public_document` origin in the same workspace. No server is rerouted and
no assessment or answers are copied into a new workflow. `read_pages` remains a
separate actual page-delivery operation.

Canonical history retains the preceding Batch inventories and exact admission
records. Old Source bytes, IDs, projections, approved Result, Domain records and
snapshots remain unchanged. Both bundle verifiers authenticate append-only
inventory lineage and historical search accounts against their original inventory.
Removing both history fields cannot disguise admitted public Sources as a legacy
bundle. The source-byte archive supports the new explicit origin and retains all
old and new captures.

Receipt currency is per Trial, derived from immutable Batch versions. A target
admission makes its old search receipts and context cursors stale and working notes
unavailable for reuse until reorientation. An unaffected Trial's inventory, review,
search/context basis and working checkpoint remain current. Old reading receipts
continue to describe exact immutable Source coordinates; they never cover the new
PDF. The target's old immutable review becomes non-current and status requests a
fresh Trial review. Closure rejects the old review. Neither admission nor review
silently rewrites a signaling answer, Domain/overall label or Result.

## Real document and failure review

The [real-source proof receipt](real-source-proof.json) uses the previously captured
106-page official MONALEESA SAP, 2,238,633 bytes, SHA-256
`2316b7d597d691f59c6eb97e8192ff5f868511f0dc0057ae10300c1098f8b583`.
It is a neutral approved mechanics fixture carrying real published document bytes,
**not a MONALEESA benchmark reassessment**. Public URL validation and the bounded
fetch path ran against offline `httpx.MockTransport`. No new network or model call
was made. The operator received native page windows 1 and 30. Applicability,
prespecification, historical plan chronology and actual conduct remain unverified;
no dates or identifier mentions establish those facts.

The first attempt exposed an actual continuation defect: status offered closure
merely because an old target review existed. The independent closure check rejected
it as inventory-stale. The failed state and script are preserved privately.
Status now reuses the existing review-currentness check. The proof continued in
that same workspace without reacquisition, dossier rebuilding or copied answers;
it performed a new target review and finalized successfully. Both bundle verifiers
and the source-byte archive verifier passed.

## Tests and limits

Native tests cover acquisition/admission/read separation; exact-revision,
wrong-Trial and closed/finalized rejection before fetch; byte/ID/projection and
scientific-record preservation; target review/cursor/search/working recovery;
a two-Trial unaffected review, search, context, working checkpoint and closure;
historical search-account revisions and exports; candidate-byte tampering; and
rehashed inventory/provenance/review-history tampering in both verifiers.
Existing finalization, bounded-context, reading, search-cache, workspace, authority,
Source-handle, working-checkpoint and release tests provide compatibility checks.
Validation counts are recorded separately after the last checks complete.

This is an explicitly Result-fixed admission route. ADR0030 allows Result mapping
changes only before researcher approval; this change does not create a post-approval
scope-revision gate. If new evidence changes that mapping, the host must surface
the conflict for explicit researcher-authorized scope review. The supported fresh
Proposal Review is distinct from preserving an active assessment. No automatic
label/scope rewrite is allowed, and no scientific suitability claim is inferred
from successful acquisition or mechanical acceptance.

No paid model call or benchmark ran. The earlier contrastive prompt hypothesis
remains closed; no contrastive prompt was adopted. Full benchmark remains off.
