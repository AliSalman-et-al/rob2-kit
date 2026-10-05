# Target-Trial companion admission contract (proposed)

The current Batch identity hashes its entire inventory. Replacing it alone makes
unrelated receipts stale and leaves a previously reviewed target current. The
smallest coherent change is immutable Batch versions in the existing canonical
record/history machinery, with a per-Trial currency basis derived from those
versions. This is not a second assessment or a new generic ledger.

## Native contract

1. `acquire_companion_source(reference, expected_revision)` requires one exact
   named open Trial in an approved assessment and the current revision before any
   network access. It reuses the existing source/page/citation validation and
   bounded public PDF/DOI fetcher. Successful acquisition captures immutable PDF
   bytes and provenance in the current workspace, returns a content-addressed
   candidate identity, and reports staged=true, admitted=false, read=false.
   Failure reports unresolved; it admits nothing. Caller role/linkage, dates and
   registry mentions remain assertions/observations, not applicability findings.
2. `admit_companion_source(trial_id, candidate_identity, expected_revision)` checks
   the candidate's exact captured content/provenance and original cited Source,
   rejects closed/finalized/wrong-Trial/stale calls, and appends the PDF and readable
   provenance as Other Sources. The existing projection/capture machinery fixes
   IDs and coordinates. It commits a new content-addressed Batch and its predecessor
   with existing canonical CAS, without replacing any old Source or scientific
   record. It returns staged=true, admitted=true, read=false and the current Trial
   inventory identity. `read_pages` subsequently establishes actual delivery.

## Version semantics and exports

- State carries ordered prior Batch versions only after the first admission.
  Each version is already a canonical Batch record; canonical exports include
  these same versions and exact admission records. Both verifiers validate hashes,
  append-only Sources, unchanged non-target Trials, and candidate provenance.
  Existing bundles with no admission history retain their existing contract.
- A Trial's receipt currency is the first Batch in the trailing run of versions
  having its current Trial identity. Initially this is the original Batch identity;
  an unaffected Trial keeps that basis across other Trials' admissions. The target
  changes basis. No global cursor migration or copied assessment is required.
- New search receipts and context views use that per-Trial currency. Target old
  search/context receipts are rejected with recovery through a new search/context;
  unaffected receipts remain usable. Historical search accounts are verified
  against their exact archived Batch version, not falsely against today's corpus.
- Working checkpoints already bind the complete Trial Source projection set;
  target checkpoints become stale, unaffected checkpoints stay current. Previously
  delivered text remains recoverable by immutable Source coordinates; admission
  never reports the new PDF as read.
- Target reviews bind the current Trial inventory identity after admission.
  Old reviews remain immutable but cease to be current; unaffected reviews and
  closures remain valid. Finalization checks review inventory currency in both
  verifiers. Domain checkpoints/answers/Result mapping are preserved, never
  automatically rewritten or labelled stale scientific conclusions.

## Scope and tests before readiness

No automatic Result/scope rewrite is introduced. A material mapping change still
requires researcher-authorized Proposal Review through the supported explicit
scope workflow; acquisition does not grant authority to change an approved Result.
An admission cannot reopen a closed Trial. No new arbitrary host, crawl, registry
refresh or external-app access is added.

Offline proofs must cover real captured MONALEESA SAP bytes; exact-revision and
closed-Trial rejection before fetch; acquisition/admission/read separation;
byte/ID/projection/answer preservation; two Trials with an unaffected current
review/search/context/working checkpoint; target review invalidation and recovery;
historical search accounts in both bundle verifiers; old bundles; and tampering
with candidate bytes, provenance, predecessor history and review inventory basis.

Implementation boundary: if a verifier cannot authenticate an older account's
exact inventory or a receipt cannot retain per-Trial currency, the feature stays
unready. A fresh workspace or silently copied answers is not a substitute.
