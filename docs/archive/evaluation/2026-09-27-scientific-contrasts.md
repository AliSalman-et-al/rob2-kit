# Scientific premise contrasts

## Purpose

Use the ten blinded prompts in [the contrast fixture](../../eval/scientific-premise-contrasts-2026-09-27.json) to test five distinctions in how sources support answers. Each pair changes one sentence that states a decisive premise. The evaluator key is separate from each model input.

The cases are synthetic and Trial-independent. Their expected answers and Domain judgments remain provisional until issue #475 adjudication. Use them to prepare the comparison, not to change production guidance or claim generalization to real Trials.

## Cases and repeats

Run the five pairs in the fixture. Keep every prompt, Source extract, Result scope, question guidance, tool set, pack revision, budget, Codex version, and model setting fixed within one comparison arm. Change only the declared scientific-context intervention between arms. Use the same three repeats per model input in both arms. Start each draw in a fresh Codex CLI invocation and retain every response and failure.

Counterbalance order within each pair. Run the first listed case before the second on repeats one and three. Reverse the order on repeat two. Use opaque case IDs. Do not pass `evaluator_key`, pair IDs, expected answers, or expected Domain judgments to the model.

Before scoring, two independent RoB 2 reviewers should adjudicate every target answer and Domain judgment. Freeze their resolution and evidence rationale. Exclude unresolved cases from the primary accuracy denominator and report them separately. Do not promote a change while any planned case remains unresolved.

## Scoring and acceptance

The primary measure is validity of the target premise. A response passes only when its answer follows the applicable RoB 2 branch and its rationale is supported by the delivered evidence. Score the answer separately from the overall Domain judgment. Record unsupported reassurance, unsupported concern, and `no_information` separately. An accurate Domain label does not excuse an unsupported premise.

Compare candidate and baseline on the same model, reasoning effort, Sources, Result scope, pack, tools, order, repeat count, and budget. Accept a change only when it corrects every unsupported warrant confirmed in issue #475 in at least two of three repeats, improves the valid-answer count for each warrant, produces no new unsupported reassurance or concern on the adjudicated preservation cases, and has more paired gains than losses in premise validity. If any acceptance condition fails, hold the change. Do not accept a cheaper or faster candidate that loses scientific validity.

Use `gpt-6-luna` at medium reasoning effort for the primary comparison. Run `gpt-6-sol` at high effort as a separate capacity diagnostic with the same inputs and repeats. Do not combine its results with the primary comparison or make production behavior depend on either model.

## Attribute failures

Inspect the captured model input and tool results before classifying an incorrect answer.

- **Retrieval failure:** the source passage was not found or returned by the assessment workflow.
- **Delivery failure:** the workflow recovered the passage but did not put it in context the model could see before it answered.
- **Interpretation failure:** the decisive passage and applicable question guidance were delivered, but the answer used an unsupported premise or the wrong branch.
- **Unresolved delivery:** the capture does not show whether the passage or guidance reached the model.

Use captured JSONL and source locators to establish delivery. A source existing in the workspace, a search hit, or a citation in the final answer does not prove the model received the decisive passage. A passage in input the model could see establishes delivery only. It does not establish reading or comprehension.

## Codex CLI pilot

The 27 September pilot ran only pair P-2. It used a plain assessment prompt and the two supplied Article and Protocol extracts in an empty temporary workspace. The command removed the `/rob2-assess` prefix because that workspace had no RoB 2 assessment tools. It ran one draw per case with `gpt-6-luna` at medium effort and `gpt-6-sol` at high effort, using Codex CLI 0.157.1, read-only sandboxing, and JSONL output. This was a reasoning diagnostic. It did not use the skill, current scientific pack, MCP retrieval, public assessment workflow, review, or bundle verification. The four JSONL logs and their stderr files remain under `%TEMP%\rob2-kit-scientific-contrast-pilot-11b7ec785beb48adab05439b8972fda9` on the pilot machine.

Luna rated both P-2 cases High. Sol rated C-31 Low for Domain 2 when estimating the effect of assignment to treatment, and C-42 High. Sol used web searches and command executions on both cases. Luna used neither. The models did not have the same tool activity, so their judgments are not a controlled model comparison. This pilot also used one draw per case and does not meet the three-repeat evaluation plan.

The pilot prompt revision did not state that no control participants received rescue treatment or that rescue treatment directly reduced the target symptoms. I added those shared facts to both P-2 cases after reviewing the pair. The four logs therefore do not match the current fixture inputs and are not baseline scores for the checked-in cases.

In that earlier prompt revision, the Luna response for C-31 cited the prohibited rescue treatment and possible symptom effects even though participants initiated it outside the trial context. The Sol response for C-31 distinguished usual care initiated by participants from clinician-directed changes. These responses are diagnostic observations, not adjudications. The evaluator key remains provisional pending issue #475.

Codex CLI JSONL recorded the completed assistant response and token counts but did not include a user-message record. The pilot command piped each prompt file, extracted from `model_inputs`, to stdin. Both responses discussed the case-specific facts. This supports that the input reached each model. JSONL alone cannot prove full prompt delivery.

The four pilot attempts were exploratory. The rubric was written afterward, and the prompts changed afterward. They do not qualify as a baseline. Apply the rubric below to the current fixture before the full comparison begins.

Use the checked-in runner for the plain prompt diagnostic. It removes the
leading `/rob2-assess ` because the empty workspaces do not contain the
assessment tool. It passes only the extract text to each model. Pair IDs,
expected answers, and labels stay in `run-plan.jsonl` or the separate
`evaluator-key.json`; they do not appear in model inputs. Each call gets a
fresh empty workspace, input file, JSONL log, and stderr file.

```powershell
uv run python scripts/run_scientific_contrast_baseline.py `
  --model gpt-6-luna --effort medium --repeats 3 --run `
  --output-dir eval/runs/2026-09-27/scientific-premise-baseline-luna-medium
```

After reviewing the Luna results, run the separate Sol capacity diagnostic in a
new output directory:

```powershell
uv run python scripts/run_scientific_contrast_baseline.py `
  --model gpt-6-sol --effort high --repeats 3 --run `
  --output-dir eval/runs/2026-09-27/scientific-premise-baseline-sol-high
```

The runner uses strict Codex configuration, disables shell and standalone web
search, sets `web_search="disabled"`, uses read-only sandboxing and JSONL, and
records the exact prompt hash immediately before each call. JSONL does not echo
the user prompt; the launch hash records the bytes piped by the runner, not a
model-side delivery receipt. This diagnostic does not include the current
scientific pack or public assessment tools. It does not satisfy the issue's
full workflow acceptance criteria.

## 27 September Luna Medium baseline

The first controlled baseline ran all five pairs three times with
`gpt-6-luna` at medium effort. It used the checked-in fixture unchanged, a
fresh empty workspace per call, and the strict CLI configuration above. The
runner piped only each prompt file and recorded its SHA-256 immediately before
launch. It kept JSONL and stderr per case. See
`eval/runs/2026-09-27/scientific-premise-baseline-luna-medium/`.

The model followed the provisional premise contrasts for P1, P4, and P5 in all
three repeats. It assigned Some concerns to C-14, Low to C-27, Low to C-75 and
C-93, and Some concerns to C-86 and C-04. For P2, it raised concern for
C-31—the ordinary-care change participants sought independently—in all three
repeats (High, Some concerns, High). It rated C-42 High in all three repeats,
where trial clinicians directed the prohibited change. For P3, it raised
concern for C-53 in all three repeats (High, Some concerns, Some concerns),
despite the shared month-3/6/9/12 schedule and assessment after treatment
stopped. It recognized the extra biweekly testing in C-68 in all three repeats
(Some concerns, High, Some concerns).

These results identify repeatable premise errors in a plain-prompt diagnostic,
not in the public workflow. The exact production pack and comparison-card
context were absent, and the fixture's expected answers remain provisional
pending independent RoB 2 adjudication. P3 is the closer match to the LATITUDE
Adverse Events source-review candidate. Do not treat the free-form Domain
labels as calibrated risk estimates: the C-68 answer varied between Some
concerns and High despite identifying the same extra detection opportunity.

The separate Sol High capacity run completed 30/30 calls. It will not be
combined with the Luna primary comparison. P2 C-31 received Some concerns in
all three repeats, although the rationales left trial-context causation
unresolved; C-42 was High in all three. For P3, all three C-53 answers treated
the shared fixed schedule as evidence against differential measurement despite
unequal exposure. Two also raised a separate selection concern because the
prompt did not state the grade threshold. All three C-68 answers identified
the extra biweekly tests as an additional detection opportunity. These
plain-prompt outputs remain reasoning diagnostics, not evidence about
public-workflow behavior.

To check whether the P2/P3 findings persist with current pack guidance, run
only those two pairs with the same Luna setting. This adds the existing
Domain 2 or Domain 4 reference, target proposition, and generic production
comparison-card prompt to both cases in each pair. It changes neither the
fixture premises nor production guidance.

```powershell
uv run python scripts/run_scientific_contrast_baseline.py `
  --model gpt-6-luna --effort medium --repeats 3 `
  --pair P-2 --pair P-3 --include-production-guidance --run `
  --output-dir eval/runs/2026-09-27/scientific-premise-guided-luna-medium
```

Treat this as a context check only. It still does not exercise retrieval,
public `/rob2-assess` workflow, review, or artifact verification.

## 27 September fixed-guidance context check

After the plain-prompt scan, a follow-up ran P2 and P3 with the current Domain
references, the target proposition and question ID, and the generic production
comparison-card prompt. Both cases in each pair received identical guidance.
Each case ran three times with Luna Medium in a fresh workspace, using strict
Codex configuration, JSONL, read-only sandboxing, and shell and web search
disabled. The runner recorded the SHA-256 of each input immediately before
launch. The manifest and logs are under
`eval/runs/2026-09-27/scientific-premise-guided-luna-medium/`.

For P2, C-31 was answered Probably no in all three repeats: the rationales
separated participants' requests to usual-care clinicians from changes caused
by study staff. C-42 was rated High in all three repeats because trial
clinicians directed the prohibited changes. For P3, the three C-53 rationales
did not infer differential measurement from unequal treatment exposure alone;
one retained Some concerns for a separate assessor-information gap. All three
C-68 answers identified the extra biweekly tests as increased detection
opportunity. The pack context therefore removed the synthetic P2/P3 premise
errors seen in the plain-prompt Luna run, while preserving the positive C-68
contrast.

This follow-up was prompted by the plain-prompt results and is not a
pre-registered candidate-acceptance test. It is still a reasoning diagnostic:
it does not exercise retrieval, the public lifecycle, review, or bundle
verification. The evaluator key remained outside the model inputs; the run
manifest records that split and the launch-time hashes.

## 27 September LATITUDE D4 card-prompt contrast

The plain and fixed-guidance P3 synthetic results did not reproduce the
source-review concern on the saved LATITUDE Adverse Events answer. The saved
answer was `probably_no` for `sq:measurement:differential`; its Low Domain
judgment is not independently adjudicated. The source-review sidecar flags
the answer's dismissal of the 24-versus-14-month median exposure difference,
but leaves the effect on the final Domain judgment unresolved. The reviewer is
AI source-grounded, not an independent human expert.

The paired diagnostic uses the saved September 26 Result, all captured Domain
4 question cards, the comparison card, nine source-excerpt records from the
phase-1 and phase-2 JSONL traces, and the measurement reference from the saved
kit commit `d5528044066bc0300bd96ea4e99c25a35d58f6b0`. The excerpt set includes
the report's 24-versus-14-month treatment-exposure statement and the protocol's
AE collection window through at least 30 days after the last dose. The saved
answer did not cite the exposure excerpt, but the trace shows it was retrieved
before the answer. The only arm difference is the comparison card's `prompt`
field. The candidate text is frozen in
`scripts/run_latitude_d4_card_prompt_contrast.py`.

The run also includes C-68, where intervention-only biweekly laboratory tests
create an explicit extra detection opportunity. Three Luna Medium paired
repeats ran for both the saved LATITUDE case and C-68: 12 calls total. Codex
CLI used JSONL, strict configuration, read-only sandboxing, fresh workspaces,
and disabled shell and web search. All 12 calls exited 0 and completed one
turn; none invoked a tool. The manifest records each input's render and
launch-time SHA-256. Logs and inputs are under
`eval/runs/2026-09-27/latitude-d4-card-prompt-contrast-luna-medium-controlled/`.

For LATITUDE, the baseline answered No information in all three repeats; the
candidate answered Probably yes in all three. Candidate rationales connected
the exposure difference to possible cumulative detection opportunity while
stating that actual group-specific windows, attendance, and effect were not
quantified. The saved `probably_no` answer therefore did not reproduce in the
baseline. For C-68, both arms answered Yes in all three repeats and identified
the extra tests as a detection opportunity.

This is a measured prompt effect with the C-68 preservation case intact. It is
not a demonstrated scientific gain: the baseline already retained uncertainty,
and the sidecar does not adjudicate whether No information or a qualified
Probably yes is the valid D4.2 answer. Median exposure alone does not quantify
actual observation time or ascertainment. Keep the candidate out of production
pending independent adjudication. This test does not exercise public retrieval,
the `/rob2-assess` lifecycle, review, or bundle verification.

The first render attempt stopped before any Codex call because key-separation
validation mistook the saved `probably_no` answer code for leaked evaluator
text, even though that code also appears as a normal question option. The
validation now checks private rationale and review text. The no-call failure is
recorded at
`eval/runs/2026-09-27/latitude-d4-card-prompt-contrast-luna-medium/attempt.json`.
The successful rendered-only files are in
`eval/runs/2026-09-27/latitude-d4-card-prompt-contrast-luna-medium-prepared-final/`.
The earlier render omitted the exposure excerpt and was not run; its status is
recorded in that directory's sibling `-prepared/superseded.json` file.

To render and run the Luna comparison again, use a new output directory:

```powershell
uv run python scripts/run_latitude_d4_card_prompt_contrast.py `
  --output-dir eval/runs/2026-09-27/latitude-d4-card-prompt-contrast-luna-medium-rerun `
  --model gpt-6-luna --effort medium --repeats 3 --run
```

The runner keeps the evaluator key separate and records the exact prompt-file
hash immediately before piping each input. JSONL does not echo the user prompt;
the launch hash records the bytes the runner supplied, not a model-side receipt.

## Validation

Run:

```powershell
uv run pytest -q tests/test_scientific_contrasts.py
```

The tests check valid JSON, ten unique opaque model inputs, all five required contrast themes, one changed sentence per pair, fixed pair controls, separation of the evaluator key, and coverage of Low, Some concerns, High, and `no_information` answers.
