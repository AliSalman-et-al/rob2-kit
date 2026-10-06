# Schema delivery root-cause audit

No inference, paid retry, full benchmark, field rename, answer coercion or intermediate accepted-answer state. This audit follows the exact latest DELIVER and An model-visible tool transcripts, not just the schemas that native MCP tests resolve.

## Actual invocation and exposed argument shape

Both models used `functions.exec` JavaScript with `tools.mcp__rob2__save_domain_judgment(...)`. This is generic code-mode proxy dispatch into MCP, not direct structured model function arguments and not `run_rsi`. CLI events simplify these nested calls to `mcp_tool_call`; that outer event alone does not establish what argument schema the model saw. Actual tool discovery used `ALL_TOOLS`. Focused subsequent listings in both rollouts exposed the declaration below without truncation:

```ts
mcp__rob2__save_domain_judgment(args: {
  answers: Array<unknown>;
  domain_id: "domain:randomization" | "domain:deviations" | "domain:missing" | "domain:measurement" | "domain:selection";
  expected_revision: number;
  revision_basis?: unknown | unknown | unknown | null;
  supersedes?: string | null;
  trial_id: string;
})
```

The native MCP input is strictly typed: answers items reference `#/$defs/DomainSaveAnswer`, whose properties include bases referencing `DomainEvidenceCitation`; evidence is one string and role is a closed enum. Counterpoints instead contain a nonempty evidence-handle array and an implication. Required per-answer fields are question_id, answer, justification, unknowns and counterevidence. Native definitions are complete; those nested requirements and the scalar-versus-array distinction were missing from the model-visible declaration. Tool descriptions partially describe the concepts, but cannot replace the lost typed fields. The input schema examples were not present in that generated declaration either. Initial broad discovery was truncated, but the later untruncated focused declaration rules out truncation as the sole explanation.

Server-wide `dereference_schemas=False` deliberately preserved large shared output definitions. It also left input references unresolved, and the observed host declaration rendered those objects as unknown. This is the concrete schema-delivery defect; behavior improvement after its correction remains unmeasured. Generic JavaScript does not type-check these unknown nested objects before forwarding them; runtime MCP/Pydantic rejects them. Its API method names are specific, so this is not an application-level generic scientific dispatcher or an application accepting arbitrary answers.

## Staleness and snapshot checks

Both launcher/config and saved turn_context identify exact gpt-6-luna / medium. Config uses the isolated home and explicit current checkout PYTHONPATH; tool calls reach the expected rob2 server. Input definitions of DomainSaveAnswer hash identically at5a3e580,9c7ba8c and3b5c51c: 50889407f7dcdf31c5731a342475c13735322ff9503f3e2fc1d312932c1221b0. The failures are consistent with that exact schema, not an older kind-tag or basis-index contract. models_cache contains model metadata (fetched_at, etag, client_version, identity, models), not tool schemas. Homes were isolated and the actual discovery declarations are retained. No positive evidence of stale schema/config/model cache or runtime/schema snapshot mismatch was found. The historical full tools/list wire response was not preserved in the paid rollouts; the native pre-fix schema here is explicitly a reconstruction at3b5c51c, whereas the code declarations and errors are directly captured observations. No false claim of recovering an unrecorded request is made.

## Actual malformed payloads and errors

DELIVER used every ordinary citation in this form:

```json
{"evidence_handle":"eh_f44a232fec5769fa","relationship":"direct_support"}
```

The actual error has20 paths: required evidence and role, plus forbidden evidence_handle and relationship, repeated over five citations. The model received the full4563-character JSON-wrapped error, including Pydantic URLs and input fragments; it was not truncated. It supplied no complete correct answer object or allowed-role inventory. The required/forbidden paths nevertheless identify the two renames. An operator-only offline control makes only those renames and validates the resulting DomainSaveAnswer objects without changing answers, reasoning, unknowns or counterpoints. It is not submitted and does not validate science. Thus repair from those errors was possible, but no model repair success was observed: DELIVER was expressly stopped at its first save result.

An instead used:

```json
{"role":"indirect_support","evidence":["eh_6a3a61395c2666c3","eh_0815ad60e1dc1f4e"]}
```

It received five string_type errors, full1287-character JSON-wrapped text, not truncation. It corrected once to separate objects containing scalar evidence handles. Its second draft passed shape validation and reached the scientific guard `complete_claim_has_unresolved_premise` for D2.6. An demonstrates a normal one-time construction correction followed by a different scientific failure, not an endless same-shape loop. Repeated first-attempt failures across cases are still an execution burden, especially when the visible schema says unknown. Raw calls and exact model-visible errors are retained in the paired minimal trace files.

Correct ordinary citation and joint counterpoint shapes are:

```json
{
  "bases":[{"evidence":"eh_0123456789abcdef","role":"indirect_support"}],
  "counterevidence":[{"evidence":["eh_0123456789abcdef","eh_fedcba9876543210"],"implication":"How these passages limit the inference."}]
}
```

## Implemented decision

Resolve references in input schemas only at tools/list, using FastMCP's own dereference utility; output schemas remain shared and byte-for-byte unchanged. Every advertised tool input is now self-contained, including active-answer required fields, scientific role enums and scalar/list distinctions. The existing strict runtime models, canonical mapping, Evidence ownership/delivery checks, active-path logic, scientific guard and atomic Domain transaction are unchanged. Unknown or malformed citations are not accepted as aliases.

For actual FastMCP argument-validation errors on save_domain_judgment, return concise defect paths plus one complete valid answer syntax example and the precise scalar/list distinction. The example is explicitly fictitious syntax, not a recommended answer or real Evidence. It does not rewrite the caller's payload. Other tool validation errors and scientific application repairs retain their existing paths. Input validation still occurs before the application is invoked, and rejected calls save nothing.

Across18 tools the compact input-plus-output schema size changes from470550 to475047 bytes, +4497 (about0.96%); the existing budget passes. Offline client tools/list confirms no input references remain and output schemas are unchanged. The same host's post-fix TypeScript declaration has not been captured without inference, so do not claim measured model use or successful production execution yet.

## Reconsidered question-local alternative

The earlier question-local audit said there was no generic dispatcher hiding the schema. That accurately described the native MCP operation but did not describe these actual code-mode declarations; this audit corrects that conclusion. Validating each unchanged malformed nested An answer individually does not test a flat primitive question-local tool and is not evidence against its construction benefit.

A flat typed per-question interface remains plausible. It could support host-owned provisional drafts and later assemble the existing complete atomic submission; accepted partial canonical state is not automatically necessary. Such a design still needs explicit handling of multiple citations with different roles, joint counterclaims, limitations and provenance, rather than silently flattening scientific relationships. No paid comparison has tested it. First repair the proven loss of existing field exposure and noisy errors; retain ADR0036 and source provenance. Do not reject a future primitive interface on the invalid unchanged-payload experiment, and do not introduce a staged state machine based on that experiment either. No extra question-local tool or new workflow state is introduced in this patch.

PDF recovery remains intact: unavailable captured bytes produce the explicit source-availability condition, and narrower verified queries never imply dossier-wide absence. Original labels and targets remain unchanged. Source-scope qualification is not an optimization blocker. No new paid test is authorized or launched here.

## Verification

66 focused tests passed:12 schema delivery/budget, public shape, valid provenance-derived save and scientific limitation controls;54 malformed-call, scientific premise, joint-counterpoint and source-availability controls. Ruff, ty and git diff checks passed. Exact first An and DELIVER malformed calls were replayed offline against cloned workspaces; both remain errors, now with a complete syntax example, and canonical state is unchanged. The only DELIVER field-renaming control was offline model validation, not a server save. The initial new schema test expected an unsupported sixth answer option; the expectation was corrected to the actual five-value enum before the12 checks passed. No underlying answer enum or scientific rule changed.
