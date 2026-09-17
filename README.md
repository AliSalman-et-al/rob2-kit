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

The v0.9 workflow requires a fresh assessment workspace. Finish an active
assessment with the version that created it, or start a new workspace from the
original inputs. Historical finalized v0.5 through v0.8 bundles still verify
unchanged. See the [v0.9 upgrade boundary](docs/adr/0031-v0-4-evidence-first-interaction.md#v0-9-release-amendment).

Install the command from a source checkout with `uv`:

```powershell
uv tool install --force .
rob2 --help
```

If `rob2` is not found, run `uv tool update-shell`, open a new terminal, and
try `rob2 --help` again. The installed package contains the `rob2` command, the
19-tool MCP server, and the portable `rob2-assess` skill. The v0.9 boundary
returns one structured JSON result for MCP hosts; `render_page` may additionally
return image content.

To install a built release artifact instead, replace `.` with the wheel path:

```powershell
uv tool install --force dist/rob2_kit-0.9.0-py3-none-any.whl
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

Supported source files are PDF, DOCX, TXT, Markdown, CSV, and JSON. DOCX
projection covers ordinary paragraphs, table rows and cells in order, and
footnotes on synthetic page 1. Synthetic page 1 is not Word pagination, and
the projection does not extract every embedded object. Legacy `.doc` files are
reported as unsupported. Image-only PDFs remain Sources and can be recovered
with `render_page`, even when they have no searchable text. Hidden directories
and links are excluded by the input policy; ordinary unsupported candidate files
are reported as intake conditions. Trial directory names become stable trial
identifiers, so keep them meaningful and do not put unrelated directories under
`input`.

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

For a controlled replay, put the retained response in the Trial directory and
declare its identity under `[registry]` instead of making a new request:

```toml
[registry]
nct = "NCT01234567"
replay = "registry.json"
captured_at = "2026-08-01T12:30:00Z"
sha256 = "<SHA-256 of registry.json>"
provenance = "captured response retained from baseline"
```

The replay is validated against the NCT and hash, then exposed through the
same `registry/NCT...json` Source, sorted JSON leaf paths, search index, page
reader, navigation, and Evidence selectors. The original capture time is
preserved and no network lookup is made.

Evaluation case manifests may live below `eval/runs` while reusing a retained
source or registry capture below `eval/reference`. The RSI workspace preparer
allows those relative paths only within the repository's `eval` root, then
copies the listed bytes into the fresh workspace. It never copies an existing
assessment workspace.

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
`list_sources` shows every captured Source and any intake conditions or
declared omissions; pass a `source_id` to get literal heading and page-excerpt
navigation without running a search first. When several query inputs are
already known, `search_sources_batch` runs up to eight independent searches
with separate outcomes and cursors. A dependent reformulation waits for the
previous result.
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

Before saving a Proposal, the host calls `validate_proposal` with the complete
Result cards and one concise evidence assessment for each Trial. The host then
calls receipt-only `save_proposal` with the returned `reasoning_id` and
revision. To change a draft, repeat `validate_proposal`; do not resend cards to
`save_proposal`.

Only a comparative Result or complete group-bound values for both comparison
groups support assessment. A one-group profile is descriptive: retain its exact
passage as Evidence, report the missing comparator or estimate, and propose an
unavailable Result. Labels such as mITT, per-protocol, and as-treated do not by
themselves make an otherwise comparative Result ineligible.

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

After approval, the host owns signaling answers for supported trial designs and
follows the server through all five domains and finalization. Before every
Domain save, the host calls `validate_domain_assessment` with the complete active
draft and then calls receipt-only `save_domain_judgment` with its returned
`reasoning_id` and revision. The server checks structure, references, and
workflow requirements. A successful reasoning receipt does not establish
scientific correctness. Known designs outside the installed pack close as
`unsupported_design`; unresolved designs remain `needs_input` until source
information establishes the design and unit of randomization. Do not direct
individual signaling answers. Each question card lists the official answer values allowed
for that question. Submit the selected value directly as `answers[].answer`; the
server rejects values not permitted for the stated question. Repairs preserve
the submitted proposition and explain the unmet requirement without choosing a
replacement answer.
The workflow completes one Trial at a time in captured Batch order. Within the
current Trial, Domains can be assessed independently; the server rejects work
on a later Trial. The fifth Domain makes the Trial ready for review while
keeping its checkpoints correctable. `review_trial` binds the current approved
Result and exact checkpoint set; `close_trial` makes that reviewed outcome
immutable and advances to the next Trial or Batch finalization.
`finalize_batch` packages only closed Trial records. Every Trial in a Batch
shares the outcome concept supplied to `prepare_batch`; a Batch cannot mix
different requested outcomes across Trials.

The server computes the overall Trial label after the fifth Domain. It applies
this deterministic Cochrane rule:

- All five Domains are Low: the Trial is Low.
- Exactly one Domain is Some concerns and none is High: the Trial is Some concerns.
- Any High Domain, or at least two Some concerns Domains: the Trial is High.

The model and the researcher do not submit or override this aggregation. Review
the five Domain labels when you need the reasoning behind the Trial label.

The host reads main-report text at two checkpoints: before Proposal submission,
then after approval before the Trial's first Domain save. Each pass covers the
same prefix of the full captured Source, up to 65,536 UTF-8 source-text bytes per
report at whole-line boundaries. Longer reports retain explicit partial coverage
and navigation to unread material. The host uses targeted reads to resolve
relevant premises beyond that prefix.

rob2-kit stores approved Proposals and Domain checkpoints durably. After
compaction, the host calls `get_status` and recovers the approved Result and
current progress. After a host restart, invoke the skill to resume that process.
The host resumes an unfinished read pass and recovers needed passages that are
missing or uncertain in its current context. Earlier coverage proves earlier
delivery, not retained context; it does not trigger a full report reread for
every Domain. Low remaining context must never cause the host to infer unfinished
judgments or finalize early.

For an open Trial, `save_working_checkpoint` stores one replaceable, bounded
set of source-linked observations, interpretations, terminology, unread ranges,
open questions, and unfinished drafts. `get_status` returns those notes only
while the Trial's captured Source scope and exact Result still match. Missing
or stale notes require reorientation from the current sources. Re-read cited
passages before relying on them; working notes never become Evidence or commit
a Domain.

For each active question, the host performs a bounded, question-specific search
across the relevant sources before it claims that information is absent. A
current Result Evidence set is not proof that no other relevant evidence exists.
The Domain context includes every question card and its activation predicate,
plus a short typed set of executable query suggestions. Each suggestion gives
query text, lexical mode, an optional recommended Source role, and purpose. Suggestions
are retrieval vocabulary and alternatives, not a mandatory sequence; for
example, an exact-phrase `intention-to-treat` search is paired with the
independently executable `all randomized patients` wording.
Each Domain receipt also identifies the exact pack ID, version, and content hash.
Context cursors preserve the approved Result, pack, question view, preview, and
requested Domain checkpoint; searches and unrelated Domain commits do not stale
the existing page chain. Recoverable discovery candidates are omitted by default.
Use `include_candidates=true` on a fresh `get_domain_context` request to include
them, while the existing cursor continues its original snapshot.
The host computes the complete active branch from answers in the same reasoning
call; the server ignores extra inactive branch answers.
While the current Trial remains open, the host may revise one of its committed
Domain checkpoints when new evidence or a documented self-correction requires
it; the immutable history is retained. Saving the fifth Domain makes the Trial
ready for review, but it stays correctable. `review_trial` binds
the current approved Result and exact checkpoint set; `close_trial` accepts only
that review and then makes the outcome immutable.

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

`prepare_batch`, `get_status`, `save_working_checkpoint`, `list_sources`,
`search_sources`, `search_sources_batch`, `read_pages`,
`select_text_evidence`, `render_page`, `select_visual_evidence`,
`validate_proposal`, `save_proposal`, `request_proposal_approval`,
`get_domain_context`, `validate_domain_assessment`, `save_domain_judgment`,
`review_trial`, `close_trial`, and `finalize_batch`.

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
./scripts/verify_v09.ps1
```

The verification script runs Ruff, ty, the four-worker pytest suite, runtime
contract checks, wheel construction, and independent verification of the built
wheel. Pytest uses four workers through the repository configuration; use
`uv run pytest -n 0` only when debugging a test that requires serial output.

## Verify an RSI workflow

The qualification harness can run one frozen case through a paid model in two
phases. For example, a smoke test can use Luna at medium reasoning effort:

```powershell
uv run --no-project python scripts/run_rsi_case.py `
  --case eval/reference/qualification-cases/TRIAL-A.json `
  --prompt eval/runs/example/prompt.txt `
  --run-dir eval/runs/example-luna-medium `
  --phase 1 --model gpt-5.6-luna --effort medium
```

Approve the Proposal Review with the researcher-only `rob2 review` command,
then continue the same session with `Continue.` as described in
[`docs/evaluation/rsi.md`](docs/evaluation/rsi.md). Verify the resulting
`.rob2.zip` with `scripts/verify_bundle.py`. A successful smoke test confirms
that the model-facing contract completes without schema or Pydantic repair
loops; it is an operational check, not a population accuracy estimate.

For the full evaluation protocol, frozen case format, batch runner, scorer, and
denominator rules, see the [evaluation guide](docs/evaluation/README.md) and
[recursive assessment improvement guide](docs/evaluation/rsi.md).
