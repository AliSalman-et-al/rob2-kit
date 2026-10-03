# Host-owned completion contract — offline implementation

The failed EXSCEL run remains immutable and unfinished; no model call, approval, state repair or same-case resumption occurred in this change. Implementation belongs to the Codex host adapter, not model-free MCP or scientific decision rules.

## Evidence and ownership

EXSCEL's exact prompt explicitly requested all five Domains, decisive Trial review, closure and finalization. It stated actual approval was already recorded, scientific decisions were model-owned, continuations must be followed, and stopping boundaries were real blocker/finalization/guard. Its final message explicitly acknowledged unfinished reading/context and stopped. Valid read windows and next cursor were available. One malformed handle was successfully repaired. The trace does not demonstrate a transport failure, an instruction to hand off, or a missing approval. Installed skill already says continue after approval without progress confirmation and report only after finalized. There is no evidence-based reason to add more lifecycle prose to the scientific skill.

Allsop b54db92 also stopped voluntarily after opening D2, but its header next_action then omitted the exact context cursor and it attempted premature finalization. Source delivery was complete. EXSCEL bd92ec8 already had exact context cursors and only partial assessment reading, and never attempted finalization. They share an early host turn boundary; the same causal explanation is not established. A later separate Allsop invocation at544a523 completed D1–D5/review/closure/finalization after continuation changes, but prompt/policy/sampling confounds remain and its standalone verifier failed pack-descriptor matching. It demonstrates possible completion, not reliable one-turn completion or causal accuracy gain.

The one-invocation diagnostics terminate on a model turn exit. They appropriately call that unfinished but do not own the workflow. Existing `scripts/run_rsi_case.py` already classifies exit0 without a verified artifact as resumable rather than succeeded. The original read-only Code benchmark `run_human_benchmark.py` supports `codex exec resume SESSION` across up to12turns, with an actual external Proposal Review decision and sanctioned CLI acknowledgment. It lacks the new explicit no-progress/shared-wall contract. Installed Codex `exec resume --help` confirms supported same-session resume. No original Code runner/data were edited.

## Minimal supported adapter

`run_rsi_case.py` now has opt-in `--completion-resumes N` (default0) and `--completion-no-progress N` (default2). Opt-in requires existing `--timeout-seconds`: one shared deadline across all turns, not a refreshed timeout for every invocation. The reusable typed policy/driver is `scripts/workflow_completion.py`.

After an unfinished natural exit, it can invoke **the exact same session** with a generic continuation containing only authoritative pending-action metadata. It calls status, preserves source/Result/approval/runtime configuration, and never picks a scientific answer, edits a draft, acknowledges approval or creates a replacement session. Every turn is a separate billed invocation, not relabeled as one-turn autonomy. Existing runtime/selection/inventory checks remain in the adapter; default benchmark behavior and frozen protocols are unchanged. Enabling it is a declared host architecture/evaluation condition, not an accuracy-based retry.

Boundaries:

- **Complete:** authoritative phase finalized and artifact passes the existing standalone verifier. Scientific warrant correctness remains a separate audit.
- **Waiting for user:** authoritative next action has researcher authority. This includes fresh Proposal Review; no automatic approval, no loop across it. Already-approved assessment resumes ordinarily without asking again.
- **Blocked:** finalized artifact fails verification, status reports an explicit condition/error, or no callable host action is available. Do not repair or invent authority.
- **Aborted:** child timeout/nonzero exit, shared wall budget or changed/missing session binding. Preserve partial work and usage.
- **Unfinished:** valid host work remains after the finite resume/no-progress allowance or two consecutive identical failures. Model final prose is ignored for completion decisions.

Progress consists of workflow phase/revision/action or delivered-reading changes, or distinct successful non-status tool work. Status-only repetition and repeated identical calls do not reset the no-progress counter. This is operational progress, not semantic proof; novel searches can count, but the finite turn count/shared wall prevent infinite search loops. Native failed-item status is included even when error=null and only text error content exists, fixing the EXSCEL observer omission for future adapter runs. Failure classification uses receipt structure, not response-text regexes or reference labels.

The adapter preserves per-turn command, prompt, JSONL trace, stderr and final-message files, plus a completion ledger with session/status/progress/calls/usage and an aggregate trace for existing phase audits. Total provider turn usage is summed across every recorded turn. Cached input remains part of total input; do not charge it twice or equate it with uncached billing. Missing/partial token receipts remain unknown rather than zero-cost claims. A session mismatch is retained with its charged usage and stops. No standalone final message can make an execution succeeded.

Example for an **RSI-prepared** existing run, with its exact session and frozen runtime arguments retained:

```bash
python scripts/run_rsi_case.py \
  --run-dir EXISTING_RSI_RUN --phase NEXT_PHASE --session EXACT_SESSION \
  --prompt AUTHORIZED_FULL_WORKFLOW_PROMPT \
  --timeout-seconds 1200 --completion-resumes 2 --completion-no-progress 2
```

This permits at most three total invocations in that phase: initial plus two same-session resumes. Every invocation is recorded and charged. The EXSCEL diagnostic directory uses a different manifest/ledger format and is not silently converted to RSI input. Its old one-invocation authorization remains closed. A later integration validation needs a predeclared multi-turn policy and a compatible adapter, not a hidden relaunch.

This implementation supplies shared wall/finite turns/no-progress boundaries; it does **not** add hard token/tool/idle caps to RSI. Existing diagnostic monitors or a separately declared monitor remain necessary when those caps are required, and their counters must span every turn. Provider usage is telemetry, not a guaranteed billing ceiling. No larger benchmark or changed experimental selection was authorized by this patch.

## Offline checks and limitations

46focused tests passed: seven new completion tests plus existing RSI host/auth tests. The new cases exercise finalized verified/unverified, explicit blocked status, pending researcher gate (zero calls), unfinished progression, same-session binding, shared deadline, host abort, unchanged status/error loops, accurate summed turn usage, and the actual EXSCEL native failed receipt. Focused Ruff lint/format and types pass; a pre-existing probe_cleanup type inconsistency was resolved using the existing text-normalization helper, preserving declared string telemetry.

No paid inference validates the new host controller yet. Offline fake turns demonstrate state/authority/budget decisions, not scientific accuracy or reliable model completion. No full CI success is asserted; no CI wait/log retrieval, full benchmark or merge occurred. Latest actual EXSCEL usage remains1,275,511total tokens (1,269,267input;1,113,344cached;155,923uncached;6,244output),23MCPcalls across two authorized invocations; no new paid usage.
