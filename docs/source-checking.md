# Opt-in source checking of an existing Trial review

This is an advisory source-fidelity path, disabled unless explicitly prepared.
It does not introduce a model into the server, change scientific authority, or
add a closure gate. Official Cochrane guidance and the original assessor remain
authoritative. No paid reviewer behavior has been demonstrated for this version.

Prepare a fresh native request from a current workspace (one Domain or all saved
Domains), with explicit assessor/reviewer identities and settings:

```bash
PYTHONPATH=src:. python -m scripts.export_factual_audit WORKSPACE TRIAL DOMAIN \
  --prepare NEW_DIRECTORY \
  --assessor-model ACTUAL_ASSESSOR --assessor-effort medium \
  --reviewer-model AUTHORIZED_REVIEWER --reviewer-effort medium
```

The existing exporter also reads verified immutable bundles. Both use one shared
packet builder. Current-workspace export reuses selected-Trial review findings to
locate the exact current checkpoint set and the existing Evidence resolver to
recover complete cited material. It does not save a Trial review or require
finalization. A missing or corrupt exact citation fails preparation explicitly.
The packet contains the exact target, reported result, relation, full saved
warrants, unknowns, counterclaims, missing-data descriptions and original citation
roles/bindings. Claims have deterministic opaque IDs. Signalling answers, risk
judgments, driver flags, question IDs and Domain IDs are withheld where those are
metadata. Saved prose is not rewritten; it can itself reveal a question or view.
The private assessor routing map stays in `request.json`, outside model input.

Preparation freezes packet/input/schema/image hashes and emits a fresh native
`codex exec` command, not a resumed session. It makes zero model calls. The five
existing source tools are allowlisted: list, search (single/batch), read, render.
No status, review or assessment-writing tool is supplied. Full captured source
follow-up is possible without curated repair pages, case hints or reference labels.
Original visual receipts/regions/uncertainty stay intact. Verified full-page pixels
are supplied through native image arguments; this transport is recorded distinctly
from a new MCP delivery. Further renders use the existing image-delivering adapter.

Execute only under an explicitly authorized, frozen scientific diagnostic. Reuse
`diagnostic_evidence_preflight.launch_checked` and the existing native runner's
`run_rsi_case._run_owned_codex`, with research criteria and full source availability
manifest frozen before launch. Preserve native events, images, usage, effective
model/effort, stderr, source/code hashes and canonical preservation checks. The
prepared command does not claim that its declared settings were observed at run
time. No new paid runner, default reviewer, retry loop or automatic stage is added.

Validate the frozen structured response locally:

```bash
PYTHONPATH=src:. python -m scripts.export_factual_audit WORKSPACE TRIAL \
  --packet NEW_DIRECTORY/packet.json --findings NEW_DIRECTORY/response.json
```

Findings locate an exact clause in its saved field and classify supported facts,
legitimate inference, narrower support, citation gaps, contradictions or unresolved
support. Each has explicit uncertainty. Every saved claim must be represented,
including retained facts/inferences; that checks report coverage, not scientific
completeness of its conclusions. Non-unresolved findings require source references.
Narrative quotes must equal the complete specified line window. Source ownership,
captured integrity, current Result/checkpoints and unchanged canonical claims are
verified. Visual observations require authentic receipts and retain interpretation
uncertainty; provenance does not certify transcription truth. Claim-specific
original windows are distinguished from follow-up support, which never silently
repairs an original citation. A valid but irrelevant quote can still yield a false
critique: the receipt explicitly does **not** certify semantic support.

The original assessor reads the advisory receipt and routing map, inspects its
sources, and accepts or rejects findings. A warranted change uses the existing
canonical Domain edit/submission path and revision basis. There is no apply
operation, silent correction, historical overwrite, new ledger or finalization
gate. Closed assessments remain immutable.

## Difference from rejected review experiments

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
current and bundle inputs share one builder. Five existing source tools, selected
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

## Offline validation at this checkpoint

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
