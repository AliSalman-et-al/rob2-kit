---
name: verify-rob2-kit
description: Drive the real rob2-kit MCP server (stdio, `rob2 mcp` / `rob2 mcp-codex`) and the `rob2` CLI through synthetic RoB 2 assessments and capture evidence. Use it to prove a change to tools, workflow gates, the skill, finalization/verification, the Codex entrypoint or the Claude Code/Codex plugin packaging behaves as a host and researcher would see it, rather than only passing unit tests.
---

# Verify rob2-kit

rob2-kit has no UI. A user touches it in three ways:

- an **MCP host**, such as Claude Code or Codex, which calls the stdio server's tools;
- the **`rob2` CLI**, which the researcher uses to approve (`rob2 review`), verify and archive;
- the **plugin install** itself.

Verification means acting as that host and that researcher against the real
server process. The harness for this already exists: `tests/e2e/agent.py`
(`Agent`) starts `python -m rob2_kit.interfaces.cli.app --workspace <dir> mcp`
over stdio. It calls tools using only public arguments and approves through the
real CLI. `tests/e2e/trial.py` builds synthetic trial folders (a real PDF made
with pymupdf, plus a protocol and a registry replay).

Never use real trial reports as verification input. They are copyrighted, and
the repository must not contain them. Build sources with `tests/e2e/trial.py`,
or write new synthetic text in the same way.

## Launch

The server is short-lived: one stdio process per `Agent`, killed on disconnect.
There is nothing to keep running.

```bash
uv sync --locked
```

Each drive creates its own temporary workspace. The workspace is the folder
that contains `input/<trial>/…`. All state lives in `<workspace>/.rob2-kit/`.
Workspaces are fully isolated, so drives can run in parallel.

Ready means `Agent(...)` returned: the MCP initialize handshake has completed.

## Doctor

Run this first, and again whenever something looks off. It is read-only.

```bash
uv run python .agents/skills/verify-rob2-kit/doctor.py
```

It checks the following:

- the installed package version matches `pyproject.toml` (if not, run `uv sync`);
- the CLI starts;
- `rob2 mcp` and `rob2 mcp-codex` each list exactly the tools in `docs/release/public-contract.json`;
- both plugin manifests carry the package version.

Any `FAIL` means the instance is not worth driving.

## Drive

Scripted scenarios, with evidence written for you:

```bash
uv run python .agents/skills/verify-rob2-kit/drive.py assess
```

```bash
uv run python .agents/skills/verify-rob2-kit/drive.py codex-render
```

The script prints the evidence directory and then `PASSED` or `FAILED: …`, and
exits non-zero on failure. Add `--keep-workspace` to copy the final workspace
into the evidence.

For any other behavior, write a short script in your scratch directory that
reuses the harness:

```python
import sys, tempfile
from pathlib import Path

sys.path[:0] = ["<repo>/tests", "<repo>"]
from e2e import trial
from e2e.agent import Agent, answer, rob2
from e2e.test_assessment import OUTCOME, selection, low_risk_answers

ws = Path(tempfile.mkdtemp(prefix="rob2-verify-"))
trial.build(ws)  # also: trial.build_open_label, trial.build_sparse
agent = Agent(ws)  # Agent(ws, server="mcp-codex") for the Codex entrypoint
try:
    agent.prepare(OUTCOME)  # prepare_batch; sets agent.trial_id and agent.sources[role]
    agent.read_required()  # reads every window the server's next_action names
    ...  # agent.call / agent.ok / agent.raw / agent.next_action()
finally:
    agent.close()
```

### Harness methods

| Method | What it does |
| --- | --- |
| `call(tool, args)` | Returns the structured result, or `{"error": text}`. It never raises. |
| `ok(tool, args)` | Same as `call`, but asserts `outcome == "success"`. |
| `raw(tool, args)` | Returns the MCP `CallToolResult`, for content blocks and images. |
| `tools()` | The advertised tool definitions. |
| `resource("rob2://current-batch")` | Reads the batch resource. |
| `cite(role, page, quote)` | Selects a literal quote and returns its evidence handle. |
| `cite_lines(role, page, first, last)` | Cites the numbered lines that span `first` through `last`. Use it when a phrase crosses a PDF line break. |
| `propose(*selections)` | Runs `validate_proposal` then `save_proposal`. It returns the repair result when validation fails. |
| `approve()` | Calls `request_proposal_approval`, then runs `rob2 review --review-reference <ref>` with `yes` on stdin. |
| `context()` | Drains every page of `get_domain_context`. |
| `save_domain(domain_id, answers, **extra)` | Saves one Domain judgment. |
| `close_trials()` | Calls `review_trial` and `close_trial` until no further action is pending. |
| `finalize()` | Calls `finalize_batch`. |
| `answer(question_id, value, handles, why)` | Builds one answer, with each handle as direct support. |

The full workflow of each feature is in [features/README.md](features/README.md).

### Rules the server enforces

Drives that ignore these fail for reasons unrelated to the change under test:

- Every mutating call needs `expected_revision`, read from `get_status`'s `head.state_revision`. A stale value is rejected.
- Follow `head.next_action`. Required main-report reading appears there as `read_pages` with `windows`, both before validating a proposal and again after approval. `agent.read_required()` handles it.
- A citation must quote source text literally. Table passages must contain both the row label and the estimate. An `exact` relation needs every clarity facet. `baseline_subgroup` must be given explicitly, even as `None`.
- The `answers` for a Domain must match its active signalling questions, since earlier answers switch later questions on or off.
- Approval is the researcher's alone. The host cannot approve through tool arguments. `rob2 review` records approval only when it reads `yes`.

## Evidence

`drive.py` writes `.verify-evidence/<UTC time>-<scenario>/` at the repository
root. That directory is git-ignored, and cleanup never deletes it. It contains:

- `transcript.jsonl`, with one `{"tool", "arguments", "result"}` line per call, from `agent.calls`;
- `outcome.json`, holding the observed end state and `passed`;
- scenario artifacts, such as the finalized `.rob2.zip` or the rendered `page-2.png`.

Custom drives should write the same files to the same place.

Proof standards:

- Drive the public path: tool calls a host can make and CLI commands a researcher can type. Never prove a behavior by writing to `.rob2-kit/` directly or by calling `rob2_kit.application.*` functions.
- Capture the action and the resulting state. For a mutation, take a second, read-only view: `get_status`, `rob2 status`, the `rob2://current-batch` resource, or the finalized bundle.
- Verify side effects. A finalized bundle must pass both `rob2 verify <bundle>` and `python scripts/verify_bundle.py <bundle>`. A tamper check must make both fail.
- The only external boundary is ClinicalTrials.gov. The synthetic trials replay a saved registry record (`[registry] replay` in `sources.toml`), so drives make no network calls. Do not point a drive at a live NCT number unless the change is the lookup itself.

## Plugin packaging

Use this when `.claude-plugin/`, `.codex-plugin/`, `pyproject.toml` or the skill path changes.

```bash
claude plugin validate .
```

**Claude Code, live, one session, no configuration change.** Run this from an empty folder that contains `input/<trial>/`:

```bash
echo "Call the rob2 get_status tool once and print its raw JSON result verbatim." | MCP_TIMEOUT=120000 claude -p --model haiku --plugin-dir <repo> --allowedTools "mcp__plugin_rob2-kit_rob2__get_status"
```

The first launch builds the package with `uvx`. If the model reports that the
server is "still connecting", run the command again.

**Codex**, in a throwaway `CODEX_HOME` so the user's configuration is never
touched:

```bash
CODEX_HOME="$(mktemp -d)" sh -c 'codex plugin marketplace add <repo> && codex plugin add rob2-kit@rob2-kit && codex mcp list'
```

`codex mcp list` must show `rob2` running `uvx … rob2-kit@v<version> rob2 mcp-codex`.
A local-path install copies the entire checkout, including `.venv`, so delete
that `CODEX_HOME` afterwards. Codex does not substitute plugin-root variables,
so its server runs the git tag. A version that has not been tagged cannot start
from the Codex plugin.

## Cleanup

`drive.py` deletes its temporary workspace after writing evidence. Custom drives must:

1. call `agent.close()` in a `finally` block, which stops the stdio server they started;
2. delete the temporary workspace they created, and nothing else;
3. delete any throwaway `CODEX_HOME`.

Never kill `python` or `uvx` by name, because the user's hosts run the same server.
Never delete `.verify-evidence/`, and never run `rob2 discard` outside a temporary workspace.
