# rob2-kit verification map

This directory is the maintained source for verifying what hosts and
researchers see from rob2-kit. Read this index before you drive the server, then
use the matching feature file as the recipe. The harness is described in
[../SKILL.md](../SKILL.md).

## Baseline preconditions

- `uv run python .agents/skills/verify-rob2-kit/doctor.py` passes.
- Every drive builds its own workspace in a fresh temporary folder with
  `tests/e2e/trial.py`. Never use a researcher's real assessment folder.
- The synthetic trials:
  - `prevent-tia` (`trial.build`): a double-blind, low-risk PDF trial with a
    protocol and a registry replay.
  - `knee-arthroscopy` (`trial.build_open_label`): an open-label text trial.
  - `dapa-glycaemia` (`trial.build_sparse`): a trial whose outcome was not
    assessed.

## Driving conventions

- Read `head.next_action` from `get_status` and follow it. Take
  `expected_revision` from `head.state_revision`, never from a stale receipt.
- Cite by literal quote (`agent.cite`) or by numbered line range
  (`agent.cite_lines`).
- Researcher actions go through the real CLI: `rob2(ws, "review", ...)` and
  `rob2(ws, "verify", ...)` from `tests/e2e/agent.py`.

## Proof and skip reporting

- Record the tool call and its result for every step (`agent.calls`
  becomes `transcript.jsonl`).
- Prove a mutation with a second, read-only view: `get_status`, the
  `rob2://current-batch` resource or the finalized bundle.
- Prove a rejection by its repair `code`, then show that state did not change:
  `state_revision` stays the same.
- Name the entry point you drove. A host path proven does not prove the CLI
  path, and the reverse also holds.

## Feature entry contract

Each feature file starts with an H1 title and a one-paragraph description. It
then has exactly four H2 sections, in this order: `Sub-features`,
`How to get to it (user POV)`, `Driving it with the e2e Agent` and `Gotchas`.

## Features

- [Intake and source navigation](./intake-and-navigation.md): `prepare_batch`, sources, reading, search, rendering and evidence selection.
- [Proposal and researcher approval](./proposal-and-approval.md): `validate_proposal`, `save_proposal`, the reading gate and the approval routes.
- [Domain assessment](./domain-assessment.md): domain context, saving answers, algorithm judgments, adjudication and resume.
- [Close, finalize and verify](./finalize-and-verify.md): trial review, finalization, both verifiers, tampering and source archives.
- [Assessment report](./assessment-report.md): the Batch and Trial pages rendered at finalize, `rob2 report`, and refusal of unverified bundles.
- [Codex entrypoint and plugin install](./codex-and-plugins.md): `rob2 mcp-codex` images and the Claude Code and Codex plugins.
