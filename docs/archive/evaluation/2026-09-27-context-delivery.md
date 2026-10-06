# Domain-context delivery profile (#474)

## Prespecification

The candidate omits empty `questions`, `evidence`, and `comparison_cards` arrays
from continuation-page JSON. Page zero, section identity, offsets, snapshot
digest, non-empty arrays, stable recovery, cursors, and the official scientific
view stay unchanged. The output contract defaults these arrays to empty, so the
pages should reconstruct to the same view.

Primary measure: structured-MCP response bytes summed per outcome run. The
candidate must reduce the median total by at least 10% across the three runs,
with no increase in serial `get_domain_context` calls. Report page-zero,
continuation, and unpaged calls separately. Count omitted empty-array bytes as
repeated scaffold. Do not call structured JSON bytes model tokens.

To accept a candidate, run a controlled assessment comparison. Freeze at least
30 held-out Trial/Result/Domain cases. Run two draws per arm. Keep the model,
effort, Sources, Result, pack, prompts, and stopping budget fixed. An
independent RoB 2 adjudicator reviews the blinded decisive premise. A second
adjudicator resolves disagreements. The rubric marks each decisive premise
valid or invalid, and records unsupported reassurance and concern separately.
Any worsening fails. A smaller or inconclusive sample cannot establish
non-degradation.

The installed-host profile uses the three ENZAMET runs from the 2026-09-27
issue-465 capture. Codex CLI 0.157.1 ran Luna Medium. These traces form a
transport baseline. They are not a paired candidate comparison and have no
independent premise adjudication. The JSONL has no per-call timestamps or
model-token records. The profiler reports both measures as unavailable.

## Reproduction

The raw captures remain in the original checkout. Run the profiler from the
issue worktree with the original capture path:

```powershell
$originalRunRoot = Join-Path $env:USERPROFILE 'Documents\Code\rob2-kit\eval\runs\2026-09-27\issue-465-e2e\runs'
uv run python scripts/profile_domain_context_delivery.py `
  $originalRunRoot
```

The checked-in [capture manifest](2026-09-27-context-delivery-captures.json)
contains trace hashes, complete snapshot digests, and aggregate measures. It
reports structured payload bytes, text content bytes, exact structured-text
copies, and non-text parts separately. The profiler does not emit prompts,
context bodies, Source contents, full workspace paths, or assessment answers.
Keep raw logs in the original checkout.

The small candidate can be checked against the public output contract and full
reconstruction with:

```powershell
uv run pytest tests/test_bounded_domain_context.py -k empty_delta_arrays
```

## Captured profile

The 19 snapshots reconstructed from these runs all matched their recorded
snapshot digests. They cover 65–69 Evidence items in the largest OS and AE
views, and each outcome includes questions with conditional activation. The
manifest records each snapshot's page count, Evidence and question counts, and
Result size.

| Outcome | Calls page zero / continuation / unpaged | Complete views | Repair receipts | Tool errors |
| --- | ---: | ---: | ---: | ---: |
| Adverse Events | 10 / 21 / 2 | 7 | 3 | 0 |
| Overall Survival | 6 / 18 / 0 | 6 | 3 | 0 |
| Progression-Free Survival | 6 / 17 / 1 | 6 | 0 | 0 |

| Outcome | Bytes page zero / continuation / unpaged | Total bytes | Candidate savings |
| --- | ---: | ---: | ---: |
| Adverse Events | 270,332 / 273,170 / 1,150 | 544,652 | 428 (0.079%) |
| Overall Survival | 168,202 / 224,647 / 0 | 392,849 | 370 (0.094%) |
| Progression-Free Survival | 166,454 / 167,323 / 609 | 334,386 | 348 (0.104%) |

The candidate would omit 59 repeated empty arrays and save 1,146 bytes across
1,271,887 serialized bytes. The weighted reduction is 0.090%; the median
per-outcome reduction is 0.094%. The captures contain no timing or token-usage
records. Repair receipts count all MCP tools in each run, not context-page
repairs. The traces contain no failed tool calls.

The traces contain 1,268,971 structured payload bytes. They contain no text
content parts, exact structured-text copies, or non-text content parts. These
are transport counts, not model-token estimates. No image or base64 part appears
in the captured `get_domain_context` responses.

## Decision

**No production change.** The candidate is checked for lossless reconstruction
and measured against the prespecified 10% threshold. It falls well short, so no
paired model comparison was run. The issue accepts no change when a candidate
has no material benefit. This is that case. The existing comparison launcher
also rejects `factor=context` because it has no context-delivery run control.
Decisive-premise validity and unsupported-answer rates are unmeasured. The
omission test confirms the output contract accepts this shape and restores
empty defaults. That does not establish scientific equivalence. The live
contract and historical verification remain unchanged. JSON bytes are not
reported as model tokens.
