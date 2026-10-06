# Domain-boundary history handoff: offline feasibility

**Decision: no-go for a canonical-only reset prototype; conditional go for a separately authorized, one-boundary host-compaction comparison.** The logs demonstrate repeated delivery and retained prior conclusions, but not that stale history caused a scientific mistake. They do not establish how much history the provider retained after automatic compaction. A deterministic bundle based solely on saved judgments cannot presently certify preservation of all scientifically necessary observations. Do not add agents, change production defaults, or launch this plan merely because it is prepared.

## What was actually measured

`measure.py` reads only existing public completed event logs: EXSCEL's initial native turn and its same-session completed host recovery; MONARCH-2's October 1 **Code benchmark** proposal and assessment turns. No private rollout, authentication/configuration file, denied session path, hidden reasoning, model request or new session was accessed. Original trace hashes were checked unchanged. The EXSCEL session starts from an approved seed; earlier proposal history is not in its event projection. These measurements therefore are partial observed delivery totals, not a reconstruction of the entire model conversation.

Each completed tool is counted once; started items are excluded. History bytes serialize its arguments plus one structured result, avoiding duplicate textual rendering. Message text is included where emitted. Initial user/developer instructions, tool schemas, hidden reasoning, provider serialization and host compaction are excluded. Bytes are neither tokens nor measured live context size. Saved submissions are exact successful answer arguments (including warrants, unknowns, counterevidence and limitations), not a newly adjudicated scientific summary. They exclude full recovered evidence, official guidance, approval and source metadata. Do not mistake them for a deployable handoff.

At the first context call of each Domain:

| Case / Domain | Observed prior delivery bytes | First fresh context response bytes | Saved answer-argument bytes | Prior context calls | Working notes |
| --- | ---: | ---: | ---: | ---: | --- |
| EXSCEL D1 | 11,712 | 29,813 | 2 (empty list) | 0 | current |
| EXSCEL D2 | 167,654 | 31,430 | 1,633 | 3 | stale: canonical newer |
| EXSCEL D3 | 241,588 | 28,161 | 3,045 | 7 | stale: canonical newer |
| EXSCEL D4 | 323,886 | 30,393 | 6,874 | 11 | stale: canonical newer |
| EXSCEL D5 | 392,086 | 27,607 | 8,791 | 15 | stale: canonical newer |
| MONARCH-2 D1 | 158,149 | 22,465 | 2 | 0 | absent |
| MONARCH-2 D2 | 399,228 | 24,452 | 1,938 | 6 | absent |
| MONARCH-2 D3 | 514,217 | 26,891 | 4,892 | 10 | absent |
| MONARCH-2 D4 | 642,175 | 24,058 | 6,887 | 14 | absent |
| MONARCH-2 D5 | 704,654 | 26,445 | 8,734 | 18 | absent |

The first fresh response is only the first page, not the full paginated Domain context. Comparing it with all prior bytes does **not** estimate a reduction factor. Prior-domain wording, repeated scope and source content are demonstrably delivered repeatedly; some remain useful across Domains. At MONARCH-2 D5, 48 prior read windows represent 37 distinct exact windows. These are exact duplicate counts; overlapping but differently bounded reads are not collapsed. EXSCEL D5 has 16 exact windows with no exact duplication. Context pagination and repeated context calls remain in both histories. No semantic classifier labels all this material irrelevant.

Turn totals recorded by the CLI:

| Trace | Input | Cached input | Output |
| --- | ---: | ---: | ---: |
| EXSCEL initial native turn | 334,932 | 268,800 | 1,277 |
| EXSCEL resumed completed turn | 5,856,513 | 5,618,176 | 9,611 |
| MONARCH-2 assessment turn | 12,225,312 | 11,871,232 | 33,737 |

These sum repeated requests over a turn. They are **not** context length, cash cost, evidence of hitting a context limit, or proof of billing. EXSCEL's already-retained seven initial per-response telemetry records range from 32,021 to 62,256 input tokens; these include unknown host overhead and precede the resumed Domain completion. There are no per-response boundary token records for the completed recovery in the public events analyzed here. The MONARCH-2 proposal turn total remains in `measurements.json`; no usage-saving estimate is justified.

## Durable state versus conversation memory

At D5, successful EXSCEL prior answer submissions preserve nine unknowns; MONARCH-2 preserves eight unknowns and three counterevidence entries. Complete submissions are retained verbatim in measurements. Conclusions are prior scientific judgments, not established facts. Preserve their source basis and uncertainty when recovering them; later evidence may justify explicit revision.

EXSCEL's saved D3 NI questions and warrants remain in conversation when D5 later reads protocol physical 186–188, including the six-month endpoint rule and primary analysis/sensitivity plan. That is a potential anchoring opportunity, not a demonstrated causal failure: the later plan does not itself settle actual missingness or establish that D3 must change. A new context must preserve both the earlier limits and the opportunity to reassess them; it must not silently upgrade plan to performance or import Figure S9 performance evidence never read in that session. The intake/report registry identity conflict must also survive.

MONARCH-2's all-randomized target, narrower EP reported cohort, EN exclusions and protocol rationale must coexist. Dropping the target/report relation to obtain a shorter packet would reproduce the ambiguity investigated in the preceding audit. Prior blinding judgments must retain the protocol's possible inadvertent unblinding counterevidence.

At D5, 16 EXSCEL and 42 MONARCH-2 prior delivered windows are not fully reproduced in **cited selected** evidence as reconstructed from these event projections. This count includes uncited material, partial citations and duplicates; it does not prove those windows contain material counterevidence or are unavailable elsewhere. It demonstrates why copied citations alone cannot certify source completeness. Full main-report reads, images, newly discovered leads and unsaved interpretations can be omitted from saved judgments. They may be recoverable by source ID/page/lines or visual page, but recovery has to occur before relying on their contents.

Neither trace calls `save_working_checkpoint` in its analyzed turns. EXSCEL begins with current notes whose Domain bindings are empty, then Domain context correctly returns `stale/canonical_newer` after the first save. Current `working_checkpoint_status` retains those notes for reconciliation while identifying stale Domains; changed source/Result scope instead suppresses their contents. MONARCH-2 reports `absent/not_saved`. Existing skill recovery instructions already require `get_status`, exact next action, source recovery and preservation of uncertainty after compaction. They also explicitly say earlier read coverage proves past delivery, not retained contents. Thus the recovery **mechanism exists**, but it is not evidence that a complete fresh checkpoint automatically exists at every Domain boundary.

## Supported host mechanism and concrete interaction

Local `codex-cli 0.159.0` generated its app-server schemas without starting an assessment session. `thread/compact/start` is exposed and takes only `threadId`; retained schema is included. It offers no caller-supplied deterministic replacement-history or handoff field. The legacy `ContextCompactedNotification` is explicitly deprecated in favor of a `ContextCompaction` item. Public `codex exec` help exposes resume and fork but no compact subcommand. Resume continues the same history; forking is not a guaranteed history reset. A host app-server experiment can request same-thread compaction at an idle boundary; it may itself invoke inference and must be counted and separately authorized. No such call occurred here.

**Before:** one continuing assessment thread loads all D3 context pages, reads sources, saves D3, and immediately loads D4, later D5; earlier context, failed searches and prior conclusions remain in the observed transcript. Canonical state and approvals reside in the same workspace.

**After, opt-in host experiment:** at an accepted Domain save and idle host boundary, obtain authoritative status and canonical identities. Preserve complete current approved target **and** reported Result/relation, source inventory and projection hashes, all saved prior Domain findings with full warrants/limitations/unknowns/counterevidence, and current working notes with exact recovery locators. Reconcile stale notes against latest canonical Domain bindings instead of treating their drafts as current judgments. Explicitly retain material uncited leads and pending text/image recovery. If there is no complete checkpoint or source-recovery manifest, stop preparation rather than compact away the only copy of an observation. Request supported same-thread compaction. Then call `get_status` before any other workflow action, compare identities, and follow fresh `get_domain_context` pagination. Recover exact relevant source contents if absent or uncertain. Continue the same assessment with no new researcher approval and no new agent.

This is a conversation-history intervention, not another abbreviated context payload. Keep the entire normal active Domain context in both conditions. A model-generated compaction summary may retain irrelevant details or lose nuances; it is not equivalent to a deterministic canonical handoff. A standard fresh `codex exec` against the same approved workspace could eventually test a more complete reset, but would also change session identity, host initialization and cache behavior; it is not the preferred first experiment and is not authorized here.

Scientific provenance and authority remain in the unchanged workspace: batch/proposal/review acknowledgment identities, selected Result identity, source hashes, current scientific-pack hash, workflow revision and Domain checkpoint identities. A transcript reset cannot grant approval, modify the assessment target, finalize a Trial, reuse a stale revision or make drafts into canonical answers. Check those identities before and after; recover researcher authority only from original acknowledgments, never a generated summary. Copying a prose approval sentence is insufficient.

## Factual losses, usage tradeoffs and test decision

Potential losses are uncited contrary evidence, figure layout/legend continuity, query-negative stopping rationales, incomplete main-report recovery, source identity conflicts, and distinctions between reported/approved/planned/performed facts. Source locators enable rereading; they do not themselves convey the facts or prove scientific sufficiency. Conversely, retaining all prior outcomes as terse settled facts risks stronger anchoring than the original full warrants. Fresh context must carry uncertainty, not just labels.

Likely overhead: checkpoint/status calls, host compaction, fresh paginated context, and any needed text/image recovery. A cold restart may lose cache reuse; same-thread compaction may change caching too. A reduction in repeated-history input could be offset by compaction tokens and rereads. Count model responses (including compactor), per-response input/cache/output where exposed, recovery tool calls, elapsed time and all guards. Do not extrapolate dollar savings from the aggregate cached totals above. Keeping one thread avoids mandatory per-Domain agents, approval duplication and scheduling machinery.

**Small falsifiable plan, not a launch request:** prepare two identical disposable EXSCEL workspaces at the saved D3-to-D4 boundary, with exact historical target/approval/source identities and all delivered D1–D3 evidence recoverable. Freeze an independently checked source-recovery manifest covering uncited material too. Use the same implementation, guidance, model/effort, active Domain payloads and source access. Condition A resumes retained history; B uses an idle-boundary supported host compaction after the same state-preservation checkpoint. Stop both after D5 and Trial review, with at most one attempt each and no full benchmark. Do not inject expected case facts or desired risk labels into either model prompt.

Private criteria: (1) original approvals, target/report relation and source identity conflict remain explicit and unchanged; (2) prior unknowns/counterevidence remain available, and later plan evidence is not retroactively credited as previously read/performed evidence; (3) any scientific claim depending on missing text/images triggers exact recovery, with no fabricated count or transfer from mortality to composite availability; (4) later contradictory evidence prompts reconciliation or an explicit reason the prior judgment remains defensible; (5) no contrary evidence is lost merely to achieve fewer tokens. Failure is a falsified source/target/temporal claim or lost material uncertainty, not label disagreement. Independent reviewers should compare complete warrants and recovered evidence before considering label agreement.

Technical feasibility must be demonstrated offline first: every required saved field and source locator preserved, immutable canonical identities unchanged, complete recovery manifests in both branches, exact host compaction event and safe context-preservation output observable without denied-path access. If host compaction cannot expose enough preservation evidence, reject that experiment rather than inventing a custom reset API. No current canonical-only bundle is prototyped because this completeness condition has not been established. This is a reasoned preparation no-go, with a concrete route to a small scientific comparison, not a claim that reset context improves accuracy.

`measure.py` extraction and Ruff pass. Original files unchanged. No model calls, new sessions, production edits or benchmark were run.
