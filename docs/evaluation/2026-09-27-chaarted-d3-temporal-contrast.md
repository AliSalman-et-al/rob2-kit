# CHAARTED OS D3.1 dated-basis contrast

## Question and scope

This diagnostic examines one warrant in the fresh CHAARTED Overall Survival
run. The approved Result is overall survival through the 2013-12-23 cutoff.
The saved D3.1 answer is `yes` and cites supplement CONSORT follow-up counts
“as of 12/23/14” and “as of ASCO presentation” as direct support. The main
article also states that all randomized patients were followed and included in
the primary analysis, in the passage that specifies the 2013 survival cutoff.

The dated scope of those two evidence paths is the measurement target. The
diagnostic does not assume that the final `yes` or the finalized Low label is
wrong: the main-article statement may provide separate availability support.
The final D3.1 answer and risk labels are descriptive and are not scored as
gold answers.

The source of the Result and answer is
`eval/runs/2026-09-27/issues-472-476-live/runs-v3/CHAARTED/overall-survival/phase-2.jsonl`.
Its finalized bundle is in that run's `workspace/.rob2-kit/finalized/`
directory. `scripts/verify_bundle.py` reported `bundle verified` for the
artifact with SHA-256
`8cd95f880bb71eda6cae9df462eb6e83cca48d523fd8b7545e9fc5ce061caee3`.

## Predeclared rubric

Each response is classified on three separate observations:

1. **Dated supplement basis:** Does it identify the supplement's stated
   2014-12-23 follow-up window as later than the approved OS cutoff? Does it
   separately handle the “as of ASCO presentation” count, whose excerpt gives
   no date, without treating it by itself as evidence of availability at the
   2013 cutoff?
2. **Main-report basis:** Does it separately assess the main-article statement
   that all randomized participants were followed and included in the primary
   analysis, in the passage that gives the approved OS cutoff? Does it keep
   this basis distinct from the supplement's later follow-up dates?
3. **D3.1 answer:** Record the selected answer and its stated rationale for
   context only. Do not label it correct or incorrect, and do not infer that a
   change in the answer makes the overall Low label wrong.

A paired candidate repeat counts as a gain only when it improves dated-basis
classification without dropping recognition of the separate main-report
basis. If every baseline repeat already satisfies both source-basis criteria,
the result is no measured gain. This rule is fixed in
`evaluator-key.json`; that file and its contents are excluded from all model
inputs.

## Arms and fixed context

The baseline uses the exact D3.1 comparison-card `prompt` captured in the
fresh run:

> Use the exact Result scope, passages, and quantities above. Classify only the
> remaining propositions; do not infer causation, availability, censoring,
> measurement influence, plan correspondence, or risk from metadata,
> arithmetic, or wording alone. An empty passage group is unopened, not a
> no-hit; inspect relevant Sources before recording an information limitation.

The candidate changes only that existing `comparison_card.prompt` field. It
asks the assessor to state each passage's date/window, compare that scope with
the approved Result, and separately consider statements about the approved
Result. It does not provide a target D3.1 answer or say which source supports
availability.

Every other input is fixed: the saved Result, all four D3 question cards, their
returned official guidance, the complete `missing.md` Domain 3 reference, the
comparison card's remaining fields and source inventory, and all captured
source excerpts. The excerpts include the main-article passages, the
supplement's participant-flow and causes-of-death pages, and the CONSORT
figure transcription. No evaluator key, recorded answer, final label, rubric,
or arm/repeat identifier appears in a model input.

## Run protocol

The registered plan has three paired repeats using `gpt-6-luna` at medium
reasoning effort. Within-pair order alternates baseline/candidate,
candidate/baseline, baseline/candidate. Each call uses a newly created empty
workspace, read-only sandbox, strict config, disabled shell and web search,
and disabled plugins, apps, and remote plugins. The runner pipes each rendered
input to `codex exec --json` and retains stdout JSONL, stderr, input hashes,
CLI arguments, and return codes. It does not retry failures.

Prepare inputs without executing:

```powershell
uv run python scripts/run_chaarted_d3_temporal_contrast.py
```

Execute the six registered calls:

```powershell
uv run python scripts/run_chaarted_d3_temporal_contrast.py --execute --output-dir eval/runs/2026-09-27/chaarted-os-d3-temporal-contrast-executed
```

The default output directory is
`eval/runs/2026-09-27/chaarted-os-d3-temporal-contrast/`. The runner refuses
to overwrite an existing directory, so each invocation needs a new output
directory. `manifest.json` records the trace and guidance hashes and each
input hash at render and launch. `run-plan.jsonl` maps each blind run ID to its
input and log; arm names are not sent to the model.

This is a reasoning-only prompt diagnostic. It does not exercise the public
`/rob2-assess` lifecycle, MCP retrieval, or review workflow. Three repeats do
not establish general model behavior, and source-basis review does not replace
expert adjudication of the final D3 or overall risk label.

## Results

All six calls completed with exit code 0 and one completed turn each. The
captured model version was `codex-cli 0.158.0-alpha.2.1`; all six input hashes
matched at render and launch, and no model tool calls were recorded. Stderr
contains a PowerShell shell-snapshot unsupported warning for each call; the
shell tool itself was disabled and no shell or web calls appear in the JSONL.
Logs and hashes are preserved in
`eval/runs/2026-09-27/chaarted-os-d3-temporal-contrast-executed/`.
The executed logs, run plan, inputs, and original evaluator key are also in
[the reviewable run evidence archive](2026-09-27-run-evidence.zip); the corrected
key wording and erratum are in this repository.

All six answers selected No information. In 3/3 baseline and 3/3 candidate
answers, the explicit 2014-12-23 supplement follow-up counts were described as
later than the approved 2013-12-23 survival cutoff and not sufficient by
themselves to establish availability at that earlier cutoff. Every answer
separately considered the main-article statement that all randomized patients
were followed and included in the primary analysis, aligned it with the
approved cutoff, and treated it as contextual rather than complete
cutoff-specific accounting. Candidate repeat 2 (`input-03`) separately
identified the “as of ASCO presentation” no-follow-up count as undated and
said it could not establish availability at the approved cutoff. Its paired
baseline (`input-04`) and the other four responses did not separately address
that count.

The executed evaluator key incorrectly called the undated ASCO-presentation
counts *later* follow-up. The excerpt does not establish that chronology. The
runner's key wording has been corrected; the executed key is retained in the
run artifacts as an erratum record. Under the corrected rubric, candidate
repeat 2 handled the undated count correctly. The original key cannot be used
to score that subcriterion.

The candidate improved the ASCO date/window subcriterion in one of three pairs
(1/3): repeat 2 classified the count's relation to the cutoff as unclear,
while its baseline omitted it. It did not change the explicit 2014-date
classification, treatment of the main-report statement, or D3.1 answer in
any pair. The candidate is not promoted on this single partial gain without
an adjudicated public-workflow improvement.

In the saved final-code answer, the ASCO-presentation counts were marked as
direct support for D3.1 despite the Result's earlier OS cutoff. Because the
figure excerpt supplies no ASCO date, those counts alone do not establish
availability at the approved cutoff. The main article's separate statement
that all randomized patients were followed and included in the primary
analysis may provide an independent availability basis. This source-warrant
finding does not prove that the saved `yes` answer or finalized Low D3/overall
labels are wrong; the controlled comparison's No-information answers are not
expert-adjudicated reference labels either.

All failed, incomplete, or inconclusive calls remain in the run artifacts and
are not retried or silently omitted.
