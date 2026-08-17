# rob2-kit

`rob2-kit` is a model-free FastMCP server for deterministic RoB 2 assessment.
An installed Codex or Claude Code host supplies the model loop; the server owns
captured Sources, verified Text projections, immutable packets, append-only
Domain checkpoints, terminal outcomes, and portable artifacts.

## Public MCP contract

The v2 server exposes these tools, in order:

`ingest_batch`, `list_sources`, `retrieve_evidence`, `render_page`,
`save_proposal`, `approve_batch`, `validate_domain_judgment`,
`commit_domain_judgment`, `finish_trial`, `finalize_batch`, `read_record`, and
`discard_active_batch`.

Resources are the compact `rob2://current-batch` projection, immutable
`rob2://detail/{kind}/{identity}` records, and captured
`rob2://registry/{trial_id}` records. Whole canonical records are read only by
deliberate identity-bound Detail requests; mutation responses remain compact.

## Install and use

Build and install the wheel, set `ROB2_WORKSPACE`, and register `rob2-mcp` as a
stdio MCP server in the host. The package includes the `rob2-workflow` and
`rob2-signalling` skills plus host manifests for Codex and Claude Code.

```powershell
uv build --wheel
python -m pip install dist/rob2_kit-0.2.0-py3-none-any.whl
rob2-mcp
```

The workflow is: capture and list Sources, retrieve and deliberately select one
preapproval anchor handle per Trial, save the minimal Proposal draft, read and
review its exact Proposal Detail, and approve that reviewed hash. Only then is
the approved packet the postapproval context boundary for further Evidence
retrieval, five Domain commits, synthesis review, Trial completion, and verified
artifact finalization. Explicit discard is reserved for a researcher instruction
bound to the displayed frozen identity.

See [the release contract](docs/release/README.md) for reproducible package
verification.
