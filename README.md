# rob2-kit

`rob2-kit` is a model-free FastMCP server for evidence-grounded Cochrane Risk
of Bias 2 assessments. Codex, Claude Code, or another MCP host supplies the
model loop. The server captures trial sources, validates evidence selections
against them, applies deterministic RoB 2 logic, records assessment history,
and exports verifiable bundles.

The v0.9 workflow requires a fresh assessment workspace. Finish an active
assessment with the version that created it, or start a new workspace from the
original inputs. Historical v0.5 through v0.8 bundles still verify. See the
[v0.9 upgrade boundary](docs/adr/0031-v0-4-evidence-first-interaction.md#v0-9-release-amendment).

## Use rob2-kit

### Requirements

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/) for development and wheel builds
- An MCP host with local stdio support
- One directory of authorized source documents for each trial

### Install

Install the command from a source checkout:

```powershell
uv tool install --force .
rob2 --help
```

If `rob2` is not found, run `uv tool update-shell`, open a new terminal, and
try `rob2 --help` again. The package includes the `rob2` command, a 19-tool MCP
server, and the portable `rob2-assess` skill.

To install a wheel instead, use its path:

```powershell
uv tool install --force dist/rob2_kit-0.9.0-py3-none-any.whl
```

### Prepare a workspace

Create one immediate subdirectory under `input` for each trial:

```text
my-assessment/
└── input/
    ├── TRIAL-A/
    │   ├── main-article.pdf
    │   ├── registry.json
    │   ├── supplement.pdf
    │   └── sources.toml        # optional
    └── TRIAL-B/
        └── main-article.pdf
```

The supported source formats are PDF, DOCX, TXT, Markdown, CSV, and JSON.
Image-only PDFs can be inspected with `render_page`. Legacy `.doc` files are
unsupported. Trial directory names become trial labels, so keep them
meaningful.

Filenames provide default source roles. Add `sources.toml` when a filename is
ambiguous or when you need to identify an authoritative registry record:

```toml
nct = "<NCT-ID>"

[roles]
"article.pdf" = "main_article"
"appendix.pdf" = "supplement"
"analysis-plan.pdf" = "sap"
```

Valid roles are `main_article`, `registry`, `supplement`, `sap`, `protocol`,
and `other`. When `sources.toml` contains an NCT identifier, `prepare_batch`
requests that record from the public ClinicalTrials.gov API. Use this only when
the lookup is authorized. Other source capture is local.

### Connect your host

Set `ROB2_WORKSPACE` to the directory that contains `input`.

For Codex, add this to `~/.codex/config.toml` or a trusted project's
`.codex/config.toml`:

```toml
[mcp_servers.rob2]
command = "rob2"
args = ["mcp"]
env = { ROB2_WORKSPACE = "C:/path/to/my-assessment" }
```

For Claude Code, run this from the assessment workspace:

```powershell
claude mcp add --transport stdio --scope project rob2 -e ROB2_WORKSPACE=C:/path/to/my-assessment -- rob2 mcp
```

Export the packaged skill to the host's project skill directory:

```powershell
# Codex
rob2 export-skill --output .agents/skills/rob2-assess

# Claude Code
rob2 export-skill --output .claude/skills/rob2-assess
```

The export includes the skill's reference files. Restart the host if it does
not discover the skill in the current session. Confirm that the `rob2` MCP
server is connected before you start an assessment.

### Run an assessment

Invoke the skill with the outcome shared by the selected trials:

```text
/rob2-assess Assess risk of bias for the primary outcome across TRIAL-A and TRIAL-B.
```

The host prepares the batch, searches the captured sources, and proposes one
Result for each trial. Review and approve that proposal before the
host assesses the five RoB 2 domains. The server computes the overall label,
then the host reviews and closes each trial before it finalizes the batch.

The proposal is the only researcher approval gate. If the MCP host does not
support elicitation, approve the exact proposal through the CLI:

```powershell
rob2 review --workspace C:/path/to/my-assessment
```

The packaged [`rob2-assess` skill](src/rob2_kit/skills/rob2-assess/SKILL.md)
contains the full assessment and recovery workflow.

### Verify and archive results

Finalization writes a deterministic `.rob2.zip` bundle under
`.rob2-kit/finalized/`. Each bundle contains canonical JSON, static HTML,
selected evidence records, and integrity hashes. It excludes source files,
credentials, prompts, traces, and absolute paths.

Check a workspace or verify a bundle with these commands:

```powershell
rob2 status --workspace C:/path/to/my-assessment
rob2 verify C:/path/to/finalized-bundle.rob2.zip
```

To archive the source bytes separately, run:

```powershell
rob2 archive-sources --workspace C:/path/to/my-assessment
rob2 verify-sources C:/path/to/archive.sources.zip
```

## Develop

### Public contract

The server exposes 19 strictly typed MCP tools and the live
`rob2://current-batch` resource. The generated [public contract](docs/release/public-contract.json)
records the tool catalog, schemas, annotations, resource families, and portable
skill pointers. See the [release guide](docs/release/README.md) for contract and
wheel verification.

### Run the project checks

```powershell
uv sync --frozen
./scripts/verify_v09.ps1
```

The verification script runs Ruff, ty, pytest with four workers, public
contract checks, wheel construction, and independent verification of the wheel.
Use `uv run pytest -n 0` when debugging a test that needs serial output.

### Evaluation

The [26-case RCT benchmark report](eval/runs/2026-09-26/rob2-trial-benchmark-luna-medium/trial-benchmark-report.md)
compares assessments with provisional catalog labels. Its scores are agreement
measures, not independently adjudicated estimates of scientific accuracy.

The [qualification ledger](docs/evaluation/issue-464-qualification.md) keeps
qualification on hold. See the [evaluation guide](docs/evaluation/README.md)
and the [recursive assessment improvement guide](docs/evaluation/rsi.md) for
the evaluation process.
