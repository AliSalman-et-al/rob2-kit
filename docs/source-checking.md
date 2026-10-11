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
reuse diagnostic_evidence_preflight.launch_checked and run_verification_case._run_owned_codex;
freeze research criteria and complete required evidence availability before launch.
Retain actual delivery, effective settings, usage, errors and preservation checks.
Do not impose arbitrary productive caps or claim completeness after a recovery limit.

The packaged optional reference is available via the ordinary guidance tool/resource
and skill export. Omission does not block assessment, Trial review or finalization.
Historical v1 inputs/outputs are not accepted as v2; use their recorded code contract
for interpretation. Preserved invalid reports stay invalid, not retroactive successes.
