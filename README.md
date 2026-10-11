# rob2-kit

rob2-kit helps an AI coding agent carry out a Cochrane
[Risk of Bias 2 (RoB 2)](https://www.riskofbias.info/welcome/rob-2-0-tool)
assessment of randomized trials. Every answer has to be grounded in passages
it cites from your trial reports.

It has two parts that work together:

- **A model-free MCP server.** It captures your trial sources and checks every
  cited passage against them. It applies the official RoB 2 algorithms
  deterministically and records the full assessment history. When you finish,
  it exports a bundle you can verify.
- **The `rob2-assess` skill.** It guides the agent through the official RoB 2
  guidance one signalling question at a time.

The agent reads the reports and answers the signalling questions. The server
then computes the domain and overall judgments. You approve which result is
assessed before any domain work begins.

> rob2-kit supports systematic reviewers; it does not replace them. Check every
> judgment before you use it in a review.

## Install

The plugins start the server with [uv](https://docs.astral.sh/uv/getting-started/installation/).
uv is a single executable, and it downloads Python 3.11 or later if your machine
doesn't have it. Claude Code and Codex do not ship a Python of their own. If you
cannot install uv but have Python 3.11 or later, follow
[Other MCP hosts](#other-mcp-hosts) instead; that route works in Claude Code and
Codex too.

### Claude Code

```text
/plugin marketplace add AliSalman-et-al/rob2-kit
/plugin install rob2-kit@rob2-kit
```

### Codex

```bash
codex plugin marketplace add AliSalman-et-al/rob2-kit
```

```bash
codex plugin add rob2-kit@rob2-kit
```

Both plugins install the `rob2-assess` skill and the `rob2` MCP server. The
server starts with `uvx`. On first use, uv downloads its dependencies, which
can take a minute. If the host reports that the server failed to start,
reconnect it once the download finishes (`/mcp` in Claude Code).

### Other MCP hosts

Install the command-line tool with uv:

```bash
uv tool install git+https://github.com/AliSalman-et-al/rob2-kit
```

or with Python 3.11 or later and pip, preferably inside a virtual environment:

```bash
python -m pip install git+https://github.com/AliSalman-et-al/rob2-kit
```

Register `rob2 mcp` as a local stdio server, then export the skill into the
host's skill directory:

```bash
rob2 export-skill --output .agents/skills/rob2-assess
```

The [user guide](docs/user-guide.md#other-mcp-hosts) has the details.

## Assess trials

1. Create an assessment folder with one subfolder per trial under `input/`:

   ```text
   my-review/
   └── input/
       ├── TRIAL-A/
       │   ├── main-article.pdf
       │   ├── supplement.pdf
       │   └── sources.toml      # optional: roles and NCT number
       └── TRIAL-B/
           └── main-article.pdf
   ```

2. Start Claude Code or Codex **in that folder**, then ask for an assessment:

   ```text
   /rob2-kit:rob2-assess Assess risk of bias for all-cause mortality at 12 months in TRIAL-A and TRIAL-B.
   ```

   In Codex, mention `$rob2-assess` or simply ask for a RoB 2 assessment.

3. Review the proposed result for each trial and approve it when your host
   asks. If your host cannot prompt you, approve it from a terminal opened in the assessment folder:

   ```bash
   uvx --from git+https://github.com/AliSalman-et-al/rob2-kit rob2 review
   ```

4. The agent assesses the five domains. When it finalizes, two things are
   written:
   - a verifiable `.rob2.zip` bundle in `.rob2-kit/finalized/`, which is the record;
   - an **Assessment report** in `reports/<date>-<id>/`. Open its `index.html` in
     any browser. That Batch page shows each trial's assessed result and its
     D1–D5 and overall judgments. Each trial links to a page with every
     signalling question, the answer, the justification and the quoted passages.

Supported source formats are PDF, DOCX, TXT, Markdown, CSV and JSON. The
[user guide](docs/user-guide.md) covers the approval step, verification,
archiving and troubleshooting.

## `sources.toml`

Each trial folder may contain a `sources.toml`. Every key is optional.

```toml
# The trial's registration. If you leave this out, rob2-kit looks for the
# trial's own NCT number in the main report.
nct = "NCT01234567"

# Files in the trial folder that should not be captured. Give either a bare
# path or a path with a reason (duplicate, irrelevant, unreadable, restricted
# or other) and a rationale.
omissions = [
  "cover-letter.pdf",
  { path = "old-version.pdf", reason = "duplicate", rationale = "Superseded by article.pdf" },
]

# Source roles, by path relative to the trial folder. Roles: main_article,
# registry, supplement, sap, protocol, other.
[roles]
"article.pdf" = "main_article"
"appendix.pdf" = "supplement"
"analysis-plan.pdf" = "sap"

[registry]
# Also download the protocol and analysis-plan documents posted on
# ClinicalTrials.gov.
acquire_documents = true
```

TOML requires top-level keys (`nct`, `omissions`) to come before any `[table]`.

- **Main report.** Declare it as `main_article`. If you don't, the agent
  identifies it from file contents and leaves the role unresolved rather than
  guessing. File names are only navigation hints.
- **Registry lookup.** rob2-kit fetches the trial's ClinicalTrials.gov record
  when it knows the trial's NCT number. To turn the lookup off for a trial, add
  an empty `[registry]` table and no `nct`.
- **Offline registry record.** To use a saved ClinicalTrials.gov API record
  instead of fetching it, name the file and record where it came from:

  ```toml
  [registry]
  nct = "NCT01234567"
  replay = "registry.json"
  captured_at = "2026-01-15T10:00:00Z"
  sha256 = "<sha256 of registry.json>"
  provenance = "ClinicalTrials.gov API v2, downloaded by the review team"
  ```

Declare the registration once, either at the top level or under `[registry]`.
Unknown keys are rejected, so a typo fails loudly instead of being ignored.

## Scope

The packaged guidance covers individually randomized parallel-group trials and
the effect of assignment to intervention (intention-to-treat). Cluster-randomized
and crossover trials are recorded as unsupported designs and are not assessed.
The effect of adhering to intervention needs a Domain 2 variant that this
package does not include.

## Data handling

Trial sources stay on your machine. The only network request rob2-kit makes
on its own is the ClinicalTrials.gov lookup for a trial's registration (see
[`sources.toml`](#sourcestoml) to turn it off). Finalized bundles contain the
assessment, the cited passages and integrity hashes. They never contain the
source files, prompts, credentials or absolute paths. Your host's model
provider sees whatever the agent reads, under that provider's terms.

## RoB 2 guidance

The packaged signalling questions, algorithms and guidance text reproduce the
official RoB 2 tool for individually randomized parallel-group trials (version
of 22 August 2019). They are used with permission and keep their version and
source location for provenance. Cite the tool as:

> Sterne JAC, Savović J, Page MJ, et al. RoB 2: a revised tool for assessing
> risk of bias in randomised trials. *BMJ* 2019;366:l4898.
> doi:10.1136/bmj.l4898

## Cite rob2-kit

If you use rob2-kit, cite it using [`CITATION.cff`](CITATION.cff). GitHub's
"Cite this repository" button gives the same citation.

## License

rob2-kit is released under the [MIT License](LICENSE). The packaged RoB 2
guidance text is reproduced with permission and is not covered by that license.

## Development

```bash
uv sync --locked
```

```bash
uv run pytest
```

[`tests/e2e`](tests/e2e) drives the real `rob2 mcp` server over stdio the way a
host does. The [release guide](docs/release/README.md) covers the public tool
contract, wheel verification and release steps. Design decisions are recorded
in [`docs/adr`](docs/adr), and the [evaluation guide](docs/evaluation/README.md)
covers verification runs.
