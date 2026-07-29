# RoB 2 Kit v1 implementation backlog

**Status:** execution plan  
**Canonical requirements:** [V1-SPEC.md](V1-SPEC.md)  
**Last reconciled:** 2026-07-29

This backlog translates the canonical v1 specification into dependency-ordered,
independently verifiable GitHub issues. It does not replace the specification or
introduce new product decisions.

The sequence is deliberately preview-first. It reaches a safe, end-to-end build
for the owner and a small lab group before spending time on the full public-v1
assurance matrix. A ticket is complete only when its acceptance criteria pass;
being able to demonstrate a partial happy path is not enough.

## Sequencing rules

- Work only from unblocked issues. GitHub's native **blocked by** relationships
  are authoritative; the table below is a readable projection.
- Keep the Python application and domain layers authoritative. MCP, CLI, GUI,
  skills, and host adapters remain thin interfaces.
- Add the narrowest fixture that proves each behavior while implementing it.
  Do not postpone all testing to the release-gate issues.
- Do not split tickets merely by schema, file, or specification heading.
  Create a follow-up only when work can be independently reviewed and verified.
- Do not broaden v1 to cluster, crossover, adherence-effect, hosted inference,
  dense retrieval, or research-validation work.
- The private `eval/reference/` corpus may inform local testing but must not
  enter distributable fixtures or be treated as a correctness oracle.

## Dependency graph

```mermaid
flowchart TD
    foundation["Package architecture and canonical contracts"]
    logic["Logic and Guidance packs"]
    ledger["Workflow ledger and artifact store"]
    ingestion["Source custody and LiteParse coverage"]
    registry["ClinicalTrials.gov adapter"]
    evidence["FTS5 search and Evidence Bundles"]
    visuals["Visual inspection"]
    preparation["Autonomous preparation"]
    review["Review and sign-off GUI"]
    interfaces["Skill, MCP, CLI, and host adapters"]
    reports["Reports and verification archives"]
    preview["Hands-on preview gate"]
    hardening["Public-v1 automated assurance"]
    release["Public v1 release gate"]

    foundation --> logic
    foundation --> ledger
    foundation --> ingestion
    foundation --> registry
    ledger --> ingestion
    ledger --> registry
    ledger --> evidence
    ingestion --> evidence
    ingestion --> visuals
    evidence --> visuals
    logic --> preparation
    ledger --> preparation
    evidence --> preparation
    visuals --> preparation
    ledger --> review
    preparation --> review
    preparation --> interfaces
    review --> interfaces
    ledger --> reports
    preparation --> reports
    review --> reports
    interfaces --> preview
    reports --> preview
    registry --> hardening
    preview --> hardening
    hardening --> release
```

The ClinicalTrials.gov adapter can be built alongside source ingestion once
the ledger exists. It is required for the public-v1 claim but is not allowed to
delay the first local-PDF preview path.

## Implementation issues

| Order | Issue | Starts after | Independent proof |
| --- | --- | --- | --- |
| 1 | [Establish the Python package architecture and canonical revision contracts](https://github.com/AliSalman-et-al/rob2-kit/issues/14) | Immediately | Schema, hashing, dependency, and boundary property tests |
| 2a | [Implement versioned RoB 2 logic and guidance packs with deterministic evaluation](https://github.com/AliSalman-et-al/rob2-kit/issues/15) | Package contracts | Exhaustive conformance, invalid-state, trace, and mutation tests |
| 2b | [Implement the transactional workflow ledger and content-addressed artifact store](https://github.com/AliSalman-et-al/rob2-kit/issues/16) | Package contracts | Atomicity, lease, replay, corruption, and targeted-invalidation tests |
| 3a | [Implement project initialization, source custody, and LiteParse coverage](https://github.com/AliSalman-et-al/rob2-kit/issues/17) | Package contracts and ledger | Source/parse fixtures with typed coverage and failure isolation |
| 3b | [Implement the current ClinicalTrials.gov adapter and source projection](https://github.com/AliSalman-et-al/rob2-kit/issues/18) | Package contracts and ledger | Recorded HTTP/provenance fixtures and safe degradation |
| 4 | [Implement canonical evidence units, complete FTS5 search, and frozen bundles](https://github.com/AliSalman-et-al/rob2-kit/issues/19) | Ledger and source ingestion | Full pagination, exact-span, coverage, conflict, and bundle tests |
| 5 | [Implement relevance-gated visual inspection and typed transcriptions](https://github.com/AliSalman-et-al/rob2-kit/issues/20) | Source ingestion and evidence | Crop escalation, disposition, transcription, and ambiguity fixtures |
| 6 | [Implement the autonomous preparation work-item protocol end to end](https://github.com/AliSalman-et-al/rob2-kit/issues/21) | Logic, ledger, evidence, and visuals | End-to-end fixtures for all outcomes, resume, reuse, and batch isolation |
| 7 | [Build the evidence-first local review and human sign-off GUI](https://github.com/AliSalman-et-al/rob2-kit/issues/22) | Ledger and preparation | Security, stale-action, idempotency, evidence-first, and sign-off tests |
| 8a | [Expose the canonical skill, MCP and expert CLI through generated Codex and Claude adapters](https://github.com/AliSalman-et-al/rob2-kit/issues/23) | Preparation and review | Cross-interface contract and real-adapter equivalence tests |
| 8b | [Implement deterministic reports, exports, and verification archives](https://github.com/AliSalman-et-al/rob2-kit/issues/24) | Ledger, preparation, and review | Golden outputs and offline complete/reference archive verification |
| Preview gate | [Pass the dual-host hands-on preview gate on Windows](https://github.com/AliSalman-et-al/rob2-kit/issues/25) | Interfaces/adapters and reports/archives | Real Codex and Claude Code run plus owner/small-lab critical flow |
| Public hardening | [Automate the public-v1 trust, security, and portability gates](https://github.com/AliSalman-et-al/rob2-kit/issues/26) | Preview and current registry adapter | Cross-platform CI and a one-to-one acceptance-gate evidence matrix |
| Release gate | [Complete the public v1 release gate](https://github.com/AliSalman-et-al/rob2-kit/issues/27) | Public hardening | Frozen release manifest, named human checks, real-host checks, and verified archive |

## Milestone boundaries

### Hands-on preview

The preview gate is intentionally narrow but real. It requires the complete
local-PDF assessment, evidence review, human-only sign-off, reporting, resume,
and dual-host Windows path. It does not wait for broad usability research,
formal accessibility conformance, validation-study execution, or cosmetic
polish.

Issues discovered during owner/lab use should be triaged by consequence:
critical blockers and dangerous misunderstandings block the preview gate;
minor friction becomes normal follow-up work.

### Public v1

Public v1 adds the complete current ClinicalTrials.gov claim, cross-platform
package/core CI, adversarial and security coverage, all acceptance-gate
evidence, named human review of the Logic/Conformance transcription, and a
frozen cross-host release manifest. Research validation and manuscripts remain
outside this backlog.

## Changing the plan

The specification remains the authority. If implementation reveals a genuine
unresolved product decision, stop that issue and open a focused decision ticket
before changing behavior. If it only reveals more executable work, add the
smallest implementation issue, give it explicit acceptance criteria, and wire
its native dependencies. Avoid turning this backlog into a detailed project
management system.
