# Issue #481: input-contract qualification

**Disposition: no production change.** The captured September 27 trace has repeated MCP argument-validation failures, but the proposed schema example has not been shown to reduce them on the supported host. Keep the strict typed contract and the current assessment skill. A lower byte count or a schema-valid example alone is not evidence of better scientific validity.

## Frozen observation

The primary sample is `eval/runs/2026-09-27/rob2-trial-benchmark-fresh-4e03e798/runs` (56 segments, 2,464 completed MCP-call records), from the `gpt-6-luna` medium-effort campaign. The separate `retry-attempt-2-peace1-pfs/runs` subtree has six segments and 120 calls; it is reported separately and is not pooled into the primary rate.

| Sample | Input-validation failures | Structured `outcome=repair` receipts | Runtime errors observed |
| --- | ---: | ---: | ---: |
| Primary 56-segment run | 86 / 2,464 | 61 (41 Proposal, 20 Domain) | 0 |
| PEACE-1 retry subtree | 3 / 120 | 4 (3 Proposal, 1 Domain) | 0 |

All 86 primary failures are FastMCP/Pydantic call-argument validation responses: `item.status="failed"`, a validation message in `item.result.content`, `structured_content=null`, and `item.error=null`. There are no top-level JSONL `error` events in either sample. This is not evidence of 86 server crashes or state writes. The 61 structured repairs are separate application responses from schema-valid calls. Other completed application outcomes include `review_required` and `condition`; those are not runtime failures.

Primary failure counts by tool:

| Tool | Failed calls | Observed recurring shapes |
| --- | ---: | --- |
| `validate_proposal` | 40 | Empty result arrays, missing/invalid discriminators, incomplete assessable cards, invalid relation values or empty rationales, and missing source Evidence. |
| `save_domain_judgment` | 37 | Seven obsolete `kind: evidence` basis tags; seven scalar counterevidence entries; four missing basis tags; three SHA-256 identities used in Evidence-handle fields; and three Evidence lists where one string is required. Other calls had different missing or wrongly shaped fields. |
| `prepare_batch` | 6 | Five requests supplied Result facets in the outcome-only field; one omitted a revision. |
| `read_pages` | 2 | One exceeded the page bound; one supplied unsupported `max_response_bytes`. |
| `get_domain_context` | 1 | One included an extra `missing_data.population_role` field. |

As a recovery proxy, the first observed Proposal call per outcome/trial path failed in 8 of 26 groups; the first observed Domain call per outcome/trial/domain target failed in 17 of 125 groups. Every one of those 25 first-failed groups later had a schema-valid call with application `outcome=success` for the same group. The grouping is a call-trace proxy: the JSONL does not record draft IDs, and a later accepted shape does not prove the answer was scientifically correct. There are 5 unfilled Domain targets relative to 26 × 5 because one case has no Domain call in this trace; their absence is not attributed here.

The retry subtree adds three validation failures (two Proposal and one Domain) and four structured repairs. Its requests are retries of one case and are not independent observations.

### Representative failed calls and recovery

Line numbers below are one-based JSONL lines; `item_N` is the host trace call ID. Each path is relative to the primary run's `runs/` directory.

| Trace location | Call sequence and result |
| --- | --- |
| `adverse-events/LATITUDE/phase-1.jsonl:28–44` | `validate_proposal` items 13–21 are nine sequential failed attempts. They cover empty `results`, missing or invalid `kind`, `kind="binary"`, incomplete assessable objects, invalid/empty relation fields, empty rationales, and applicability without source Evidence. Items 23 and 24 at lines 48 and 50 are schema-valid calls returning structured `repair`, not accepted Proposal saves. |
| `progression-free-survival/TITAN/phase-3.jsonl:32–42` | `save_domain_judgment` items 15–19 fail in sequence: missing `bases` (line 32), missing basis discriminator (34), obsolete `kind="evidence"` (36), missing direct-support Evidence (38), and Evidence supplied as a list (40). Item 20 at line 42 is a later successful save with typed bases and scalar handles. |
| `overall-survival/ARASENS/phase-2.jsonl:76–84` | Items 38 and 40 fail because `counterevidence` contains scalar index `2`; each reports two `DomainCounterevidence` validation errors. Item 42 is corrected to objects with `basis_index` and `implication` and returns `outcome=success`. This shows a shape correction, not scientific adjudication of the rationale. |
| `overall-survival/ENZAMET/phase-2.jsonl:109–117` | Items 56 and 58 fail because strings beginning `sha256:` are supplied where an `eh_…` Evidence handle is required. Item 60 at line 117 later returns `outcome=success` using handles. |
| `adverse-events/STAMPEDE/phase-3.jsonl:137–143` | Items 68 and 70 fail because `revision_basis.new_evidence.evidence` is a list where the field is a scalar string; line 137 also lacks the required rationale. Item 71 at line 143 passes argument validation but returns application `outcome=condition`; it is not counted as a successful Domain save. |

An example of an application repair, distinct from these input errors, is `adverse-events/ARASENS/phase-2.jsonl:35`, item 16: `outcome=repair`, code `answer_requires_direct_basis`. Its detail leaves the submitted answer unchanged and tells the host to add support or reconsider the answer from Evidence. It does not select a replacement answer. Across all 20 primary Domain repairs, later accepted saves are observed; eight changed certainty without changing direction after this repair code, and one direction change followed newly rendered/read Evidence. Those trace patterns require independent source adjudication before any repair-policy change.

## Current public contract and candidate disposition

The installed working tree reports package/server `rob2-kit 0.10.0`, FastMCP `4.0.3`, MCP `2.1.1`, and Pydantic `2.13.4`. The captured call records identify the server alias `rob2`, but do not retain the MCP initialize response, the host's `list_tools()` payload or cache version, or the skill content/hash. Current versions therefore freeze the inspected working-tree contract; they cannot prove which historical schema or cached skill the host had at each failed call.

At inspection time, `mcp.list_tools()` and `fastmcp.Client(mcp).list_tools()` delivered equal schemas for both tools. Canonical compact JSON was serialized with sorted keys, UTF-8, and `ensure_ascii=False`; the metadata hash covers `{name, description, input_schema}`:

| Tool | Description chars | Input-schema bytes | Metadata SHA-256 |
| --- | ---: | ---: | --- |
| `validate_proposal` | 708 | 28,901 | `4dcac7671685d0887febbfce8a72e5b1f8aacd0d671d974eb5b66f378917449a` |
| `save_domain_judgment` | 956 | 14,447 | `9a1441d3dfea123282320320c08c13e34c603cf54b30e856c563c8ddef2b40f8` |

The current Domain schema describes `counterevidence` entries with required integer `basis_index` and string `implication`. The existing answer example uses `counterevidence: []`; the field also accepts a valid nonempty list. Invalid examples such as scalar `[2]` fail through public `Client.call_tool` before state changes. Other public-boundary tests reproduce obsolete basis tags, a canonical identity in a handle slot, and list-valued Evidence fields. The invalid drafts leave `_state(workspace)` unchanged.

One candidate was tested and reverted: add a single compact nonempty `counterevidence` object to the optional field's schema `examples`. It validated against the Pydantic model and was delivered by the public Client; the serialized input schema grew by 117 bytes (14,447 to 14,564). The empty-list example remained available, so the candidate did not make counterevidence mandatory. These checks establish schema validity and delivery only. There was no supported-host A/B, no observed reduction in invalid calls, and no measured effect on scientific premise or answer validity. The candidate is therefore unqualified under #481's retain-current-design rule; the 117-byte example is not in production.

The current skill is 27,201 bytes with SHA-256 `c67eaa47b2dbe70aeaa7d1882caffa222df5b07fb2ec21003ff904020667a528`. It has no semantic version field. This hash is of the current source file, not a captured host-delivered copy.

### Later uncoached host observation

The separate [ENZAMET workflow check](2026-09-27-human-like-luna-medium-r1.md)
ran the same `gpt-6-luna` medium model with three short prompts and retained
two JSONL phases per outcome. Its phase metadata pins build
`475ef1e378b9f1c030a79e0b3f82aba0cf622ee5d7e383a237bbbbd139bd554d`,
exported skill SHA-256
`1e5e1258749c6dff3edd31716ea039cf31a7c62e1db92c2fdaed4ea30cb5ef9d`,
and a stdio `tools/list` inventory of 18 tools (inventory SHA-256
`b2bcba23d5036f336b72f864408ff111d0ec405b3352bb21ce2c4c905cda9469`).
The host then made typed calls to that server in the same sessions. This
establishes current-run delivery, but it does not reconstruct the historical
host cache for the 56-segment campaign.

OS made one failed `validate_proposal` call with a malformed Evidence handle;
AE made one with an extra field in the reported Result and two failed
`save_domain_judgment` calls with invalid basis tags. Each was followed by
accepted calls, and all three assessments finalized with verified bundles.
These are observational recoveries on the unchanged contract, not a
candidate/control comparison or evidence that the scientific answers improved.
The no-change disposition remains in force.

## Cost measurements and limits

Compact UTF-8 JSON serialization of the 86 primary failed calls' stored arguments totals 105,147 bytes; their stored result objects total 114,039 bytes. The separate three retry failures total 8,884 argument bytes and 1,322 result bytes. These are local JSON serialization sizes, not wire sizes or model-context tokens.

The 56 primary `turn.completed` records sum to 346,939,461 input tokens (334,552,576 cached), 1,219,323 output tokens, and 655,564 reasoning-output tokens. The six retry segments sum to 41,584,053 input tokens (39,865,856 cached), 169,602 output, and 88,407 reasoning-output tokens. Usage is reported at segment/turn completion and cannot be attributed to a particular failed call. No paid rerun or candidate/control host comparison was made; ENZAMET and other live trace examples above are observational recoveries, not paired comparisons.

## Reproduction

From the repository root:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_input_contract_481.py -q
.venv/Scripts/python.exe -m pytest tests/test_assessment_lifecycle.py tests/test_assessment_review_gate.py::test_new_evidence_revision_must_use_novel_evidence tests/test_domain_boundary_repairs.py::test_answer_scope_repairs_are_atomic_and_valid_replay_is_idempotent -q
.venv/Scripts/ruff.exe check src/rob2_kit/workflow_models.py tests/test_input_contract_481.py
```

The first command covers public schema delivery, optional structured counterevidence, six malformed Proposal/Domain shapes, and state preservation. The lifecycle command covers the full assessment lifecycle, source-driven new-evidence revision, and atomic application repair behavior. These local tests do not substitute for the missing paid host comparison.
