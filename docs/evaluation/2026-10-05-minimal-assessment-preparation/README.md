# Assessment-only scientific scaffolding comparison — preparation only

No paid inference has run. No production defaults changed. This is a falsifiable,
isolated comparison, not a recommendation to adopt minimalism or roll out the
experimental full official guidance route.

Both arms assess all five Domains on the same source-only MCP host. The minimal
arm receives the exact source-grounded diagnostic Result, all 22 signalling questions with options
and activation conditions, and complete applicable official 2019 guidance. The
rich arm additionally receives current local question interpretation rules,
comparison cards, Domain guidance/traps/response framework, and five scientific
references, adapted only for the shared lean interface. The manipulated factor is **additional local scientific scaffolding**.
Both arms omit native intake, Domain save, premise, checkpoint and review tools;
this pair does not isolate the effect of removing the native workflow itself.
The content and its added context length are bundled; this is not a length-matched
pure content experiment.

The common substrate retains native list/search/batch search/read/render/text
selection/visual selection handlers and authentic source receipts. Only workflow
head/next-action metadata and tool descriptions are simplified. Official PDF page
images remain inspectable through one additional tool. Resource access and all
other tools are blocked. Existing typed answers, source resolution, active-question
branching, Domain algorithms and overall default calculation are reused offline.
The response schema accepts answers/rationale/citations/unknowns/counterevidence,
not model-supplied risk labels. Source resolution is followed by the existing bounded canonical Evidence validator,
including handles in counterevidence, checking current-Trial ownership, immutable
Source bytes/projection, and selected Evidence integrity. It does not establish
semantic entailment. Outputs are `computed_proposed_domain_labels` and
`overall_default`; native adjudication/cumulative-concerns review and finalization
are outside this diagnostic.

## Case and matched inputs

Baillard 2006 was selected from the **Code benchmark repository**, before reading
Domain answers or reference labels. Its one captured trial PDF has seven pages;
all source SHA/projection identities match the original capture. Only approved
Result/proposal/intake metadata was recovered. Bausys 2023 was considered first
but excluded because captured registry bytes could not be recovered; no live
registry or reconstructed source substitution was made.

The original Code object is unchanged. Its exact field values are preserved in
`original-approved-result.json` outside git, byte-identical to the earlier v5
approved-Result snapshot. The new `diagnostic-result.json`
fixes the target from the seven-page report: group means of participant minimum
SpO2 during endotracheal intubation, measured by continuous pulse oximetry;
control 81 ± 15% and NIV 93 ± 8% (mean ± SD). Figure 2 shows 57 randomized
(control 28, NIV 29); the report analyzes 53 (26, 27) after two exclusions per
group for lack of exhaustive data. The target remains the assignment effect
in all 57; the reported analysis population is explicitly narrower.

This is not a mean change score. The paper nevertheless calls its primary
endpoint mean drop in the methods. That contrary source wording remains in
both inputs and fully accessible through the tools; the host does not reconcile
it into an endpoint-selection judgment. No old Domain answer, gold label or
host bias interpretation is inserted. This corrected diagnostic scope is not
compared to the original human-label target. `scope-provenance.json` and
`scope-receipts.json` identify the exact line ranges and inspected pixels.

Both arms match Result, source bytes and coordinates, complete source availability,
initial Evidence, empty Domain history, question schema, official guidance,
source tools and image delivery, output schema, evaluator, runtime commit,
model (`gpt-6-luna`), medium reasoning, and isolated CLI version (0.159.0).
Official text includes pages 2–33 and 39–67, including D2 assignment judgment
pages 30–33. Pages 34–38 address adherence effects and are inapplicable to this
assignment-effect Result. Images preserve original tables/layout.

All private inputs, trial and guidance PDF bytes, full prompts and failure
preparations remain outside git. Metadata hashes and offline proof are committed.
The frozen runtime is 9c6c3ae98bd60be613a6d4f687f4684483d0e2eb. The final
private preparation is `minimal-assessment-baillard-v14`; prior preparations
remain intact. `freeze-receipt.json` gives exact prompt/evidence/schema/adapter
hashes and sizes. No authentication or persistent credentials were copied,
created, or expanded. Any authorized future run must use existing normal CLI
authentication.

## Interface adaptation and capacity

`interface-transformations.json` records every changed span before/after. Rich
instructions for unavailable save/preview/companion/premise calls are translated
into rationale/citations/unknowns; inactive-answer retention is replaced by the
shared exact-active-path contract. Empty unavailable count previews are omitted.
Scientific count distinctions, unknowns, censoring semantics, source discovery,
plan applicability/chronology, and uncertainty are retained. No case-specific
bias answer is added. Both prompts state the same lean-contract precedence.

`independent-review.json` checks exact official PDF text parity across all 61
applicable pages and all 22 question wordings/options/activation predicates.
It enumerates 14,130 valid answer combinations across 18 distinct active paths
and checks missing/inactive answers. `review.py` measures exact prompt, actual
tool schemas, output schema, and full trial text with tiktoken 0.12.0 using both
public o200k_base/cl100k_base encodings. These are proxies, not a verified Luna
tokenizer. The local advertised model cache supplies the ordinary 272,000-token
context at 95% effective capacity (258,400); no context expansion is requested.
Explicit planning allowances cover CLI/wire overhead, repeated source interaction,
trial plus selected guidance images, and output/reasoning. This is a context
feasibility check, not a cumulative-input spending cap or proof of useful attention.
Actual usage and context events must still be reviewed after any authorized run.

## Why this differs from previous probes

The October 4 authoritative D3 prototype retained native workflow and submission
layers and covered D3. Its Freeman pair showed no credible improvement. The
October 2–3 tool-free observation contrasts lacked interactive source inspection
and complete formal active branches. This preparation covers all Domains with
interactive source/image access and computed labels on a shared simpler host.
Neither earlier result establishes that the new hypothesis is true.

## Scientific review criteria before any gain claim

Review source-backed causal warrants before comparing computed labels. In
particular, distinguish assignment-effect analysis exclusions (D2) from missing
outcomes (D3), avoid treating a missing percentage as proof of no bias, inspect
measurement methods/assessor awareness (D4), and require supported selection
opportunities or prespecification evidence (D5). Preserve unknowns and contrary
source facts. Neither absent documentation nor outcome blinding mechanically
answers all questions. No invented missing counts, timestamp requirements, or
forced favourable answers are acceptable.

Minimalism loses this comparison if it omits necessary active answers, substitutes
a different outcome, weakens source warrants, ignores counterevidence or guidance,
or produces less defensible judgments. Equal labels alone are no improvement.
An isolated pair supports a mechanism diagnosis, not aggregate accuracy or
superiority over All-Low. Any later paid pair requires explicit authorization;
full benchmark remains off.

## Reproduce offline

Use the existing shared dependency environment, with clone code on PYTHONPATH:

```bash
export PYTHONPATH=src:scripts:.:tests
PY=/home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python
D=docs/evaluation/2026-10-05-minimal-assessment-preparation
# ROOT must be a fresh directory; preserve existing preparations.
"$PY" "$D/diagnostic.py" prepare "$ROOT" --official "$OFFICIAL_PDF"
"$PY" "$D/check.py" "$ROOT" offline-check
# review.py additionally needs isolated tiktoken 0.12.0 on PYTHONPATH.
"$PY" "$D/review.py" "$ROOT"
"$PY" "$D/diagnostic.py" plan "$ROOT"
```

`prepare` freezes both inputs, full evidence bundle/manifests and clean workspaces.
`plan` verifies exact CLI/model/medium support and creates separate credential-free
CODEX_HOME configurations; it does not launch inference. `serve WORKSPACE` exposes
the isolated MCP host. `validate ROOT --response FILE --workspace WORKSPACE`
computes labels and resolves citations. `usage JSONL` deduplicates durable per-response
usage, separates cached input, treats reasoning as an output subset, and leaves
pending usage/cost unknown rather than inventing totals. Future launches must use
the existing checked launcher with frozen prompt/evidence manifest hashes and
capture actual model/profile, delivery, completion/error, responses and usage.
Explicit paid authorization remains required before launch. Only already
authorized normal CLI authentication may be used; no credential expansion is
part of this preparation.

## Offline evidence

Actual stdio MCP checks confirm identical source schemas/page data/PNG bytes,
searches, original guidance images, blocked workflow/resources, real text and
visual citation resolution, closed output schema and active branches. Foreign Sources, existing foreign-Trial and nonexistent Evidence handles in
citations/counterevidence, modified immutable source bytes, missing active
answers, and model-supplied risk labels are rejected. Every native source page
remains exact; workflow metadata is absent from every delivered receipt text
block, actual PNG/receipt identities remain unchanged, and non-receipt contrary
prose is preserved.
Synthetic responses are explicitly fixtures, outside model inputs. Both arm
workspaces contain no Domain history. Usage duplicates count once. Scoped Ruff
format/lint and ty pass. Failed preparations/checks remain preserved; the earlier
v5 preparation corrected the initial omission of official D2 pages 30–33.

Preparations v6–v8 failed on visual-selector/typed-reference metadata and remain
preserved. The v9 integrity negative fixture initially changed the input PDF,
which does not modify immutable captured source bytes; the fixture was corrected
to tamper with the captured blob, which the validator rejects. v10–v12 are
retained successful intermediate preparations; v13 includes consistent minimum
SpO2 intake scope and exact Figure 2 population evidence. v14 widens the
Figure 2 visual region to include the complete flow diagram and records all its
labels. This history is not model input. No paid launch has occurred.
