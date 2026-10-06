# Preserve source-bound premise snapshots in native Trial review

The Baillard lean-host pair does not demonstrate contradictory Domain answers.
An appropriate assignment analysis in D2 and missing-data concerns in D3 are
compatible when selected outcomes really were unavailable. Its central defect is
source-to-premise warrant fidelity: incomplete records were promoted to missing
selected outcomes without resolving or sufficiently qualifying that inference.
Minimal can consistently repeat the same unsupported premise across Domains;
Rich acknowledges the unknown and then recasts it as established. Numeric or
word-matching cross-domain consistency gates would miss the first error and could
incorrectly reject scientifically compatible answers.

Offline inspection found one actual information-loss gap in the native route:
`save_domain_judgment` retains a source-bound `working_observation` snapshot on an
Evidence basis, including a referenced account step's inference, uncertainty,
counterevidence and count-Evidence identities. `_review_domain_findings` previously
projected the citation role/identity but dropped that entire snapshot. Trial review
could display the source passage and conclusion while losing the qualified
interpretation that the author had explicitly attached to that same warrant.

The repair copies the already validated snapshot into that basis's review finding.
The existing `ReviewBasisFinding` is now used as the typed public basis rather than
an untyped dictionary and reuses `WorkingObservationLink`. The unchanged snapshot
is displayed as a host assertion, not as a current account revision or a
server-approved scientific fact. This creates no ledger, new assessment action,
semantic detector, answer coercion, critic, review gate or clinical label policy.
It does not make the experimental account-first route a default. Bound source
locations, source-scope meaning, inference, unknowns, counterevidence, step identity,
checkpoint identity and nested count-Evidence mappings remain available together.
The typed receipt may emit nullable defaults; canonical content/identities are
unchanged. Existing review summary/deferred-field recovery still bounds delivery.

## Existing architecture and why it was not duplicated

| Existing mechanism | What it represents | Limit relevant to this task |
|---|---|---|
| `WorkingPremiseRecord` | Host proposition, tentative status, observations, inference, counterevidence and unresolved component | Free-text propositions cannot be equated or adjudicated deterministically; support is not entailment |
| `MissingDataRow` / `MissingDataSemantics` | Randomized, observed, analyzed, excluded and imputed quantities with scope and Evidence | An explicit observed count is host supplied; the server cannot establish that the source supports it |
| `reconcile_missing_data` | Same-scope arithmetic and conflicting typed reports | Never converts analyzed/excluded counts into observed counts; common unsupported assertions can still agree |
| `WorkingResultStep` / `result_account` | Shared editable selected-Result reconstruction with inference, counterevidence, unknowns and existing count rows | Experimental and optional; a wrong common reconstruction can contaminate several answers |
| `WorkingResultStepReference` / `WorkingObservationLink` | Exact relied-on step snapshot in an ordinary Evidence basis | Validates ownership, source intersection and snapshot identity, not the semantic conclusion |
| `account_reconsideration` | Changed or removed relied-on step identities | Does not determine whether the old or revised inference is correct |
| Native Trial review | Source excerpts, warrants, unknowns, typed-count and declared-scope signals | Previously omitted the existing warrant snapshot; repaired here |
| Opt-in source-check packet | Full canonical basis snapshots and original source bindings | Already retains them; no extra critic or packet ledger is needed |

Observation-scope `meaning` already distinguishes reported, inferred and uncertain
interpretation. Account-step `inference` is explicitly separate from the original
observation; unknowns do not require NI and supported probable inferences need no
exact missing count. Count rows likewise do not establish availability from an
analysis denominator. These are useful existing representations. Their presence
cannot prevent a model from ignoring a qualifier or asserting an unsupported
observed count. Deterministic provenance validation cannot safely solve that
semantic problem, and this repair does not claim to solve it.

Review continues to expose the stored proposed/adopted Domain decision separately
from the answers and their warrants. It does not rewrite either proposal or
adoption. Nested count Evidence bindings are retained as mappings; this repair
does not introduce a new automatic expansion of every nested source or certify
its transcription. Existing native source/context recovery remains available.

## Prior negative experiment

The [BeNeDuctus account-first comparison](../2026-10-04-hundscheid-paired-d5/source-audit.md)
found no meaningful scientific benefit, higher operational overhead, and an early
BPD-definition uncertainty retained despite later delivery of discriminating
operational definitions. Neither arm used explicit answer-to-step dependencies,
so it did not test the snapshot route repaired here. That limitation does not
turn the negative comparison into positive evidence. The account remains opt-in;
more structured uncertainty can preserve a stale interpretation rather than
improve reasoning. The earlier Freeman independent source checker also missed
known errors and supplied false assurance; no new critic is added.

The Baillard pair deliberately omitted native working/premise/submission/review
routes. Therefore its failures cannot be attributed to this native review omission,
and the repair cannot be credited with improving those frozen outputs. It is an
independently demonstrated transport loss of existing scientific state, useful
without an accuracy claim.

## Offline controls

A single parametrized native integration test uses four source-backed synthetic
situations with the same analyzed denominator: unknown selected-outcome
availability, all outcomes observed but some omitted from analysis, genuinely
unavailable measurements, and an explicitly qualified inference from monitoring
interruption. The states remain distinct in both D2 and D3 review bases. It checks
exact source locators and snapshot content after typed normalization, preserved
reported/inference qualifications and counterevidence, unchanged canonical Domain
records and proposed/adopted decisions, and no fabricated snapshot on an unlinked
D4 basis. For the qualified-inference case a subsequent account revision must not
silently replace the original answer's relied-on snapshot. No expected clinical
risk labels are encoded in these controls.

Initial controls exposed two fixture/transport assumptions, not semantic failures:
the checkpoint change requires a fresh Domain context, and typed serialization
emits nullable defaults omitted from canonical storage. Both were corrected;
failed logs and temporary workspaces remain preserved. A broad check first named
a nonexistent test file and ran no tests; that attempt is also preserved. Final
validation results are recorded below after execution. No paid calls or benchmark
were launched, and frozen Baillard response bytes remain unchanged.

## Distinct falsifiable next contrast (unexecuted)

The remaining hypothesis is whether retaining already-authored qualification
**at the exact native review basis** helps the original assessor distinguish a
source fact from a supported inference or unsupported promotion. This is narrower
than asking for another account or generic independent reviewer. A future matched
contrast would hold the complete cold source corpus, target, model, native
submission, ordinary guidance and source tools fixed, changing only inclusion of
these existing snapshots in native review delivery. The assessor would use ordinary
review/correction, with no operator rival explanation, preferred answer or
case-specific warning. No shared factual account would be supplied by the operator.

Choose an unexposed Code-benchmark case with real source qualifiers before reading
answers or gold, and freeze discriminating cited and uncited passages. Prespecify
clause-level factual fidelity criteria: whether incomplete record content is
actually reported, whether an outcome-specific availability claim remains
qualified, whether omitted observed data stay distinct from unavailable data,
and whether later contrary evidence is reconciled rather than ignored. Include
qualified probable inference as a positive control; treating every unknown as NI
is a failure. Inspect source warrants before labels, freeze both outputs before
comparison, preserve common-mode errors and false alarms, and report the extra
context length as bundled with content. A single pair cannot establish accuracy
or All-Low superiority. If the assessor never creates a linked snapshot, report
non-exposure rather than claiming the repair worked. This design requires new
explicit paid authorization; none is requested or exercised here.

## Validation outcome

Broader account, Trial review, source-check/export, adopted/proposed decision and
contract recovery checks: **59 passed in 289.64 seconds**. After tightening the
new controls to D2 2.6 and D3 3.1 and omitting absent optional review fields, the
final controls plus contract budget checks: **7 passed in 50.71 seconds** (overlap
with the broader suite; not 66 distinct tests). Scoped Ruff/format and ty pass.
The public contract was regenerated. Frozen Baillard inputs, response bytes and
raw artifact hashes were checked again and remain unchanged. Private attempt
log hashes are retained in `verification.json`; the first fixture failure also
remains in the execution transcript and preserved pytest temporary workspaces.
No additional inference or benchmark runs occurred.

The subsequent [natural-fixture feasibility screen](../2026-10-05-native-review-snapshot-feasibility/README.md)
looks for a cheaper reviewer continuation from already captured state, rather than
purchasing a cold assessment to generate an account. It found only a partial
Chua checkpoint that cannot use normal assessed Trial review. No eligible paid
contrast is ready and no new assessment or terminal state was manufactured.
