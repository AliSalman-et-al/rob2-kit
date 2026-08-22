# rob2-kit

`rob2-kit` is a model-free FastMCP boundary for deterministic RoB 2 assessment.
An installed Codex or Claude Code host supplies the model loop; the server owns
captured Sources, verified Text projections, immutable packets, append-only
Domain checkpoints, terminal outcomes, and portable artifacts.

## Public MCP contract

The v2 server exposes these tools, in order:

`preflight_sources`, `inspect_candidate_sources`, `save_intake_plan`,
`capture_batch`, `list_sources`, `retrieve_evidence`, `render_page`,
`save_proposal`, `approve_batch`, `validate_domain_judgment`,
`commit_domain_judgment`, `prepare_trial_finish`, `finish_trial`,
`finalize_batch`, and `read_record`.

Resources are the compact `rob2://current-batch` projection, immutable
`rob2://detail/{kind}/{identity}` records, and captured
`rob2://registry/{trial_id}` records, and binary `rob2://render/{identity}`
images. Whole canonical records are read only by
deliberate identity-bound Detail requests; mutation responses remain compact.

## Install and use

Build and install the wheel, set `ROB2_WORKSPACE`, and register `rob2 mcp` as a
stdio MCP server in the host. The package includes the `rob2-workflow` and
`rob2-signalling` skills plus host manifests for Codex and Claude Code.

```powershell
uv build --wheel
python -m pip install dist/rob2_kit-0.2.0-py3-none-any.whl
rob2 mcp
```

Start an isolated Claude Code assessment with a private prompt on stdin (or
`--prompt-file`):

```powershell
rob2 assess --host claude-code --workspace . --prompt-file prompt.txt
```

Codex assessment launch is currently unsupported: the installed Codex CLI does
not provide a process-scoped MCP-only tool allowlist, so `rob2 assess --host
codex` fails closed rather than exposing shell/filesystem capabilities.

The launcher uses a process-scoped MCP configuration and always appends a
machine-verifiable `Verified rob2-kit status` block after host output.

The workflow is: capture and list Sources, retrieve and deliberately select one
preapproval anchor handle per Trial, save the minimal Proposal draft, read and
review its exact Proposal Detail, and approve that reviewed hash. Only then is
the approved packet the postapproval context boundary for further Evidence
retrieval, five Domain commits, synthesis review, Trial completion, and verified
artifact finalization.

See [the release contract](docs/release/README.md) for reproducible package
verification.
