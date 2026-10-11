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

You need [uv](https://docs.astral.sh/uv/getting-started/installation/)
(Python 3.11 or later is fetched automatically) and one of the hosts below.

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

Install the command-line tool:

```bash
uv tool install git+https://github.com/AliSalman-et-al/rob2-kit
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

4. The agent assesses the five domains. When it finalizes, a verifiable
   `.rob2.zip` bundle is written to `.rob2-kit/finalized/`.

The [user guide](docs/user-guide.md) covers supported source formats,
`sources.toml`, the approval step, verification, archiving and troubleshooting.

## Scope

The packaged guidance covers individually randomized parallel-group trials and
the effect of assignment to intervention (intention-to-treat). Cluster-randomized
and crossover trials are recorded as unsupported designs and are not assessed.
The effect of adhering to intervention needs a Domain 2 variant that this
package does not include.

## Data handling

Trial sources stay on your machine. The server contacts ClinicalTrials.gov only
when a trial's `sources.toml` gives an NCT number. Finalized bundles contain the
assessment, the cited passages and integrity hashes. They never contain the
source files, prompts, credentials or absolute paths. Your host's model provider
sees whatever the agent reads, under that provider's terms.

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
