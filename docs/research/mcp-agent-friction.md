# Reducing rob2-kit MCP agent friction

## Scope

This note investigates two failure modes observed in the clean-room CHAARTED
run: repeated invalid MCP arguments and very large repeated context payloads.
It uses only first-party MCP, MCP Python SDK, and OpenAI Codex/plugin guidance.

## Findings

### Put the callable contract in the schema

MCP tools are model-controlled and are discovered through their name,
description, and JSON input schema. The protocol defines `description` as the
human-readable explanation of the tool and `inputSchema` as the JSON Schema for
its arguments. It also permits an output schema for structured results.
Consequently, correctness-critical argument shape cannot depend only on a
separate skill document. [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

The MCP Python SDK derives a tool's description from its function docstring and
its input schema from type hints. It supports Pydantic models for structured
inputs, `Annotated[..., Field(...)]` for per-field descriptions and constraints,
and `Literal` for closed enums; invalid constraints are automatically reported
as validation errors. [MCP Python SDK: tools](https://py.sdk.modelcontextprotocol.io/v2/servers/tools)

OpenAI's tool-design guidance says every contract should define required and
optional fields, types, allowed values, limits, side effects, and recoverable
failure behavior. It specifically advises explicit inputs rather than making
the model guess identifiers or scope. [OpenAI: Define tools](https://developers.openai.com/plugins/plan/tools)

Actionable implications for rob2-kit:

- Represent every nested request with a named Pydantic model; avoid open-ended
  dictionaries at the MCP boundary.
- Add `Field` descriptions to opaque identifiers, cursor fields, search modes,
  offsets, and mutually exclusive branches. Put a short valid example in fields
  whose serialization is not obvious.
- Use enums or discriminated unions for finite alternatives. Encode numeric and
  length limits in the schema rather than relying on prose or rejection loops.
- Make each tool docstring say when it is used, its prerequisite state, and the
  next expected tool. Distinguish proposal, confirmation, result resolution,
  and classification tools explicitly.
- Return validation failures at field granularity and include the accepted
  shape or allowed values. Do not return a generic protocol error for a
  correctable argument error.

### Design metadata as an evaluated interface

OpenAI recommends descriptions that begin from user intent, distinguish similar
tools, and state limits or prerequisites. Parameter documentation should include
examples and allowed values. Metadata changes should be tested against labelled
direct, indirect, negative, incomplete, and edge-case prompts while recording
tool selection and arguments. [OpenAI: Optimize Metadata](https://developers.openai.com/plugins/guides/optimize-metadata)

For rob2-kit, preserve the clean-room transcript as a regression corpus. Add a
small golden set for each previously rejected call, then assert both tool choice
and a schema-valid first attempt. Change one metadata field at a time so an
improvement can be attributed rather than guessed.

### Keep routine results small and make detail fetchable

OpenAI's tool guidance asks tools to return stable identifiers and enough
structured information for follow-up calls, while excluding unnecessary data.
[OpenAI: Define tools](https://developers.openai.com/plugins/plan/tools)
The MCP protocol allows tool results to contain structured content and resource
links, so large supporting material can be returned by reference instead of
being embedded in every response. [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
MCP standard pagination applies to list operations such as `tools/list`; it
uses opaque cursors and server-selected page sizes. Domain-specific tool-call
results therefore need an explicit application-level cursor/limit contract if
they can be large. [MCP pagination specification](https://modelcontextprotocol.io/specification/draft/server/utilities/pagination)

Actionable implications for rob2-kit:

- Return a compact work item by default: state, required action, stable IDs,
  small candidate summaries, and an opaque cursor or handle for more detail.
- Do not repeat the full source inventory, run history, question pack, or prior
  evidence in each mutation response. Expose a bounded read for whichever
  detail the current step needs.
- Give search a documented `limit` plus opaque continuation cursor; return short
  snippets and stable `unit_id` values. Put full passages or visual payloads
  behind bounded reads/resource links.
- Keep response ordering deterministic and avoid echoing the submitted request
  unless it is required for the next decision.
- Measure uncached and cached input per successful workflow step, not merely the
  total run. Set budgets for response bytes, returned candidates, and first-call
  validity in the clean-room eval.

### Let the skill teach workflow, not restate schemas

Codex skills use progressive disclosure: only names and descriptions are loaded
initially, and the complete `SKILL.md` is loaded after activation. OpenAI advises
keeping each skill focused, writing imperative steps with explicit inputs and
outputs, and placing detailed policies, schemas, and examples in referenced
files. [OpenAI: Build skills](https://developers.openai.com/plugins/build/skills)

OpenAI also says an MCP-connected skill should tell the model which tools to use,
in what order, and how to handle missing or ambiguous results. The workflow
boundary should define expected input, steps, output, facts that must not be
inferred, and when to ask, stop, or decline. [OpenAI: Build skills](https://developers.openai.com/plugins/build/skills)

The existing split between `rob2-init` and `rob2-assess` is directionally sound,
but the assessment skill should make the happy path and recovery path more
operational:

1. State the exact tool sequence as a short state machine, keyed to returned
   statuses.
2. For each state, name only the next tool and the identifiers that must be
   copied verbatim from the prior result.
3. Add one compact example each for search, result resolution, classification,
   domain evidence, and domain answers in a progressively loaded reference.
4. Explain that a proposal candidate is not necessarily an issued
   classification source; classification must use only the IDs explicitly
   returned as issued by the relevant step.
5. Define bounded retry behavior for schema validation: inspect the field error,
   correct only that request, and do not restart or broaden the run.
6. Keep normative RoB 2 logic out of the skill, as it is now. The engine and
   pinned packs remain authoritative.

These instructions should complement, not compensate for, incomplete schemas.
If a valid request cannot be constructed from `tools/list` metadata and the
immediately preceding result, fix the tool contract first.

## Recommended verification

Run three layers after the changes:

1. **Schema snapshots:** assert every nested object is closed and described,
   enum values and constraints appear, and each tool has a useful description.
2. **Golden tool calls:** replay representative clean-room intents and require a
   schema-valid first call for the previously troublesome tools.
3. **Isolated end-to-end eval:** install the wheel into a fresh Codex home, run
   CHAARTED PFS, count rejected calls by tool, and compare per-step response size
   and token use with the `ec9073e` baseline.

The target should not be zero domain-level diagnostic outcomes. It should be
zero avoidable schema/issuance errors, bounded responses, and faithful terminal
behavior when evidence coverage is genuinely incomplete.
