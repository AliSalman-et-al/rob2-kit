# Code audit findings

Scope: read-only audit of the active implementation, current agent skill, workflow/application boundaries, retrieval/projection integrity, scientific guidance, MCP metadata, and evaluation infrastructure. This is not an exhaustive line-by-line review of historical fixtures or every test. The task-level evaluation logs and label adjudication are handled in the companion audit.

## Findings

### No confirmed infrastructure defect found in the inspected paths

The architecture already supports a host-run ReAct loop. MCP tools expose source inventory/navigation, lexical and literal search, independent search batches, bounded reads, visual inspection, Evidence selection, context recovery, durable notes, assessment writes, review, and finalization (`src/rob2_kit/interfaces/mcp/server.py`). Search remains available during assessment; optional Domain/question purpose labels attribution without restricting how discoveries may be used. The model remains responsible for scientific sufficiency and answers; the server validates identity, provenance, activation, and structure (`src/rob2_kit/application/domains.py`, especially answer-basis validation around 2560-2687). This authority boundary is appropriate.

Source handling has several independent integrity checks: captured source bytes and projections are identified, persisted state payloads are verified, and the distributable projection verifier independently reproduces projection identity (`src/rob2_kit/application/_state.py`, `src/rob2_kit/projection_verify.py`, `src/rob2_kit/application/source_archive.py`). Search uses verified projections, exact-span localization, literal mode and optional spelling suggestions (`src/rob2_kit/application/evidence.py`). No demonstrated retrieval/projection bug was established in this pass.

The investigation checkpoint implementation binds notes to Trial, Result identity, and source projection hashes and marks dependent notes stale when those identities change (`src/rob2_kit/application/working.py:281`, `:307`, `:708`). The first-Domain write requires a fresh main-report pass only when the working checkpoint is not current (`src/rob2_kit/application/domains.py:2363`). This implements the intent of ADR 0032; the ADR still says “implementation pending.” A pre-Proposal checkpoint has no Result identity, so it becomes stale when the Proposal is committed (`working.py:60-75`, `:928-930`). A scratch end-to-end test using the existing public-MCP helpers confirmed the supported path: checkpoint status was `current` before Proposal save, `stale` after Proposal save, `current` after re-saving the same source-linked notes, and `current` after Proposal approval; the first Domain save then succeeded without the postapproval reread gate. The skill does not explicitly call out this rebind step. This is a narrow ergonomics/documentation gap; no new state machinery is needed. Existing `tests/test_read_first_workflow.py:461` demonstrates the fresh-pass-required path, but not the rebind/bypass sequence.

The evaluation layer records retrieval stages separately (`src/rob2_kit/evaluation/harness.py`, `coverage.py`, `observations.py`) and supports frozen paired comparisons, draw/retry provenance, support/completion/cost metrics and class recall. The evaluator explicitly warns that label agreement does not establish scientific accuracy. No measurement defect was confirmed.

### Public context surface measurements

Measured from `mcp.list_tools()` and UTF-8 serialized `tool.parameters`: 18 tools expose 73,082 bytes of input JSON schema and 11,811 bytes of tool descriptions (84,893 combined). Largest input schemas are `validate_proposal` (28,901 bytes), `save_domain_judgment` (14,447), and `get_domain_context` (8,301). Skill assets total 95,136 bytes: 27,201 bytes for `SKILL.md` and 67,935 bytes across nine on-demand references. The skill instructs opening domain references as needed; this is total asset size, not evidence that all references were injected into every call. These figures are inventory data, not proof of token use or an accuracy cause.

## Issue overlap and prioritization

The apparent evidence-to-claim gap (a structurally valid broad Evidence basis may not semantically entail a definitive answer) is already covered by issue #462 per task coordination; do not create a duplicate. Large context/tool overhead, retrieval attribution, model-effort comparisons, decisive-Evidence controls, and D2-D5 domain guidance are covered by #465-#469 and #455-#459/#461/#463/#464 as relayed by the parent. No additional implementation issue is recommended from this code-only pass without log-linked evidence.

## Review coverage

Read: repository `AGENTS.md`; `docs/agentic-search-spec.md`; `docs/adr/0032-host-owned-investigation-sufficiency.md`; agent skill and search/evidence references; MCP server/tool contracts; core Evidence, Domain, and working-checkpoint application paths; source projection/archive verification; scientific pack question guidance (spot checks); evaluation harness, coverage, adjudication, and observations modules (spot checks); host manifests; existing read-first workflow test. A scratch end-to-end test used the public MCP boundary and existing test helpers; it made no tracked code changes.

Spot-checked but not audited exhaustively: CLI, all application state transitions, all scientific questions and licensed source text, all tests/scripts, every run JSONL, PDF extraction fidelity, concurrency/error paths, and all historical design/ticket docs. The scratch checkpoint test passed (1 test, 9.50 s); no tracked files or production code were changed.



