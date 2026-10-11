# rob2-kit user guide

This guide walks through one assessment from start to finish. To install the
plugin first, see the [README](../README.md#install).

## How an assessment runs

1. **Prepare.** The agent registers the trials under `input/` and captures their
   sources. A captured source is fixed by its content hash.
2. **Read and propose.** The agent reads each main report. It then proposes one
   result per trial for your outcome: the reported estimate, the analysis
   population and the comparison groups, each supported by cited passages. If
   no eligible result is reported, the proposal says so.
3. **Approve.** You review the proposal and approve it. This is the only
   approval step. Domain work cannot start until you approve.
4. **Assess.** For each of the five RoB 2 domains, the agent answers the active
   signalling questions. Every answer cites passages from the captured
   sources. The server applies the official algorithm to produce the domain
   judgment, then combines the domains into the overall judgment.
5. **Close and finalize.** The agent reviews and closes each trial, then
   finalizes the batch into a verifiable bundle.

The agent can stop at any point and resume later. All state is kept in
`.rob2-kit/` inside the assessment folder.

## Prepare the assessment folder

Create one folder per trial directly under `input/`. The folder name becomes
the trial label, so use a meaningful name.

```text
my-review/
└── input/
    ├── TRIAL-A/
    │   ├── main-article.pdf
    │   ├── supplement.pdf
    │   ├── protocol.pdf
    │   ├── registry.json
    │   └── sources.toml
    └── TRIAL-B/
        └── main-article.pdf
```

Supported formats are PDF, DOCX, TXT, Markdown, CSV and JSON. Legacy `.doc`
files are not supported, so convert them to DOCX or PDF. The agent can render
image-only PDF pages and transcribe what it sees as visual evidence.

### `sources.toml`

This file is optional. It declares source roles and the trial's registry
number:

```toml
nct = "NCT01234567"

[roles]
"article.pdf" = "main_article"
"appendix.pdf" = "supplement"
"analysis-plan.pdf" = "sap"
```

The valid roles are `main_article`, `registry`, `supplement`, `sap`,
`protocol` and `other`. If you do not declare a `main_article`, the agent
identifies the main report from file contents. It leaves the role unresolved
rather than guessing.

When `nct` is set, preparing the batch fetches that record from the public
ClinicalTrials.gov API. Leave `nct` out to keep the run fully offline.

## Run the assessment

Start the host in the assessment folder. The server uses the folder it was
started in as its workspace.

- **Claude Code:** `/rob2-kit:rob2-assess <request>`
- **Codex:** mention `$rob2-assess` in your request, or ask for a RoB 2
  assessment.

Name the outcome in your request, and the time point if one matters. For
example: *"Assess risk of bias for all-cause mortality at 12 months in
TRIAL-A and TRIAL-B."* All trials in a batch share that outcome.

## Approve the proposal

When the proposal is ready, the agent asks for approval:

- **Hosts that support MCP elicitation** (such as Claude Code) show an approval
  prompt with the exact proposal. Accept it to approve, or decline it to keep
  the proposal pending.
- **Other hosts** report that approval is required. Approve from a terminal in
  the assessment folder:

  ```bash
  uvx --from git+https://github.com/AliSalman-et-al/rob2-kit rob2 review
  ```

  The command shows the proposal and records approval only after you type
  `yes`. If you installed the CLI with `uv tool install`, run `rob2 review`.

If you want a different result, tell the agent. It revises the proposal, and
you review the new version.

## Check, verify and archive

These commands use the `rob2` CLI. Install it with `uv tool install
git+https://github.com/AliSalman-et-al/rob2-kit`, or prefix each command with
`uvx --from git+https://github.com/AliSalman-et-al/rob2-kit`.

```bash
rob2 status
```

```bash
rob2 verify .rob2-kit/finalized/<bundle>.rob2.zip
```

Each bundle contains the canonical assessment as JSON, a static HTML report,
the selected evidence records and integrity hashes. `rob2 verify` checks every
hash, the scientific-pack descriptor and the RoB 2 algorithm outputs. The
dependency-free [`scripts/verify_bundle.py`](../scripts/verify_bundle.py)
performs the same checks without installing rob2-kit:

```bash
python scripts/verify_bundle.py path/to/bundle.rob2.zip
```

Bundles do not include source files. To keep the exact source bytes alongside
an assessment, archive them separately:

```bash
rob2 archive-sources --output sources.zip
```

```bash
rob2 verify-sources sources.zip
```

## Other MCP hosts

Any host that runs local stdio MCP servers and loads Agent Skills can use
rob2-kit.

1. Install the CLI:

   ```bash
   uv tool install git+https://github.com/AliSalman-et-al/rob2-kit
   ```

2. Register the server. The command is `rob2` and its argument is `mcp`. Set
   `ROB2_WORKSPACE` to the assessment folder if the host does not start
   servers in that folder. For example, a manual Codex configuration in
   `~/.codex/config.toml`:

   ```toml
   [mcp_servers.rob2]
   command = "rob2"
   args = ["mcp-codex"]
   env = { ROB2_WORKSPACE = "/path/to/my-review" }
   ```

   `mcp-codex` is the same server with one difference: rendered page images
   are returned with the receipt as text, because Codex otherwise drops the
   image in favor of structured content. Other hosts should use `mcp`.

3. Export the skill to the host's skill directory, for example:

   ```bash
   rob2 export-skill --output .agents/skills/rob2-assess
   ```

   Hosts that cannot read skill files can read the same guidance through the
   server's `read_guidance` tool.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| The host reports that the `rob2` server failed to start | The first launch downloads dependencies. Wait a minute, then reconnect the server (`/mcp` in Claude Code). |
| No trials are found | Make sure the host was started in the folder that contains `input/`, or set `ROB2_WORKSPACE`. |
| Approval cannot be requested | The host does not support elicitation. Use `rob2 review` as described above. |
| A trial is marked `unsupported_design` | The trial is cluster-randomized or crossover. The packaged RoB 2 variant covers individually randomized parallel-group trials only. |
| `rob2 verify` fails | The bundle was changed after finalization, or it was produced under different scientific guidance. Use the original bundle. |
| You want to start over | `rob2 discard` removes the active assessment state. It keeps `input/` and any finalized bundles. |
