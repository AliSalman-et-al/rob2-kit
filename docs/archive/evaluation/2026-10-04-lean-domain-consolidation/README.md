# Bounded consolidation and opt-in lean Domain submission

No paid calls ran. The implementation uses the existing production judgment
operation, exact source selector, Evidence identity and canonical validator.
It adds no scientific authority or risk-label rule.

[guidance-audit.md](guidance-audit.md) reproduces the exact D5 addition from247db8c,
maps each normative claim to Cochrane22August2019 Box11 pp63–65 (or explicitly
local traceability mechanics), and preserves Bagg's exact Result,5.1warrant,
earlier/later source quotations and actual reading. There is no added chronology
proof gate, forcedNI, or inference of result-driven selection from a difference.
Bagg's NI is defensible; a qualified probable inference may also be defensible.
Under-explanation or incomplete citation coverage does not establish a wrong answer.
The prior paid output remains frozen, and no accuracy gain is claimed.

## Actual implementation

`save_domain_judgment.answers[].bases` now accepts three existing-compatible forms:

```json
[
  "eh_0123456789abcdef",
  {"source_id": "sh_0123456789abcdef", "page": 2, "start_line": 5, "end_line": 9},
  {"evidence": "eh_fedcba9876543210", "role": "context"}
]
```

The first two opt into compact supporting facts. The caller's choice of this form
asserts support; the server records **indirect_support**, without asserting direct
entailment. The existing full citation retains explicit support/context/inference/
contradiction roles and optional annotations. No mode flag, draft tool, fact ledger,
new required answer field or top-level field was introduced.

A small application normalizer resolves text ranges using
`select_text_evidence_by_lines` and the currentTrial Source-handle resolver. It
copies immutable source text, not caller-supplied quotes; repeated ranges share a
per-submission lookup and content identity. Existing selected text is reused by
identity. Selected visual handles retain their render receipt, transcription and
uncertainty; text ranges cannot replace visual inspection or provide a render.
Counterpoints accept the same reference forms and remain neutral context when
not already cited as support. Source resolution does not decide an answer.

The normalizer feeds the **unchanged** DomainDraft validation, activation,
reading-recovery, definitive/probable evidence rules, uncertainty checks, revision
lineage, evaluator and canonical persistence. Justification, unknowns and
counterevidence remain required. Limitations and bounded stopping rationales are
available when an investigation remains unresolved. Invalid references cannot
produce a Domain checkpoint; the selector's existing Trial ownership, projection
integrity and exact page/line bounds still apply. Selection of legitimate passages
may be retained even if a later draft validation fails, as with ordinary separate
selection; no destructive rollback erases inspected Evidence.

Full official question cards and source readers remain unchanged. The lean path
uses no WorkingNote, WorkingScope, premise record or optional observation snapshot
unless the caller separately asks for one. It does not parse trial-specific labels,
assert scientific entailment, manufacture chronology, or force a risk category.

## Scope overlap and consolidation decision

| Layer | Distinct responsibility | Decision |
|---|---|---|
| Canonical Evidence | Exact source text or visual transcription, source/version/coordinates/render provenance | Necessary; one existing content identity, automatically reused |
| Answer warrant and role | Host inference for the exact Result, uncertainty and counterclaims; scientific relationship to citations | Necessary; role is declared once by compact form or explicitly in full citations |
| Inline observation | Optional source-specific interpretation distinct from a multi-source answer warrant | Keep existing functionality; no requirement or scientific-gain claim; same WorkingNote representation |
| Working checkpoint | Resumable draft memory, open questions, unread ranges and source/Result freshness | Keep existing user functionality; not a judgment prerequisite |
| Checkpoint observation link/snapshot | Verifies membership and preserves the exact old interpretation when advisory memory changes | Keep legacy/user functionality; not used by the lean path |
| Scope fields | Optional host distinctions of relation/group/stage/window/population/method/reportedness/uncertainty | Retain compatibility and source-specific annotation capability; no scope inference, label gate, mandatory dimensions or further expansion |
| Inline note Domain/question IDs | Duplicate the containing canonical Domain and answer | **Remove the two auto-copied values**; historical fields remain accepted and unchanged |

The earlier preferred manual checkpoint-copy ceremony is absent. The root skill
no longer implies that facts must first be put into observation metadata before
combining them. Inline capture and resumed notes use one shared durable model,
not separate ledgers. Exact source locators in WorkingNote are retained to avoid
another canonical variant and to preserve multi-source legacy interpretations.
`scope.result_identity` stays optional for interpreting resumed/historical notes;
the normal currentResult binding does not depend on it. Removing public legacy
fields or tools merely to lower counts would break existing functionality.

Both retained paid diagnostics omitted scoped fields. That limits scientific
benefit claims; it does not justify another paid test or additional machinery.
This consolidation preserves their compatibility while removing their obligation
from the ordinary drafting route. No new public action was introduced by those
scope changes, so there was no redundant newly introduced action to delete.

## Measured changes and remaining cost

- Public actions: **18→18**. New top-level or required answer fields: **0**.
- Already selected supporting citation: **2 scalar values→1** (Evidence+role
  become an Evidence string). Full roles remain available when scientifically needed.
- One unselected text passage: **2 actions→1** (select then save become save),
  **7 caller scalar occurrences→4** (selectorTrial/source/page/start/end plus
  Evidence/role become source/page/start/end). Unchanged answer/top-level fields
  are excluded. WithN new passages, removeN separate selection calls; handling
  already-selected passages still needs no selection call.
- New inline annotations omit **2 redundant stored scalar values** each.
- Same Codex adapter schema-only surface: **501,505→503,082 bytes**, +1,577
  (**0.31%**). Judgment input alone: **19,236→20,813 bytes**. The optional union
  increases schema size; no overall prompt/token savings are claimed. Existing
  schema-budget ceilings are unchanged. `surface-cost.json` records the comparison.
- Production code includes one49-line resolver using the existing selector,
  three accepted basis forms and normal canonical conversion. This is additional
  normalization code in exchange for fewer caller actions/fields—not a claim
  that total implementation LOC shrank. Two inline ID-copy lines were deleted.
  No new model class, canonical record type, persistence format or tool was added.

## Offline verification

Neutral native tests cover complete D2,D3,D5 paths with exact source support,
D2Low, D3High and D5Low/Someconcerns according to caller-selected probable/NI
answers. They confirm full official question-card availability, preserved
unknowns/counterpoints, identical source identities/quotes, and no working notes.
They reject fabricated handles/Sources, out-of-range pages/lines, caller-invented
quote fields, missing active answers and unresolved definitive claims. Product
and dependency-free verification pass for finalized lean text/visual bundles.
Legacy scope links/serialization remain covered. These are boundary tests, not
proof that an LLM's clinical interpretation will improve.

The native examples use synthetic source facts, not benchmark gold. The existing
visual test also submits a compact handle, preserving the original host image
receipt/transcription/uncertainty. Public schema/recovery tests retain closed
objects, scientific choices and untouched state on argument errors. Union branch
implementation labels are removed from error paths so users receive field paths.

The 43 distinct focused cases passed; lint, formatting, typing, release verification
and diff checks passed. `validation.json` records the groups and timings.
`offline-native-examples.json` contains the actual passed fixture canonical
answers and source records, including both D5 timing answers.

## Next distinct-case comparison, only after authorization

Use a new source-complete trial with materially relevant plan versions or analysis
populations. Freeze identical exactResult, originalCode source bytes, official
question guidance and review criteria before any inference. A paired comparison
would require explicit authorization for two calls: fresh isolated same-model/
effort sessions, identical source availability/task/reading requirements and
canonical validation, with full citations in one interface and compact references
in the other. No scoped-observation experiment or task instruction to create notes.

The sole treatment is citation construction/reference resolution, not official
wording, label rules, source corpus, answer coaching or evidence budgets. Compare
actual selection/repair calls, caller scalar duplication, complete source-bound
warrants, reconciliation of relevant earlier plans, qualified timing, unknowns and
active-path coverage. Review without gold/model-label agreement as a shortcut.
No benefit follows merely from feature use, fewer calls or matching a reference
label. This turn did not run or authorize that comparison.
