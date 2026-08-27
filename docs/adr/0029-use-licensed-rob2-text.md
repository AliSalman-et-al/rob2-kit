# Use the licensed RoB 2 text

Date: 2026-08-25

Status: Accepted

## Context

The project owner confirmed that rob2-kit has the rights needed to use the
RoB 2 text without licensing restrictions. This confirmation covers verbatim
use, including use in packaged scientific guidance, MCP responses, skills,
tests, and documentation.

ADR 0025 recorded a narrower confirmation for content needed by issue #184.
This decision replaces that scope limit for RoB 2 text.

## Decision

rob2-kit may reproduce and distribute the RoB 2 text verbatim when verbatim
text best preserves the scientific guidance. The implementation does not need
to paraphrase, omit, or shorten RoB 2 text to address licensing concerns.

Every packaged guidance item must still identify its RoB 2 version and source
location. These fields preserve scientific provenance and support review. They
are not licensing safeguards.

## Consequences

- The MCP and Assessment skill may supply the exact guidance needed to answer
  each signaling question.
- Tests may compare packaged guidance with the source text.
- Contributors must keep the guidance version and source location accurate
  when the source changes.
- This decision records the project owner's authority for rob2-kit. It does not
  make a claim about rights held by other projects or users.
