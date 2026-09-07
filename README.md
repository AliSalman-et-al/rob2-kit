# rob2-kit

`rob2-kit` is a model-free FastMCP server for evidence-grounded Cochrane Risk
of Bias 2 assessments. Codex or Claude Code supplies the model loop. The server
captures trial sources, verifies selected evidence, applies deterministic RoB 2
logic, records immutable revisions, and exports independently verifiable
assessment bundles.

## Requirements

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/) for development and wheel builds
- Codex or Claude Code with local stdio MCP support
- One directory of authorized source documents for each trial

## Install

Install the command from a source checkout with `uv`:

```powershell
uv tool install --force .
rob2 --help
```

If `rob2` is not found, run `uv tool update-shell`, open a new terminal, and
try `rob2 --help` again. The installed package contains the `rob2` command, the
14-tool MCP server, and the portable `rob2-assess` skill. The v0.5 boundary
returns equivalent structured and serialized text results for MCP hosts.

To install a built release artifact instead, replace `.` with the wheel path:

```powershell
uv tool install --force dist/rob2_kit-0.5.0-py3-none-any.whl
```

## Prepare the workspace

Create one immediate subdirectory below `input` for each trial. This is the
same structure for one trial and for a batch:

```text
my-assessment/
└── input/
    ├── TRIAL-A/
    │   ├── main-article.pdf
    │   ├── registry.json
    │   ├── supplement.pdf
    │   ├── protocol.pdf
    │   └── sources.toml        # optional
    └── TRIAL-B/
        └── main-article.pdf
```

Supported source files are PDF, TXT, Markdown, CSV, and JSON. Hidden
directories, links, and unsupported files are not captured. Trial directory
names become stable trial identifiers, so keep them meaningful and do not put
unrelated directories under `input`.

Filenames provide a simple default role classification. Use an optional
`sources.toml` when a filename is ambiguous or when you have an authoritative
registry identifier:

```toml
nct = "<NCT-ID>"

[roles]
"article.pdf" = "main_article"
"appendix.pdf" = "supplement"
"analysis-plan.pdf" = "sap"
```

Valid roles are `main_article`, `registry`, `supplement`, `sap`, `protocol`,
and `other`.

When `sources.toml` contains an NCT identifier, `prepare_batch` sends that
identifier to the public ClinicalTrials.gov API and captures the returned
registry record as a searchable `registry` Source. The full returned JSON is
content-addressed with the local dossier, so registry methods and outcomes can
be selected as evidence. For navigation, JSON is projected as sorted path-value
lines such as `protocolSection.identificationModule.nctId: "NCT01234567"`;
the captured bytes and content identity remain unchanged. Replace `<NCT-ID>` with an authorized identifier
before you run the command. Do not declare an identifier unless that network
lookup is authorized. All other source capture is local.

## Connect the host

Set `ROB2_WORKSPACE` to the directory that contains `input`, then register the
installed command as a local stdio server.

For Codex, add this to the user `~/.codex/config.toml` or a trusted project's
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

Export the packaged skill from the installed command into the host's
project-scoped skill directory:

```powershell
# Codex
rob2 export-skill --output .agents/skills/rob2-assess

# Claude Code
rob2 export-skill --output .claude/skills/rob2-assess
```

The command exports the whole skill, including `references`, from either a
source or wheel installation. Restart the host if it does not discover the new
top-level skill directory in the current session. Confirm that the `rob2` MCP
server is connected before starting an assessment.

## Run an assessment

Invoke the skill with the outcome concept shared by the batch:

```text
/rob2-assess Assess risk of bias for the primary outcome across TRIAL-A and TRIAL-B.
```

The host discovers trial directories through `prepare_batch`; you do not list
files or construct trial records manually. It searches the main article first
for the reported result, checks the registry next for outcome identity, and
uses supplements, protocols, and statistical analysis plans for competing
definitions and methods. Within each source, FTS5 BM25 relevance and then page
order rank matches. A bounded result reserves the best match from each matching
source when space permits, then gives the remaining slots to earlier-ranked
sources. This keeps the main article primary without hiding a protocol or plan
behind many article pages.
This order is a discovery default, not an evidence hierarchy or permission to
skip the bounded cross-source check.

Search results are navigation only. `read_pages` returns numbered source lines,
and the host selects one contiguous range on one source page as evidence.
Every `search_sources` call declares its lexical intent: `all` requires every
term, `phrase` checks known contiguous wording, `any` performs broad OR
discovery, and `prefix` matches token prefixes. A broad, truncated `any`
response reports only observable counts and one executable next action (usually
an `all` refinement for multi-term queries or the issued cursor); it never
asserts scientific relevance or absence. No-hit and untruncated responses do
not receive that warning. Follow `next_cursor` to continue the same ranking.
Large pages return a bounded window and `next_start_line`; the host continues
the same page until `truncated` is false.
Selection uses only the returned page and inclusive line range. The server
creates one deterministic readable text projection during capture: Unicode
compatibility forms and ligatures are normalized, discretionary and hidden
formatting marks are removed, and PDF line-end hyphenation is resolved. Search,
page reads, and selected quotations therefore use the same text. The immutable
captured bytes remain the source authority. Figures, tables, and CONSORT
diagrams can be selected as visual evidence; text corroboration is preferred
when available.

When the proposal is ready, the host pauses at the only researcher gate and
presents the proposed Result mapping. Respond in the same Claude Code, Codex,
or other MCP client conversation:

- Reply `Approved` only when the proposed mapping is the Result you intend to
  assess. The host calls `request_proposal_approval`; the client displays the
  exact immutable Review and asks for direct confirmation before the server
  commits it.
- If a Trial uses the wrong source-reported Result, describe the intended
  construct in ordinary language. The host treats that text as search direction,
  not Evidence, rechecks the captured Sources, and submits one complete replacement
  card for that Trial. The server preserves the other Trial mappings. Review the fresh record
  before approving it.

Clients without MCP elicitation support retain the researcher-only CLI fallback:

```powershell
rob2 review --workspace C:/path/to/my-assessment
```

- Enter `yes` only when the proposed result is the result you intend to assess.
- Enter `no` when it is wrong or ambiguous, then give the host the same natural
  correction in conversation.

After approval, the host owns signaling answers and follows the server through
all five domains and finalization. Do not direct individual signaling answers.
The workflow completes one Trial at a time, in captured Batch order, and one
Domain at a time within that Trial. The server rejects attempts to start a
later Trial or new Domain before the current one is complete. Accepting the
fifth Domain automatically freezes that Trial's AssessmentSnapshot and marks
the Trial `assessed`; the next action then advances to the next Trial. No
separate Trial-finalization tool or host decision exists. `finalize_batch` only
packages the already-terminal Trial records. Every Trial in a Batch shares the
one outcome concept supplied to `prepare_batch`; a Batch cannot mix different
requested outcomes across Trials.

Long batches do not depend on one conversation fitting in one context window.
rob2-kit stores every approved Proposal and Domain checkpoint durably. After
automatic compaction, the host calls `get_status` and continues the exact next
action without replaying completed work. After a host restart, invoke the skill
again to do the same. Do not clear context manually at Proposal or Trial
boundaries: retained source knowledge remains useful, while normal automatic
compaction handles capacity. No context-management MCP tool is involved. Low
remaining context must never cause the host to skip searches, infer unfinished
judgments, or finalize early.

For each active question, the host performs a bounded, question-specific search
across the relevant sources before it claims that information is absent. A
current Result Evidence set is not proof that no other relevant evidence exists.
The Domain context includes every question card and its activation predicate,
plus a short typed set of executable query suggestions. Each suggestion gives
query text, lexical mode, an optional recommended Source role, and purpose. Suggestions
are retrieval vocabulary and alternatives, not a mandatory sequence; for
example, an exact-phrase `intention-to-treat` search is paired with the
independently executable `all randomized patients` wording.
The host computes the complete active branch from answers in the same save call;
the server ignores extra inactive branch answers.
While the current Trial remains pending, the host may revise one of its committed
Domain checkpoints when new evidence or a documented self-correction requires
it; the immutable history is retained. Once the fifth Domain freezes the Trial,
its AssessmentSnapshot is final.

Use these researcher commands for recovery and verification:

```powershell
rob2 status --workspace C:/path/to/my-assessment
rob2 verify C:/path/to/finalized-bundle.rob2.zip
rob2 discard --workspace C:/path/to/my-assessment
```

`discard` resets the active workflow for a new result choice. It does not alter
an existing finalized bundle.

## Output and source archives

Finalization writes a deterministic `.rob2.zip` under
`.rob2-kit/finalized/`. The bundle contains canonical JSON, static HTML,
selected evidence records, and integrity hashes. It excludes source files,
credentials, prompts, traces, and absolute paths.

Source bytes can be archived separately when the researcher explicitly needs a
portable source package:

```powershell
rob2 archive-sources --workspace C:/path/to/my-assessment
rob2 verify-sources C:/path/to/archive.sources.zip
```

## Public contract

The server exposes exactly these strictly typed FastMCP tools:

`prepare_batch`, `get_status`, `list_sources`, `search_sources`, `read_pages`,
`select_text_evidence`, `render_page`, `select_visual_evidence`,
`save_proposal`, `request_proposal_approval`, `get_domain_context`,
`save_domain_judgment`, `request_trial_terminal`, and `finalize_batch`.

The live `rob2://current-batch` resource is the restart-safe status projection.
Researcher authority enters through a directly accepted MCP elicitation or the
`rob2 review` CLI fallback, never through a model-facing field or tool argument.
The scientific pack retains each question's full nested official and operational
guidance. `get_domain_context` returns a compact typed question-card projection
with the complete official excerpt and locator plus the actionable operational
fields needed for answering. Operational safeguards supplement the official
source; they never replace it. Domain answers reference selected Evidence by
handle, and the server writes the exact stored quote or transcription into the
auditable checkpoint.

See [CONTEXT.md](CONTEXT.md) for the domain model and
[docs/release/README.md](docs/release/README.md) for reproducible contract and
wheel verification.

## Develop

```powershell
uv sync --frozen
./scripts/verify_v05.ps1
```

The verification script runs Ruff, ty, the four-worker pytest suite, runtime
contract checks, wheel construction, and independent verification of the built
wheel. Pytest uses four workers through the repository configuration; use
`uv run pytest -n 0` only when debugging a test that requires serial output.
