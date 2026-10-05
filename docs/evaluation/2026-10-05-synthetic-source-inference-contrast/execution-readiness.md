# Offline binding and proposed execution readiness

Independent parent review approved the original 758a14a factual design, rubric,
10 hashes, prompts and eight supplied/required source windows. Execution remains
NO-GO pending acceptance of this checker checkpoint and explicit paid authority.
Original sources, model prompts, schema and scientific rubric are unchanged.

## Binding checks

Run from the repository root using the existing dependency environment:

```bash
PYTHONPATH=src:scripts:.:tests /home/ali/Documents/Codex/2026-10-02/task/rob2-kit/.venv/bin/python docs/evaluation/2026-10-05-synthetic-source-inference-contrast/check_output.py response.json
```

Without a response argument this checks the frozen files, existing strict wire
subset and JSON Schema syntax, and both coverage manifests. With a response it
also rejects duplicate JSON object keys and responses above 24,000 bytes, applies
the unchanged wire schema and authoritative SourceCheckReport type, and verifies:

- Exactly one finding and revision for each of 13 IDs, in frozen packet order;
  no foreign, extra, missing or duplicate IDs.
- Exact snapshot SHA, complete original clause and field `justification`.
- Current case ownership, page 1, positive ordered line ranges within bounds.
- At least one text citation per finding, each with a nonempty contiguous quote.
  Visual citations, null quotes and empty reference lists are rejected.
- Canonical synthetic source SHA: unnumbered lines joined with newline plus a
  trailing newline. The packet's shorthand must match that SHA.
- Authoritative quote resolution permits only ASCII-whitespace collapse while
  preserving lexical content and requiring one unambiguous contiguous excerpt.

The independent review's requirement for at least one citation is an experiment
binding requirement, stricter than SourceCheckReport's general empty-list shape.
An unresolved classification is permitted with a locatable citation; it does not
have to assert semantic support. Blank required explanation/uncertainty, quotes
or draft text are invalid under the authoritative contract/local draft check;
they are neither filled in nor converted into a preferred semantic answer.
Revisions remain advisory. Passing says nothing about entailment or correction.

`check_fixtures.py` is a one-off companion in this experiment directory, not a
production test framework. It writes mechanical JSON controls privately under
`diagnostics/synthetic-source-inference-contrast-20261005/binding-fixtures` and
records expected acceptance/rejection in `binding-verification.json`. These are
not expected scientific answers, model responses or model input. Re-run with the
same Python/PYTHONPATH command. Schema-valid zero-findings and wrong-snapshot
fixtures demonstrate why schema acceptance alone is inadequate; the binding
checker rejects both. All optional nullable wire properties must still be
present, all objects are closed, root is an object, local references resolve,
and unsupported schema vocabulary is rejected by the existing helper. Local
checks do not establish provider acceptance; there is no paid schema probe.

## Anonymized evaluation packet

After authorized execution, freeze both raw final outputs and usage/events first,
including failures, and hash them before inspecting semantic differences. Keep
raw stderr, session/response IDs, prompts, tool/config metadata and telemetry
private; do not give these to the blinded evaluator.

Create evaluator files `evaluation-U.json` and `evaluation-V.json`. Allocate U/V
by a private random permutation after outputs are frozen; record the random
choice, original-output hashes and U/V hashes in private
`operator-only/arm-key.json`. Do not use arm-dependent filenames, session order
or comments in evaluator files. Each file contains the original parsed response
without rewriting reasoning, plus its mechanical validation result. Malformed
output is provided as raw output with the failure receipt, not silently repaired.
Give the evaluator both anonymized files, common source packet and rubric;
withhold prompts, question wording, mapping, usage and operator interpretations.
The reviewer locks per-claim factual scores before the arm key is revealed.
Keep any explicit self-identification in the original response and record it as
potential unblinding; do not secretly edit it away. A syntactic classification
name is not the scientific reference decision.

## Concrete prelaunch and usage plan (not launch authorization)

The installed executable was checked offline: codex-cli 0.159.0 at
`/home/ali/.nvm/versions/node/v24.21.0/bin/codex`. Its help confirms
`--output-schema`, `--json`, `--output-last-message`, `--ignore-user-config`,
`--ignore-rules`, `--strict-config` and `--skip-git-repo-check`. Reuse the prior
isolated launcher pattern, with exact overrides `-m gpt-6-luna`,
`model_reasoning_effort="medium"`, `features.code_mode={enabled=false}`, disabled
shell_tool/unified_exec, `web_search="disabled"`, and read-only sandbox. Unlike
the prior Baillard configuration, **no MCP servers are needed or allowed**.
Neither credentials nor new auth homes were created here. Use only the existing
authorized CLI auth environment; ignore its user config. An empty isolated
working directory must expose no AGENTS/skills/project instructions. Pass the
frozen prompt via stdin and the shared schema by absolute path. Before inference,
freeze actual argv, cwd, effective configuration, executable hash/version,
instruction delivery, empty tool inventory and intended model/effort. Verify
recorded actual model/effort from turn-context events after execution; mismatch
invalidates interpretation and does not authorize a replacement run.

For each arm use existing `launch_checked` with that arm's frozen manifest path,
prompt path and expected manifest SHA, recording its receipt before Popen.
Run `check_output.py` preflight immediately beforehand. The frozen manifests
cover every synthetic source line, including uncited material; the checker does
not certify scientific sufficiency. Parent's independent GO is design review,
not paid approval. Record explicit approval with intended two initial sessions,
no continuation/retry/third session and no feedback before any inference.

Proposed operational limits for parent approval: one review pass/arm, zero tools,
no retries; 300-second wall timeout/arm; 24,000-byte final acceptance budget.
Stop any unexpected tool invocation, configuration/model mismatch or continuation
request; preserve the failed run. There is no verified provider hard token cap,
and these limits are not a dollar cap. Do not claim the byte limit prevents
provider expenditure. Freeze any numeric usage limit the parent requires before
launch; no such token/dollar ceiling has been authorized in this checkpoint.

Reuse the existing private diagnostic usage aggregation: deduplicate
`token_usage_record` by response_id, reject conflicting duplicates, report input,
cached input, uncached input=input-cached, output and reasoning output separately.
Reasoning is a subset of output and must not be added again. Preserve raw records
and turn-context model/effort. Record completed/failed/timeout state, response
count, missing usage and unknown pending usage; a rejected initial request with
no durable usage has unknown billing, not zero cost. No dollar conversion without
verified applicable rates. Do not expose account identifiers in public artifacts.
A missing durable usage record is an accounting limitation to report, not grounds
for rerunning. The existing usage function is private in the preserved Baillard
one-off diagnostic; no new accounting framework is needed.

Remaining execution prerequisites: parent acceptance of checker, explicit paid
approval and guards, actual effective tool/config verification at launch. No
launcher, inference or credentials were created as a schema test.

## Interpretation limits retained

T4 principally tests preserving a directly supported 59-person count; it is a
weak test of difficult probable inference. There is no positive
outcome-dependent-missingness case. Thirteen dependent claims are nested in four
worlds and two sessions, not 13 independent trials. The fixed sibling panel can
produce a ceiling. Do not expand this design, claim accuracy improvement, replace
benchmark cases, change production defaults or launch a full benchmark from it.
