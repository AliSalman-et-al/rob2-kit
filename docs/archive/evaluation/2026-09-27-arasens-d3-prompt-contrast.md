# Prepare the ARASENS D3 prompt comparison

This diagnostic measures the effect of the D3 comparison-card prompt for the
saved ARASENS Overall Survival assessment. It changes only the comparison
card's `prompt` field. The rendered inputs hold the September 26 Result,
question cards, reference guidance, source excerpts, and other card fields
fixed.

## Render the inputs

Run:

```powershell
uv run python scripts/render_d3_card_prompt_contrast.py --output-dir eval/runs/2026-09-27/arasens-os-d3-card-prompt-contrast-final
```

The renderer writes 12 prompt files and a `run-plan.jsonl`. The plan contains
three paired repeats for `gpt-6-luna` at medium effort and three paired repeats
for `gpt-6-sol` at high effort. It alternates the order within each model's
pairs. Each plan row names a separate JSONL log path under `logs/`. The
renderer does not invoke Codex CLI or create those logs.

The renderer refuses to reuse an existing output directory. Give it a new path
to regenerate the files. It extracts the generic prompt from commit
`8fa90ed5aec80de8bfc5dfb55e480b7a38f65dd8` and uses a frozen copy of the
tested D3-specific candidate in the renderer. The candidate remains available
for reproduction if production reverts it. The renderer extracts the fixed D3
reference from the September 26 run's recorded kit commit,
`d5528044066bc0300bd96ea4e99c25a35d58f6b0`.

The candidate card prompt says to preserve No information when availability is
unknown. That wording is the intervention under test. The saved trace answer,
its risk judgment, and the source review's rationale stay in
`evaluator-key.json` and do not enter model inputs.

## Context included in each input

The trace context comes from the completed D3 assessment calls in
`eval/runs/2026-09-26/rob2-trial-benchmark-luna-medium/isolated-worktree-run/rob2-trial-benchmark/overall-survival/ARASENS/phase-2.jsonl`.
The renderer uses the saved Result and its identity
`sha256:260eafee97cad11db21be572f022c75141e7441e10a381c81d83d8cf6709e75d`,
all four D3 question cards, and the D3 comparison card. It includes 14 source
excerpt records from five trace calls: three quoted passages returned with the
Result, ten `read_pages` windows, and one CONSORT diagram transcription.

The approved Result reports 1,305 participants in the full analysis set from
1,306 randomized participants. The included main-article excerpt separately
reports 1,306 participants in the primary analysis. The renderer keeps both
statements because the saved Result and the source excerpt contain both.

`evaluator-key.json` records the saved model answer and a provisional source
review. It stays separate from every model input. The saved Low judgment and
the source review's `likely_model_error` classification are not adjudicated
reference labels.
The source review is AI-authored and says the final label is not proven false.
The key's rubric checks the event, censoring, analyzed, randomized, and
follow-up claims without fixing a new expected label. A domain expert must
adjudicate the scientific interpretation of censoring for this time-to-event
Result.

## Keep the live observations separate

The fresh final-code CHAARTED Overall Survival run is a question-level
source-review candidate. D3.1 `yes` cites supplementary follow-up status as of
December 23, 2014, as direct support for the approved OS Result with a December
23, 2013 cutoff. The main article says all randomized participants were
followed, but does not report cutoff-specific vital-status counts. The later
supplement date does not establish status at the earlier OS cutoff. This is an
unsupported temporal-warrant candidate, not an adjudicated answer or Domain
error. See
`eval/runs/2026-09-27/issues-472-476-live/runs-v3/CHAARTED/overall-survival/phase-2.jsonl`.

The fresh uncoached ENZAMET Adverse Events run is a preservation observation.
Its D4 answer is High. AE collection followed time on treatment and a final
check 30 to 42 days after treatment stopped. At three years, 62% versus 34%
remained on regimen. Its D3 answer is High through the official No information
branch. Preserve both as source-review evidence, not label errors. See
`eval/runs/2026-09-27/issues-472-476-live/runs-v2/ENZAMET/adverse-events/phase-2.jsonl`.

The LATITUDE Adverse Events D4 sidecar preserves the Low domain label and marks
`sq:measurement:differential` as `likely_model_error`. It says the answer
dismissed a 24 versus 14 month median exposure difference without assessing
cumulative observation opportunity. The sidecar leaves the effect on the final
domain label unresolved. Its reviewer is AI source-grounded, not an independent
human expert. Treat it as a question-level source-review candidate, not an
adjudicated domain error. See
`eval/cohorts/2026-09-27-source-audits.json` for case
`2026-09-26:adverse-events:latitude`.

These separate observations do not appear in the ARASENS prompt files or
evaluator key.

## Attribute the comparison result

The September 26 host trace records the generic card prompt in the D3 context
response. It does not record the current D3-specific candidate prompt. The
renderer puts the selected prompt in each UTF-8 input file and records each
file's SHA-256 in `manifest.json`.

The runner's plan-to-log mapping identifies which response belongs to each
input file. Codex CLI JSONL does not echo the prompt, so the response trace
alone cannot prove prompt delivery.

## CLI run status

The first CLI batch was exploratory and is excluded from scoring. It used an
empty per-run working directory and these flags:

```text
--ignore-user-config --ignore-rules --disable shell_tool
--disable standalone_web_search --sandbox read-only --ephemeral --json
```

Input 04 nevertheless invoked web search. The batch was stopped after input
06; preserve its JSONL and stderr files under a separate exploratory label.
Its web-search observation means delivery and evidence context were not
controlled for that batch.

The corrected batch used one empty workspace per call and the Codex CLI with
`--ignore-user-config --ignore-rules --strict-config --disable shell_tool
--disable standalone_web_search -c 'web_search="disabled"' --json --ephemeral
--model <model> -c 'model_reasoning_effort="<effort>"' --sandbox read-only
--skip-git-repo-check --cd <fresh-empty-workspace> -`. The runner piped each
prompt named by `run-plan.jsonl` to stdin and wrote each response to its
matching `expected_jsonl_log`. It ran Luna Medium and Sol High, with three
paired repeats for each. All 12 logs contain completed turns, with zero model
tool calls. Do not score or combine the first batch.

All prompt-file hashes match the manifest on retrospective verification. The
runner did not record hashes immediately before piping prompts, and the CLI
JSONL does not echo user input. This verifies the current files against the
plan; it does not prove which bytes each model received.

The archived plan calls the candidate arm `current`, because it was created
while that wording was in production. In this report, `current` refers to the
tested candidate text frozen in the renderer; it does not mean the current
production prompt after the revert.

## Corrected comparison results

All 12 answers selected **No information** for D3.1. Every response separated
death events, censor counts, and analysis denominators from observed vital
status, and none claimed the captured evidence established complete
ascertainment. This question-level result is the primary measure for this
single-premise prompt test. Baseline and candidate (`current` in the archived
plan) tied in all six pairs; the
candidate produced no measured gain.

Free-form Domain 3 judgments varied. Luna's baseline/candidate pairs were: no
final label versus “unclear”; Some concerns versus Some concerns; and “cannot
be determined” versus Some concerns. Sol's pairs were Some concerns versus
High; High versus High; and High versus High. The answers do not provide an
adjudicated reference label for these outputs, so these judgment differences
are observations, not gains or losses. The evaluator key's recorded Low label
also remains provisional and is not treated as gold.

The tested D3-specific prompt candidate is rejected for lack of measured
benefit in this diagnostic. The production candidate was reverted after its
text was preserved in the renderer. This result does not establish how the public
`/rob2-assess` workflow behaves: these prompts used a saved context and omitted
the lifecycle, MCP retrieval, delivery, and review steps.

The fresh public ARASENS Overall Survival run subsequently finalized with High
overall risk. Its D3.1 answer was No information, and the saved Domain 3
judgment was High through the current RoB 2 path. The workflow completed with
exit code 0, and `scripts/verify_bundle.py` passed for the finalized artifact
`a8579d5b6dd051319e76832651d1887a3f4c0b44014e08d1745483c97d00e84b.rob2.zip`.
The D3 rationale distinguishes events and censor counts from actual status
availability and notes that the sensitivity analyses do not address missing
survival outcomes. This is a preservation result, not evidence that the tested
candidate caused the answer: the run was unpaired and used the candidate in
production before its revert. See
`eval/runs/2026-09-27/issues-472-476-live/runs-v2/ARASENS/overall-survival/phase-2.jsonl`.

The ARASENS inputs are a reasoning-only comparison. They do not exercise the
public `/rob2-assess` lifecycle, host delivery, or MCP tool use. The saved
September 26 JSONL contains the original host response, while the new diagnostic
tests only the supplied context and card-prompt wording.
