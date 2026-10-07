# Optional question-level advisory review

The v2 optional advisory reuses canonical answers and ordinary source readers.
It checks material source/guidance issues without changing scientific authority,
adding a model to the server or introducing a closure gate. No scientific accuracy
improvement is established by this contract replacement.

Prepare one or all saved Domains with explicit model settings (omit DOMAIN for all):

```bash
PYTHONPATH=src:. python -m scripts.export_factual_audit WORKSPACE TRIAL DOMAIN \
  --prepare NEW_DIRECTORY \
  --assessor-model ACTUAL_ASSESSOR --assessor-effort low \
  --reviewer-model AUTHORIZED_REVIEWER --reviewer-effort low
```

The packet pairs each saved active question's wording and actual canonical answer
with its complete official elaboration. Full warrants, unknowns, counterevidence,
missing-data semantics, source scopes and original citation roles remain intact.
Entry IDs are exact canonical paths within an answer, bound by claim_id and snapshot;
identical text in separate entries stays distinct. Shared official dependencies
appear once in instructions. Cited spans use one numbered text representation;
raw source text remains recoverable and verified. No human reference label or
expected correction belongs in the input. Saved answers can anchor a reviewer;
this is explicit review of the original reasoning, not a blind reassessment.

The v2 report has format=rob2-kit.source-check.v2, snapshot_identity and questions.
Exactly one row covers each accepted claim_id:

- retain: claim_id/disposition only; no material issue reported, not proof of correctness.
- revise: claim_id/disposition, affected_entries, reason and nonempty references.
- uncertain: claim_id/disposition, bounded reason, affected_entries/references where available.

No exhaustive sentence findings or copied saved clauses are required. Keep existing
legitimate uncertainty and supported probability; do not invent unavailable facts.
Revise locates a material issue for the original assessor, not a replacement answer.
Retain cannot erase unknowns or counterevidence from the canonical assessment.

A bare Evidence identity or read/search passage_ref resolves its exact immutable
selected span. No retyped quote is necessary. {handle, quote} narrows a textual
span only when the quote matches contiguously under ASCII-whitespace collapse;
case, words, numbers, signs and punctuation remain exact. Invented, stale, foreign,
ambiguous and mixed identifiers fail. Selected offsets never widen to page/line
boundaries. An intermediate agent assertion is not Evidence. Existing figure
handles retain authenticated pixels/region and qualified interpretation; a new
region uses the existing authentic VisualEvidenceReference route. Source validity
does not establish semantic support or correctness of a proposed correction.

Validate a separately frozen response (the existing --findings argument names the
response file; its v2 content is question-level):

```bash
PYTHONPATH=src:. python -m scripts.export_factual_audit WORKSPACE TRIAL \
  --packet NEW_DIRECTORY/packet.json --findings NEW_DIRECTORY/response.json
```

Exact packet recomputation, approved Result/checkpoint freshness and accepted-question
coverage protect provenance. The receipt recovers precise affected entries and
source spans, preserving original citation versus follow-up support. It remains
advisory_only=true, semantic_support_verified=false and assessment_mutated=false.
Only the original assessor inspects Sources and accepts/rejects a change through
ordinary canonical Domain submission with revision lineage. There is no apply,
retry, additional ledger or automatic label gate. Closed assessments stay immutable.

Preparation makes zero model calls, supplies six existing read/guidance tools and
records hashes, native output schema and full-page image transport. Complete
captured Sources remain available through readers, search and render; follow
pagination, inspect uncited context and pixels as needed. Availability does not
prove reading. Keep disposable cache/receipt state for validation. No new source
acquisition, default model or paid runner is introduced.

The exporter does not isolate the MCP host. Protect an isolated copy's Sources and
canonical/working files at the OS boundary, allowing only disposable caches to write.
Client read-only mode is insufficient. For any separately authorized paid diagnostic,
reuse diagnostic_evidence_preflight.launch_checked and run_rsi_case._run_owned_codex;
freeze research criteria and complete required evidence availability before launch.
Retain actual delivery, effective settings, usage, errors and preservation checks.
Do not impose arbitrary productive caps or claim completeness after a recovery limit.

The packaged optional reference is available via the ordinary guidance tool/resource
and skill export. Omission does not block assessment, Trial review or finalization.
Historical v1 inputs/outputs are not accepted as v2; use their recorded code contract
for interpretation. Preserved invalid reports stay invalid, not retroactive successes.

## Historical v1 experiments and validation

The following records describe earlier contracts and results, not current v2 instructions.
Their artifacts and failures remain unchanged; none establishes v2 effectiveness.

### Difference from rejected review experiments

The full-claim tool-free feasibility audit had a qualified-inference false alarm,
a wrong corrective line range and pooled support across warrants. The native D4
review exposed all warrants yet missed an unsupported numerical attribution.
Those negative results remain intact; another generic prompt is not evidence of
progress. The concrete repaired capabilities are exact response quote validation,
claim-specific original/follow-up attribution, typed advisory classifications with
uncertainty, current snapshot recomputation, verified visual delivery to the fresh
context and full-source follow-up. They prevent malformed feedback from passing as
source-verified feedback and keep valid-looking false critiques from editing an
assessment. They do not prove that a reviewer will find errors or avoid false alarms.

Reuse: one existing exporter replaces its narrative-only finalized-bundle loop;
current and bundle inputs share one builder. Six existing source/guidance tools, selected
Trial review, Evidence integrity/selection, renderer and native exec are reused.
Zero new MCP tools, canonical record kinds, assessment actions or finalization
gates. The earlier one-off paired collector remains frozen diagnostic provenance;
no duplicate active audit tool or independent assessment ledger is created.

Neutral offline fixtures contrast literal allocation counts with a legitimate
qualified inference from subjective scoring. They test full claim/counterclaim
preservation, metadata blindness, original versus follow-up citations, exact quote
and visual binding, explicit uncertainty, altered snapshot rejection, and immutable
canonical state even after a dubious advisory critique. No benchmark case rule or
risk-label agreement test is used.

### Offline validation at the historical checkpoint

Focused current source-check, immutable bundle export, bounded Trial review and
wire schema checks: **26 passed in 62.98 seconds**. Changed-file lint/format and
scoped source/exporter/new-test type checks passed. Local installed native CLI
help confirms image and structured-output arguments; generated overrides parse as
TOML and the code-mode override is recognized by local feature listing. This is
configuration preparation evidence, not execution of a model or proof that a
provider will honor the output schema. No paid calls were made. Frozen paired run
hashes remained intact (baseline 2,956 and lean 2,961 protected/answer files).

The preceding visual-reference CI had one stale string-only schema assertion
(1 failed / 1,433 passed / 8 skipped in representative macOS 3.13). Its test now
checks the actual handle/text/visual union; that focused check passes. No runtime
contract was weakened to satisfy the obsolete expectation.

The first authorized native launch exposed an invalid native response schema
before producing a review (see `docs/evaluation/2026-10-04-freeman-source-check`).
Preparation now uses `native_review_schema()` rather than raw Pydantic schema:
nullable values must be emitted and the four coordinates use a constrained
homogeneous array. Local validation remains unchanged. Native acceptance of this
repair has not been retested; no scientific reviewer benefit is established.

Technical recovery preflight additionally found Pydantic's nonstandard `ge`
annotation on page. Native projection maps it to `minimum` and uses a conservative
documented keyword profile (local text-length/nonblank checks remain authoritative).
`check_native_review_schema()` checks root/object requirements, closed properties,
required nullable fields, supported vocabulary and local resolved references before
preparation. This is an offline check; provider acceptance must still be observed.

### Freeman experiment closure

The immutable recovery report and original rejection receipt remain in
`docs/evaluation/2026-10-04-freeman-source-check-recovery/`. Their historical
27/27 complete-window rejection was overstrict: 13 references are faithful
contiguous excerpts under whitespace-only comparison. Fourteen do not match
contiguously (including paraphrase, ellipses and omitted source words). Three
findings also join separate saved unknown entries. This contract correction
does not repair the report, endorse its conclusions or change its scientific
misses. No report was sent back to the author and no further review was purchased.
