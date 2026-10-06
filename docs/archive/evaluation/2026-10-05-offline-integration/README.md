# Offline integration qualification

The single comprehensive pass at `b09fb0f16f7bc45f0535d1599080a175c428d525`
returned **1,548 passed, 29 failed, 8 skipped** in 2,263.73 seconds. It used two
workers and the existing shared test environment. No paid inference, benchmark,
network-dependent evaluation, or second comprehensive pass was run. The original
log and JUnit report are preserved compressed, with hashes and a per-test failure
and skip inventory in this directory.

## Repairs and classification

- Fifteen failures came from stale release metadata: the verifier expected 19
  tools while the current contract has 20, and the checked manifest retained old
  schema hashes after adjudication/context changes. Updated the explicit catalog
  and regenerated the manifest. These failures blocked actual stdio preflight,
  not merely a snapshot assertion.
- The observation importer omitted `request_companion_source` from its recognized
  public operations. Added it while preserving the historical operation names.
- Eight finalization failures came from two new-field expectations and six
  synthetic historical conversions. The conversions now remove newer decision
  contracts/provenance and checkpoint/receipt decision markers, recompute the
  historical identities, and consistently rebind lineage and driver references.
  Both verifiers retain their rejection rules and exact historical pack pins.
- The remaining five failures were outdated fixtures or expectations: an
  assessed-review unit fixture omitted its snapshot; a closed input-schema
  assertion omitted optional adjudication; the scientific-pack hash assertion
  pinned old guidance; the composite reference assertion pinned superseded
  wording; and the count-review assertion expected deferred detailed data in a
  compact overview. The latter now explicitly requests the D3 detail view and
  still checks unchanged source-bound arithmetic and retry behavior.
- The exact CI format/type scope also exposed two formatting issues and five
  inference errors in the adjudication test dictionary. Formatted the files and
  annotated that dictionary. Scientific content/hash did not change.

The first focused contract/workflow rerun returned **129 passed, 3 skipped** in
21.79 seconds. The complete finalization file then returned **28 passed, 2 failed**
in 207.53 seconds; the two remaining failures located stale historical receipt
driver identities and were repaired with a focused two-test rerun. Final outcomes
are recorded in `validation.json`: **2 passed** in 28.23 seconds. A further
**14 passed** in 30.73 seconds qualified the corrected policy description and
conditional aggregation. The final rebuilt installed wheel passed offline
verification. This is not a claim that a second full suite passed.

## Inputs and platform limits

The eight existing skips were explicit: three Windows-only boundary tests, one
missing historical `8fa90ed` commit, two tests requiring missing historical
`d552804`, retained campaign logs unavailable, and an optional undistributed live
CHAARTED transcript. No new skip or blanket exclusion was introduced. Missing
historical inputs limit those checks, not current public-contract verification.

The wheel was built from the offline cache. Installed-wheel verification used
`UV_OFFLINE=1` and removed `PYTHONPATH` so subprocesses could not import the source
checkout accidentally. This complements the suite's archive/packaging tests.

## Current defaults versus optional routes

| Route | Ordinary behavior | Explicit optional behavior |
| --- | --- | --- |
| Scientific context | `current`, including D2/D3/D4/D5 corrections and exact assessment target/reported Result | `official_d3_prototype` replaces D3 operational context; continuation freezes its selected profile |
| Overall risk | Any High gives High; otherwise any concerns gives Some concerns; all Low gives Low | Bound cumulative concerns may adopt High when confidence is substantially lowered; omission remains valid |
| Domain decision | Deterministic proposal is adopted and exposed in context/review/export | Evidence-bound adjudication may adopt a different judgment for unchanged answers; no automatic prose inference |
| Working notes | Existing checkpoint notes and inline source-linked observations remain available | Typed `result_account` is an experimental replacement for overlapping notes/premises/drafts; account-first prompts are diagnostic-only |
| Domain Evidence | Approved/saved Evidence retained; `include_candidates=false` | Explicit true includes discovery/carry-forward candidates |
| Draft references | Structured Evidence bases supported | Lean text/visual references use existing source selectors; not a new required premise layer |
| Registry PDFs | Omission follows `sources.toml`; configured default is false | Explicit `acquire_registry_documents=true` enables document acquisition for selected Trials; ordinary registry text capture is distinct |
| Companion source | Existing Sources and bounded unknowns can support continued assessment | Explicit source-located handoff; acquisition/staging uses a fresh workspace, with no automatic active admission |
| Separate factual check | Outside the ordinary assessment loop | Explicit advisory exporter/source check; findings do not automatically revise labels |
| Source delivery | Coverage interval union compacts presentation while retaining raw receipts; rendered images use native image content | Rendering remains an available assessment action, not a universal requirement |

These optional routes remain present. None was deleted or promoted in this
integration repair. Conditional overall aggregation and corrected `current`
guidance **do change defaults**; they must not be described as inactive
experiments. Historical aggregation stays verification-only. Prototype prompt
experiments in diagnostic scripts do not replace production context by default.

## Scientific interpretation

The default-route inventory found a stale model-facing `review_trial` description:
it still stated the former automatic two-concern escalation, contradicting the
implemented conditional policy. Corrected that source description and regenerated
the contract. Exhaustive conditional aggregation and release delivery were
rechecked; no algorithm changed. The scientific pack remains `2019.1`, operational
guidance `1.0.14`, with its unchanged recorded content hash.

This checkpoint repairs integration and release fidelity. It does not alter
signalling mappings, relabel a clinical case, or establish model benefit. The D5
eligibility/separate-domain corrections and the AVATAR assessor/source-accounting
qualifications retain their separate source audits and limitations. A matched
corpus accuracy gain is not claimed.
