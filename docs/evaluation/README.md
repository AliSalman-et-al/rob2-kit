# Evaluate a release

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
