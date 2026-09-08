# Evaluate a release

## Import captured MCP observations

Freeze a manifest and the captured Codex JSONL transcripts, then run:

```powershell
uv run python scripts/import_mcp_observations.py --manifest import-manifest.json --transcript trace-a=capture.jsonl --output observations.json
```

Repeat `--transcript ID=PATH` for each capture. Use explicit mappings rather
than deriving Trial or Result identity from filenames. This minimal manifest
maps one transcript to one workflow attempt and host session:

```json
{
  "schema": "rob2-kit.observation-import-manifest.v1",
  "attempts": [
    {
      "attempt_id": "attempt-a",
      "transcripts": ["trace-a"]
    }
  ],
  "transcripts": [
    {
      "transcript_id": "trace-a",
      "attempt_id": "attempt-a",
      "session_id": "session-a",
      "phase": "assessment"
    }
  ]
}
```

Add frozen `trial_id`, `result_id`, `intervention_id`, `model` (with `family`
and `version`), and `kit_revision` to each attempt when known. Missing metadata
remains unknown. Split captures from the same session share `session_id`;
different sessions use different IDs so local call IDs cannot collide.
Declare phases consistently: `assessment` and `correction` searches contribute
to assessment-search reconciliation. When phases are supplied, the top-level
`searches` count uses those phases; otherwise it counts all observed searches.

The importer supports captured Codex MCP JSONL records for the documented
`rob2` tools. It is not a general transcript adapter. It emits
`rob2-kit.mcp-observations.v1`; identical manifest and transcript bytes produce
identical output. Repeated records for one session-local call reconcile to one
operation. Unmatched calls remain unmatched.

The observer is the captured transcript, supplemented by explicit manifest
metadata. Interpret its observation families as follows:

| Observation | What it establishes and its limit |
| --- | --- |
| Operation and request shape | A recorded tool call, known scope, and structural request facts. Query presence, cursor presence, and argument counts do not establish discovery quality. |
| Response identities and counts | Recorded delivery of recoverable response content, identities, hit counts, and truncation facts. These do not establish inspection, comprehension, or the unseen candidate cache. |
| Selection | Recorded Evidence selection, distinct from citation in an accepted answer. Selection does not establish premise support. |
| Attempted mutation | A recorded save request. Rejected or unmatched requests do not establish a commit. |
| Accepted commit and checkpoint | An observed accepted save and any captured checkpoint identity or supersession. These establish recorded state changes, not scientific correctness; absent canonical answer details leave citation scope unresolved. |
| Reconciliation | Counts of attempts, records, imported MCP records, ignored host records, and unique calls. Counts measure capture and workflow activity, not reasoning quality. |
| Terminal disposition | An explicit manifest disposition or observed disposition. It remains `unknown` when neither is available. |
| Capture status | The importer's completion classification from captured workflow events. It does not establish complete source coverage or successful scientific assessment. |
| Metrics | `response_bytes` measures recoverable captured JSON bytes, not wire bytes or model context. Unavailable cost, tokens, context bytes, and latency remain null. |

Output uses allowlisted structural fields and validated identities or hashes.
It excludes prompts, source text, quotations, rationales, raw queries, paths,
and reviewer identities. Structural errors identify the manifest field or
transcript record without echoing payloads. Keep the raw captures restricted.

This artifact is not input for the held-out v0.5 scorer. Expert premise
annotations and the restricted attempt, Result, Domain, and question mapping
remain external. Resolve that join explicitly under #282; do not fabricate
missing fields to fit the v0.5 schema. The importer implements the bounded
observation-capture slice in #295.

## Score and qualify a release

The provider-independent scorer is rerunnable without paid model calls:

```powershell
uv run python scripts/run_heldout_eval.py eval/synthetic-heldout.json
```

It emits only the privacy-safe `rob2-kit.held-out-evaluation.v0.5` receipt. In
addition to needed-passage recall/rank, it scores alternative Evidence sets,
required-premise support and handled contradictions, question/Domain/overall
confusions, exact five-Domain vectors, `no_information` separately from
workflow abstention, baseline denominators, observable trajectory events,
query repetition/overlap/novelty and progress-per-call, premise support-category
confusion, duplicate attempts, and all-attempt friction. Scoring cells use the
closed 11-part key: Trial, approved Result, outcome, Domain, question, run,
draw, model family/version, kit revision, and intervention. The manifest
freezes source/projection/corpus/result/model/prompt/skill/tool/scorer/budget
hashes, preregistered selection and primary metric, limits, and every attempt.
Restricted reviewer annotations and exact Evidence coordinates are accepted
only in restricted reference input and are recursively removed from receipts.
Adjudicated answer truth never comes from an attempt. Every trajectory event
and query names one frozen attempt; only the preregistered attempt can
contribute to its funnel and query metrics. Duplicate retries remain in the
audit but cannot change scientific numerators. A manifest can
declare development/holdout splits and source/projection fingerprints; any
extra split field or cross-split Trial/fingerprint fails validation. Receipts contain no source
text, reviewer identity, rationale, query recipe, or holdout adjudication.

For retrieval-recovery validation, report Domain reasoning alongside search
count, zero-hit count, widening actions offered and followed, and whether the
needed passage was discovered. Treat those as operational observations: one
widening action does not establish adequate discovery, and a stochastic rerun
does not justify promising a particular provisional agreement gain.

For renewed Domain 4 review, inspect the rationale against the approved event
and ascertainment method. Record whether it distinguishes assessor awareness
from susceptibility to influence, explains any influence mechanism, and keeps a
mixed-outcome passage tied to the approved outcome. Do not grade this review by
string matching, a predetermined Domain label, or one agreement delta.

Use the independent `scripts/verify_bundle.py` consumer to check each finalized
bundle. It does not import proposal or presentation code from the product. The
source-defined Result remains the researcher's choice, and the evaluator does
not prescribe endpoint mappings, terminal dispositions, or RoB 2 labels.

Keep each run in a fresh workspace outside the repository. Use neutral run
labels such as `run A`, `run B`, and `run C`, then add one canary run. Give each
workspace, project, server, and MCP connection a unique identity. Start with a
zero-source attestation, use one attempt per run, and keep the captured source
hashes identical across the runs. Repeat a run only after a documented external
interruption before product or host behavior.

The workflow has one researcher gate. Review the exact Result mapping at
`Proposal Review` before approval. After approval, resume the same host session;
the host owns the Domain answers and follows `head.next_action` through
finalization. Do not turn a conversational answer into scientific feedback
after the gate. Use only this minimal continuation:

```text
Continue.
```

For the restart run, stop after the Proposal Review record exists and before
acknowledgment. After the host restarts, compare the Proposal Review, Batch, and
Source-set identities. Retain a closed top-level `restart_proof` object with
`passed: true`, the run ID, and equal before-and-after identity hashes for all
three records.

For every completed run, verify the bundle:

```powershell
uv run python scripts/verify_bundle.py <finalized-bundle.rob2.zip>
```

The command checks the archive without importing the package or reading source
documents. Do not coach Domain answers. Audit the final output, then retain the
run receipt or discard it and restart without coaching.

After the runs finish, validate the retained receipt:

```powershell
uv run --no-sync python scripts/qualification_manifest.py validate eval/retained-evidence.json
```

To close a run record, validate it and write the privacy-safe receipt without
retaining its input location:

```powershell
uv run --no-sync python scripts/qualification_manifest.py generate eval/run-record.json eval/retained-evidence.json
uv run --no-sync python scripts/qualification_manifest.py validate eval/retained-evidence.json
```

The `rob2-kit.retained-evidence.v0.4` receipt stores commit and wheel hashes,
input identities, run metadata, bundle identities, verifier output, the
restart proof, and supported CI evidence. It rejects paths, source content,
prompts, credentials, and traces. A verdict of `all_green` requires every run,
the canary, the restart proof, and the CI record to pass validation.

Use a generic researcher prompt for each run. Replace only `{outcome}` with the
outcome concept under test:

```text
/rob2-assess Assess risk of bias for {outcome} across the trials in input.
```
