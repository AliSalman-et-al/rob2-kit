# rob2-kit

`rob2-kit` is a model-free FastMCP server for RoB 2 assessments. An installed
Codex or Claude Code host supplies the only LLM/agent loop; the server supplies
the deterministic workflow, structured records, and evidence services.

It ingests local trial material, attempts matched ClinicalTrials.gov registry
capture, and exposes immutable Sources for lexical search, page-text reading, and
selective PDF rendering. A complete batch proposal must be saved and approved
before assessment. Evidence-grounded Domain judgments are versioned working
records: before `finish_trial`, an exact active-hash correction replaces the active
revision while earlier revisions remain append-only audit entries. `finish_trial`
freezes active revisions into an immutable assessment snapshot for deterministic
RoB 2 logic. Each Trial ends exactly once as an assessment, `needs_input`, or
`failed`; finalization produces durable recovery state and verified trial and batch
HTML reports.

## Public MCP contract

The server exposes eleven tools:
`save_proposal`, `ingest_batch`, `list_sources`, `read_pages`, `search_sources`,
`render_page`, `approve_batch`, `save_domain_judgment`, `finish_trial`,
`finalize_batch`, and `discard_active_batch`.

Its three resources are `rob2://current-batch`,
`rob2://domain-guidance/{domain_id}`, and `rob2://registry/{trial_id}`.

## Install and use

Build and install the wheel, then register `rob2-mcp` as a stdio MCP server in
your host. Set `ROB2_WORKSPACE` to the assessment workspace. Copy the packaged
`rob2-workflow` and `rob2-signalling` directories from `rob2_kit/skills` into the
host's skill directory; they are the two portable workflow skills shared by
Codex and Claude Code.

```powershell
python -m build
python -m pip install dist/rob2_kit-0.1.0-py3-none-any.whl
rob2-mcp
```

The minimal workflow is: save one complete proposal, ingest its trial inputs,
approve the batch, inspect each Trial's Sources and registry record, save its five
Domain checkpoints, finish the Trial, then finalize the batch.

For the frozen release checks, see [the release contract](docs/release/README.md).
Claude Code has accepted real-host evidence. Codex CLI 0.147.0 on Windows remains
an unaccepted known MCP limitation; it is documented in
[issue #193 acceptance evidence](docs/acceptance/issue-193.md).
