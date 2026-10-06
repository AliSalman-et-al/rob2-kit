# Agent companion evidence acquisition: demonstrated mid-assessment boundary

**MONALEESA-3 demonstrates a real source-availability gap, but the current native
handoff cannot resolve it inside the active assessment.** The official SAP is
publicly reachable and the Code trace delivered its exact registry filename;
the PDF was not among captured Sources. This cycle verifies the boundary and
clarifies the agent's existing initial-intake acquisition option. It does not
ship in-place admission or claim improved RoB accuracy. No model calls or
benchmark were run. The contrastive-prompt hypothesis is closed for now: no
adoption and no further same-mechanism paid tests; the earlier missingness
architecture audit was not repeated.

## Actual Code case and public document

The original October 1 Code benchmark case is
`benchmark-luna6-medium-2026-10-01/cases/monaleesa-3`, not an older main-repository
evaluation. Its approved Result is the first investigator/local PFS comparison,
all 726 randomized (484/242), November 3, 2017 cutoff and HR 0.593
(95% CI 0.480–0.732). Its captured inventory contains only the article and registry.
The exact registry filename observations `Prot_002.pdf` and `SAP_003.pdf` were
delivered by `read_pages` in turn-1 item_10, JSONL line 22. Accepted D5 warrants
explicitly say the applicable plan was unavailable and retain unknown eligible
measurements, analyses and access chronology. `Code-case-evidence.json` preserves
actual target/source/warrant metadata and archive/log/article hashes. This is a
historical inventory gap, not a failed historical call to the later companion
tool, and not proof the NI judgments are incorrect.

A bounded current fetch through the existing companion acquisition code obtained
[the official NCT02422615 SAP](https://cdn.clinicaltrials.gov/large-docs/15/NCT02422615/SAP_003.pdf):
106 physical pages, 2,238,633 bytes, SHA256
2316b7d597d691f59c6eb97e8192ff5f868511f0dc0057ae10300c1098f8b583.
It matches the earlier augmented-corpus document hash. Literal NCT mentions are
recorded on pages 1/30; the current companion identity parser leaves applicability
unverified. The document includes later and embedded earlier material. Cover,
upload/capture dates, matching identifiers and plan text do not establish
prespecification or actual conduct for the selected 2017 Result. Full PDF/text is
private; `bounded-public-access.json` publishes only provenance/identity metadata.

The prior augmented MONALEESA experiment genuinely used new plan methods, but
independent review found timing overstatements. It is source-availability evidence,
not a matched old-corpus accuracy gain. Earlier STOPDAPT-2, TESTING, Kang RECOVERY,
Guitton and CANVAS audits already inspected planning material; their unresolved
answers cannot be explained by a blanket missing-source assumption. Allsop had
no located plan and remains a different, unverified availability situation.

## Current native and host path, exercised without a model

A separate prospective fixture reused the exact Code article and explicitly
identified October 4 registry bytes with their true recorded capture timestamp.
It is **not** October 1 registry replay. Default acquisition was disabled.

1. Native `prepare_batch` admitted the article and registry. The model-facing
   `read_pages` path exposed the SAP filename.
2. Native `request_companion_source` accepted that page-bound registry reference,
   retained an immutable request and returned host handoff arguments. No fetch,
   PDF admission or PDF reading occurred; canonical state stayed unchanged.
3. Native `prepare_batch` with acquisition changed to true rejected the existing
   Batch and required a fresh prospective workspace, even before Proposal save.
4. The existing bounded fetcher obtained one exact cited public PDF (no crawl,
   credentials, DOI guessing or bypass). Host staging reused those fetched bytes
   without a second fetch, validated the reference, and created a fresh dossier.
   Its receipt correctly stated staged=true, admitted=false, read=false.
5. Explicit **host** workspace routing plus new native intake admitted the
   candidate/capture record as Other Sources. The two original Source IDs, bytes
   and projections remained identical in this replay-controlled fixture. Native
   page delivery of candidate pages 1/30 succeeded. This is operator source
   delivery, not model reading/comprehension or an approved Result/answer import.

`summary.json` and `prospective-admission-summary.json` keep these states separate.
Original Code files and original fixture canonical state remained unchanged. An
initial fixture declaration error was preserved and corrected in a fresh fixture;
no model inference occurred. Private native receipts, code and PDF are under
`diagnostics/companion-native-audit-20261005`.

## Small change shipped and remaining user/agent limitation

The native `prepare_batch` tool description and packaged assessment skill now
make the acquisition decision visible **before** the first capture. The assessing
agent can elect the existing `acquire_registry_documents=true` option for exact
named Trials when plan evidence is relevant, without an operator rebuilding that
initial dossier. Omission still respects the dossier setting; no acquisition
or scientific defaults changed. A registry filename is explicitly distinguished
from a captured PDF. Current capture is distinguished from historical replay,
and content/applicability reading from upload/cover chronology.

This is an actionable description of an existing agent-usable capability, not a
new mid-assessment acquisition API or demonstrated change in model behavior.
Mid-assessment requests still depend on host staging and workspace routing. The
patch does not falsely present a handoff as fetched/admitted/read evidence.
The generated public contract was refreshed; every input/output schema hash
remains unchanged.

## Why no in-place insertion was added

The existing Batch and Trial identities cover their complete Source inventory.
Appending Sources changes the Batch identity, not just one page cache. Search
receipts validate the current Batch identity (`evidence.py`); Domain context
views/delivery are Batch-keyed (`domains.py`); working checkpoints bind the Trial
Source set (`working.py`); bundle verification checks search-account Batch
bindings and immutable Batch/Trial digests (`finalization.py`, `verify_bundle.py`).
Historical answer/warrant records can therefore carry the prior inventory basis.
Simply replacing the Batch would invalidate unrelated Trials' search/context
bindings and can make historical exported accounts fail validation.

Conversely, Trial review currency currently binds Result/checkpoints rather than
the source inventory (`trials.py:_review_payload`). A source insertion without an
explicit target-Trial review invalidation could leave a review apparently current
although the newly admitted material was never considered. Source archive format
and origin/role/provenance semantics must also remain coherent. These are concrete
cross-layer obligations, not a reason to coerce answers or reset all Domains.
A fetch wrapper, unowned PDF text in a tool response, copied answer history in a
fresh workspace or silently redirected server root would not solve them safely.

## Minimal coherent route and admission design boundary

The supported route today is a fresh prospective dossier using the existing
source-bound companion request, bounded acquisition/staging, normal intake,
Proposal Review and reading/Evidence selection. The current host must route the
agent to it; this remaining boundary is explicit. Prefer a target-Trial-only
prospective assessment so other Trials and original histories stay untouched.
Before treating it as the captured corpus plus one document, inspect the staging
transfer receipt and require exact retained registry replay/no refresh. It can
warn of missing captured bytes, changed inputs or live registry refresh. Copying
input alone does not guarantee original captured-corpus preservation. Capture a
Source archive while original bytes are available; archived benchmark ledgers
without those bytes cannot be reconstructed by silently fetching current data.
The demonstrated four-source fixture satisfies the preservation check, not every
possible staging input.

A future agent-usable in-place route needs one coherent versioned source-admission
change, not another request-only wrapper:

- Keep the existing literal-reference, public-host/size/redirect checks. Fetch a
  content-addressed candidate and provenance separately from admission/read status.
  Retain observed identity claims, caller linkage/role hints and applicability
  uncertainty; dates and matching NCT mentions do not supply a RoB answer.
- Admit only to an open named Trial at an exact revision, preserving all prior
  source bytes/projections, Result approvals, answers and relied-on snapshots.
  Archive the old/new Source-inventory versions so old source-bound search and
  answer histories remain independently verifiable in exports.
- Bind source-dependent search/context/working currency per affected Trial/source
  version. Invalidate that Trial's review when new material can require
  reconsideration; retain unaffected Trial reviews and old scientific records.
  Do not change Domain labels or silently substitute an approved Result.
- If source interpretation requires a different Result mapping, use an explicit
  supported researcher review of that changed scope rather than pretending that
  acquisition proves equivalence. Reading and revised evidence-grounded answers
  remain separate assessor actions.

This affects source lineage, currency, scope authority and bundle compatibility
and requires design/contract review plus multi-Trial historical-bundle tests.
It is not safely reduced to a small in-place append this cycle. The report and
bounded workflow proof identify that work; no speculative ledger, new coordinator
or unsafe admission implementation was added.

## Verification and limits

Two existing companion workflow/preservation tests passed. The initial release
check detected stale generated description metadata (1 fail/5 pass); regeneration
preserved all tool schema hashes, then the six release checks passed. Ruff and
diff checks passed. Tests demonstrate structural/source fidelity and workflow
boundaries, not improved scientific accuracy. No paid model calls, benchmark,
source substitution, credential expansion, semantic reviewer or production
acquisition/assessment default change occurred.
