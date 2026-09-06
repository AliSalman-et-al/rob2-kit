# Accuracy and agent-workflow patterns for rob2-kit

## Purpose and evidence labels

This note identifies model-agnostic changes most likely to improve scientific accuracy and agent ergonomics in rob2-kit's evidence-first RoB 2 workflow. It assumes the accepted boundaries in [ADR 0031](../adr/0031-v0-4-evidence-first-interaction.md): the server owns exact source identity, deterministic projections, state, validation, and RoB 2 logic; the host owns scientific interpretation; Proposal Review remains the only researcher gate; and the public surface remains 14 tools unless evaluation justifies a later contract change.

Each recommendation is marked as one of:

- **Source-supported**: directly supported by a cited paper, specification, documentation, or source artifact.
- **Inference for rob2-kit**: a proposed application to this domain. It has not itself been validated on RoB 2 assessments.

The central conclusion is deliberately conservative: improve the deterministic retrieval controller, state projections, schemas, and evaluation before adding new model loops or semantic retrieval. Pi-Serini's evidence is strong for the importance of retrieval depth and interface design, but it is one study on BrowseComp-Plus, not proof that its BM25 settings or effect sizes transfer to trial reports or RoB 2.

## Ranked recommendations

### 1. Retrieve broadly, reveal narrowly, and preserve exact handles

**Source-supported.** Pi-Serini separates search, ranking inspection, and document reading. A search caches up to 1,000 ranked documents under a `search_id`, initially shows only five excerpts, supports rank pagination without rerunning retrieval, and reads documents with line pagination. This separates retrieval depth from context consumption ([paper, Section 3.2](https://arxiv.org/html/2605.10848v1#S3.SS2); [paper PDF](https://arxiv.org/pdf/2605.10848)). Its ablation found that increasing retrieval depth from 5 to 100 raised surfaced evidence recall from 70.5% to 86.22%, while depth 1,000 reached 95.8%; previewed recall saturated much earlier, demonstrating that a deep candidate cache need not become a large prompt ([paper, Section 6](https://arxiv.org/html/2605.10848v1#S6)).

**Inference for rob2-kit.** Keep the existing `search_sources` -> `read_pages` -> exact Evidence-handle design, but tune it as a retrieval controller:

- Search every relevant Source projection deeply and retain the full Trial-scoped ranking outside model context.
- Return a small, diverse first page containing `source_id`, page/line coordinates, concise preview, rank, query/receipt identity, and `passage_ref`.
- Let the host page through the same cached ranking rather than reformulate a query merely to see lower-ranked hits.
- Preserve current exact Evidence semantics: rankings and previews are discovery aids; only source-bound selected passages or visual regions become canonical Evidence.
- Make cached-result lifetime and eviction visible in responses so a host can distinguish an exhausted ranking from an expired handle.

This is the highest-leverage pattern because it raises the evidence ceiling without consuming the context needed to compare premises and answer signaling questions.

### 2. Tune deterministic preprocessing and lexical retrieval against RoB 2 tasks

**Source-supported.** Under a fixed timeout, Pi-Serini's change from default BM25 parameters `(k1=0.9, b=0.4)` to `(25, 1)` increased answer accuracy from 64% to 82%, surfaced recall from 84.6% to 95.7%, and slightly reduced cost in its reported ablation ([paper, Section 6](https://arxiv.org/html/2605.10848v1#S6)). The repository exposes BM25 settings and a systematic tuning command instead of treating retrieval defaults as universal ([Pi-Serini README](https://github.com/justram/pi-serini#bm25-tuning-during-benchmark-runs)).

**Inference for rob2-kit.** Do not copy `(25, 1)`. Tune the existing versioned FTS derivative on a held-out RoB 2 corpus using rob2-kit-specific needed passages. Candidate variables include tokenization, field weighting, hyphen/ligature normalization, table projection, query expansion from question cards, per-Source-role priors, ranking depth, preview length, and page-window size. Keep capture and Evidence authority unchanged and deterministic; only the disposable discovery index and retrieval policy should vary.

Begin with lexical baselines. Add dense retrieval, reranking, or model-generated query expansion only if a held-out ablation shows incremental needed-passage recall or rank improvement that survives across model families and does not damage reproducibility. Pi-Serini shows that a poorly tuned baseline can make a more complex retriever look necessary; it does not establish that lexical retrieval is universally sufficient ([abstract](https://arxiv.org/abs/2605.10848)).

### 3. Make each tool response a compact next-action packet

**Source-supported.** MCP tools define JSON Schema inputs and optional output schemas. When an output schema is declared, the server must produce conforming `structuredContent`, and clients should validate it. For compatibility, structured results should also be serialized in a text content block ([MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#output-schema)). MCP distinguishes malformed protocol requests from tool-execution errors; actionable `isError: true` results allow the model to repair and retry ([MCP error handling](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling)). Pi-Serini likewise keeps tool parameter/result schemas at the extension boundary and recommends narrow error metadata plus repair instructions rather than generic failures ([contract documentation at the studied revision](https://github.com/justram/pi-serini/blob/bbab25da84e8b0651e492bcde4c11423208bdf3c/docs/pi-search-contract.md)).

**Inference for rob2-kit.** Standardize every successful response around five fields, omitting those that are irrelevant:

1. `state`: current phase, Trial, state revision, and immutable record identities.
2. `result`: the requested data, with closed typed unions and no duplicated source claims.
3. `next_action`: one legal next tool, its purpose, and which returned handles/revision to pass.
4. `progress`: remaining Trials, Domains, active questions, or pagination state.
5. `warnings`: typed scientific or operational caveats, never hidden in prose.

Standardize recoverable failures as `code`, `message`, `field_path`, `retryable`, `current_revision` when relevant, and a concrete `repair` packet. Examples: an unknown `passage_ref` should direct the host to rerun or resume search; a stale revision should return the current revision and recovery tool; an inactive question should identify its governing predicate. Keep the compact JSON text fallback already accepted in ADR 0031. Do not rely on prose parsing for downstream state or evaluation.

Tool annotations such as `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint` can improve client UX, but MCP defines them only as untrusted hints, not enforcement ([MCP schema](https://modelcontextprotocol.io/specification/2025-11-25/schema#toolannotations)). rob2-kit should still enforce authority, revision, and idempotency deterministically.

### 4. Project complete domain work in one read and accept it in one write

**Source-supported.** Effective agent tools should have distinct purposes, return relevant context rather than bulk data, and may consolidate frequently chained operations behind one call. Too many overlapping tools distract agents, while context-assembling tools can remove redundant calls ([Anthropic tool-design guidance](https://www.anthropic.com/engineering/writing-tools-for-agents#principles-for-writing-effective-tools)). Tool definitions should state examples, edge cases, input requirements, and boundaries, and argument design should make mistakes difficult ([Anthropic ACI guidance](https://www.anthropic.com/engineering/building-effective-agents#appendix-2-prompt-engineering-your-tools)).

**Inference for rob2-kit.** Preserve `get_domain_context` as the single recovery/read projection and ensure it is sufficient to answer the whole dependency-closed Domain without repair-driven discovery. It should include:

- approved Result and relevant Source roles;
- all active question cards plus parent answers needed to evaluate predicates transitively;
- official guidance, clearly separate operational guidance, and locators;
- current and prior checkpoint Evidence relevant to the Domain;
- search receipts and explicit gaps by active question;
- typed arithmetic reconciliation where applicable;
- exact save schema, revision basis, and next action.

`save_domain_judgment` should accept all active answers atomically and ignore inactive extras as already specified. Server-side activation, arithmetic, provenance binding, deterministic judgments, and idempotent retries remove decisions the model should not make. Avoid adding per-question orchestration tools: they increase tool choice and round trips without adding scientific authority.

### 5. Add deterministic pre-save critique, then one bounded model self-review only where it pays

**Source-supported.** Programmatic gates are useful between decomposed steps, while evaluator-optimizer loops are appropriate only when criteria are clear and iteration adds measurable value ([Anthropic agent patterns](https://www.anthropic.com/engineering/building-effective-agents#workflow-evaluator-optimizer)). Agents also need ground truth from the environment at each step to assess progress ([same guidance](https://www.anthropic.com/engineering/building-effective-agents#agents)).

**Inference for rob2-kit.** Run a server-generated preflight before committing Proposal or Domain work. It should deterministically report, in one response:

- missing source bindings, active answers, or required premises;
- invalid Evidence scope, expired handles, and stale revision;
- unsupported absence claims without bounded question-specific discovery;
- plan-as-conduct, endpoint-label-as-property, or other already codified category violations detectable from structured fields;
- contradictory selected passages that must be acknowledged, without deciding which passage is scientifically correct;
- next repair actions grouped to minimize calls.

Then ask the same host loop for at most one structured self-review: `confirmed` or `self_correction` with changed answers and reasons. A second model, voting scheme, or open-ended critic loop should not be the default. Introduce one only if held-out evaluations show a meaningful gain beyond the deterministic preflight, because extra model calls add latency, cost, and opportunities for untraceable drift.

### 6. Treat context as a rebuildable projection of canonical state

**Source-supported.** Pi-Serini keeps ranked results in external state addressed by a compact handle and logs separate surfaced, previewed, opened, and cited sets ([paper, Section 3.2](https://arxiv.org/html/2605.10848v1#S3.SS2)). Its run snapshots freeze resolved benchmark configuration, input hashes, and source revision so later evaluation does not silently adopt current defaults ([Pi-Serini reproducibility documentation](https://github.com/justram/pi-serini/blob/bbab25da84e8b0651e492bcde4c11423208bdf3c/docs/reproducibility.md#run-manifest-snapshots)).

**Inference for rob2-kit.** Continue to make canonical SQLite state authoritative and host context disposable. On restart, `get_status` plus `get_domain_context` should reconstruct a bounded working set with stable Evidence identities, current revision, completed decisions, unresolved gaps, and one next action. Do not ask the model to summarize state that the server can project exactly.

For prompt-cache friendliness and cross-host consistency, keep the static prefix stable: tool order, tool descriptions, RoB 2 pack version, and fixed workflow instructions should not vary per call. Put changing state after that prefix in deterministic key order. This is partly inferred from Pi-Serini's reported prefix-cache-efficient loop, not a requirement of MCP ([paper introduction](https://arxiv.org/html/2605.10848v1#S1)).

### 7. Calibrate uncertainty to evidence sufficiency, not fluent confidence

**Source-supported.** Pi-Serini evaluates calibration error between self-reported confidence and empirical correctness, separately from accuracy and retrieval recall ([paper, Section 4.1](https://arxiv.org/html/2605.10848v1#S4.SS1)). Its evaluation distinguishes system-surfaced, agent-previewed, and opened/cited evidence, because availability, inspection, and use are different failure points ([paper, Section 3.2](https://arxiv.org/html/2605.10848v1#S3.SS2)).

**Inference for rob2-kit.** Do not add a single free-form confidence percentage to scientific answers. Prefer a typed sufficiency assessment per answer or Domain:

- `supported`: direct or indirect Evidence addresses every required premise;
- `limited`: an explicit limitation or bounded absence receipt remains;
- `conflicted`: material sources disagree or plan/conduct status is unresolved;
- `not_assessable`: required facts remain unavailable.

The host should state which premise drives uncertainty and cite its basis. Evaluate whether these categories predict error or abstention utility. Preserve RoB 2 response options and judgments as the scientific outputs; sufficiency is diagnostic metadata, not a replacement scale.

### 8. Evaluate the causal chain, not only the final RoB 2 label

**Source-supported.** Pi-Serini explicitly separates retrieval evaluation from judge evaluation because evidence surfaced and answer correctness are different questions ([evaluation documentation](https://github.com/justram/pi-serini/blob/bbab25da84e8b0651e492bcde4c11423208bdf3c/docs/evaluation.md#two-evaluation-families)). Its trajectory tiers localize whether evidence was available, shown, opened, or cited. Agent-tool guidance recommends realistic held-out tasks, verifiable outcomes, raw transcript review, and metrics for calls, errors, tokens, and latency; it cautions against overspecifying one valid path ([Anthropic tool-evaluation guidance](https://www.anthropic.com/engineering/writing-tools-for-agents#running-an-evaluation)). Official OpenAI eval guidance likewise defines typed test-item schemas and human-provided ground truth, and exposes criterion-level results and usage rather than only a top-line score ([OpenAI eval guide](https://developers.openai.com/api/docs/guides/evals)).

**Inference for rob2-kit.** Extend the existing provider-independent held-out evaluation as a layered funnel:

| Layer | Primary metrics | Failure localized |
| --- | --- | --- |
| Deterministic projection | page/line fidelity, table fidelity, stable hashes, rebuild identity | preprocessing |
| Retrieval | needed-passage recall and reciprocal rank at several depths; Source-role coverage | discovery ceiling |
| Disclosure | previewed needed-passage recall; pages/lines/tokens shown | ranking navigation/context allocation |
| Evidence use | premise recall, unsupported-premise rate, contradiction handling, absence-search adequacy | selection and grounding |
| Scientific answer | question accuracy by class/Domain, macro balance, abstention/limitation behavior | interpretation |
| Derived result | Domain and overall accuracy, always-Low rate, calibration by sufficiency class | end-to-end science |
| Ergonomics | successful completion, tool errors by code, stale repairs, calls, round trips, tokens, latency | interface friction |
| Durability | restart equivalence, retry idempotency, cross-Trial isolation, artifact verification | state boundary |

Use expert-adjudicated passages, premises, contradictions, signaling answers, and judgments where feasible. Report deterministic metrics directly; use blinded expert review or a separately validated judge only for genuinely semantic criteria. Keep the judge version and prompt fixed, measure agreement with experts, and never let the same generated rationale become its own ground truth.

Run each condition across multiple trials and at least two model families. Report mean and dispersion plus both “any success in *k*” and “all *k* successes” when operational reliability matters; repeated runs are necessary because agent outcomes are non-deterministic ([Anthropic eval guidance on non-determinism](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents#how-to-think-about-non-determinism-in-evaluations-for-agents)). Preserve the repository's one-attempt qualification policy for release evidence; use repeated trials in a separate development evaluation so retries cannot inflate release claims.

## Recommended ablation order

The following sequence minimizes confounding and implementation risk. It is an **inference for rob2-kit**, not a source-prescribed roadmap.

1. Establish a frozen held-out set and layer-by-layer baseline from the current workflow.
2. Tune deterministic normalization, FTS parameters, ranking depth, and preview/page sizes.
3. Improve search pagination and `get_domain_context` completeness without changing scientific authority.
4. Normalize success/error response envelopes and add actionable repair packets.
5. Add deterministic pre-save preflight and measure avoided repair cycles and scientific errors.
6. Add typed evidence-sufficiency metadata and evaluate calibration/abstention behavior.
7. Only then test semantic retrieval, reranking, query expansion, or a bounded model critic against the tuned lexical/preflight baseline.

Change one factor at a time. Freeze source bytes, projections, prompt/skill version, tool schemas, model/version, budget, and scorer for each comparison. Record all attempts, including failures, and compare both accuracy and friction so a gain bought by many more calls remains visible.

## Patterns to avoid until evidence supports them

These are **inferences for rob2-kit** based on the cited simplicity and evaluation principles:

- Do not add tools that duplicate the 14-tool workflow or expose server-owned derivations as model choices.
- Do not dump full search results, whole documents, or all prior checkpoints into every turn.
- Do not treat a no-hit query, Result Evidence set, or retrieval rank as proof of scientific absence.
- Do not copy Pi-Serini's corpus-specific BM25 settings or timeout directly.
- Do not add multi-agent voting, a second assessor, or iterative critique merely because it is available.
- Do not optimize only final overall judgment accuracy; it hides retrieval, grounding, class-balance, and workflow failures.
- Do not use MCP annotations, self-reported confidence, or model prose as enforcement. Keep deterministic authority and validation at the server boundary.

## Source scope and limitations

- Pi-Serini was evaluated on 830 BrowseComp-Plus queries over a fixed corpus of 100,195 long documents, using several frontier models and an LLM judge ([paper, experimental setup](https://arxiv.org/html/2605.10848v1#S4)). Its architecture and ablations are relevant design evidence, but its numerical gains may not transfer to clinical-trial PDFs, tables, or RoB 2 judgments.
- The Pi-Serini repository revision reviewed here is [`bbab25d`](https://github.com/justram/pi-serini/tree/bbab25da84e8b0651e492bcde4c11423208bdf3c). Repository documentation is implementation evidence, not an independent replication of the paper.
- MCP sources specify interoperable contracts and safety behavior; they do not establish downstream scientific accuracy.
- Vendor agent guidance reports engineering experience and suggested methods. Recommendations in this note remain model-agnostic by expressing them as interface, state, and evaluation patterns rather than provider-specific APIs.
- Every rob2-kit application marked **Inference for rob2-kit** requires a held-out ablation before adoption or an accuracy claim.

## Addendum: How To Build And Evaluate Search Agents

### Source and metadata

- **First-party source:** [YouTube video](https://www.youtube.com/watch?v=pi-IW4HYJwU), published by [Hamel Husain](https://www.youtube.com/@hamelhusain7140) on September 3, 2026; duration 50:35.
- **Speaker:** Nandan Thakur. Husain introduces the session and asks questions; Thakur gives the presentation.
- **Description:** the uploader frames the talk around BrowseComp-Plus, ORBIT, and HawkEye: respectively a reproducible retrieval benchmark, a synthetic multi-hop data pipeline, and a trajectory-analysis interface. The page provides English auto-generated captions, so the claims below are paraphrases checked against surrounding caption context rather than verbatim quotations.
- **Uploader's chapter sequence (labels paraphrased):** [00:00](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=0s) search as a weak point; [00:34](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=34s) speaker background; [03:04](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=184s) model-driven search; [05:37](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=337s) evaluation difficulty; [06:33](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=393s) BrowseComp; [08:55](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=535s) non-comparable reported results; [09:41](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=581s) BrowseComp-Plus; [13:28](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=808s) same model with a better retriever; [17:56](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1076s) long-answer grading; [20:45](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1245s) training-data limits; [23:49](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1429s) ORBIT; [25:38](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1538s) staged verification; [30:56](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1856s) simple verifiable rewards; [35:14](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=2114s) leaderboard efficiency; [39:55](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=2395s) HawkEye; [46:08](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=2768s) private-data benchmarks.

### What the video says

These are source-supported descriptions of the talk, not rob2-kit recommendations.

- Thakur defines agentic search as an LLM-controlled loop in which the model decides whether and how to call retrieval, inspects returned context, refines queries, and eventually answers, contrasting it with one-retrieval-pass RAG ([03:04-04:30](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=184s)). He warns that the area is new, not well formalized, and that the talk includes his own developing point of view ([01:30-02:10](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=90s)).
- He argues that answer-only comparisons are not reproducible when papers omit the search tool or retriever, and they cannot reveal how much retrieval contributed to the result ([08:55-10:00](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=535s)). BrowseComp-Plus addresses this by fixing a roughly 100,000-document corpus, adding difficult negatives, and supplying human relevance judgments for the evidence documents ([09:41-12:20](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=581s)).
- The benchmark reports answer exact match, evidence recall, and search-call count. In the presented comparisons, changing the retriever while keeping the LLM fixed materially changed answer accuracy and usually reduced search turns; Thakur also notes that tuned BM25 can be competitive ([12:00-15:10](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=720s)). The reported 60%-to-88% example is specific to BrowseComp-Plus and the compared retrievers. When asked about generalization, he says he expects some but explicitly qualifies that he is not the expert on the cited late-interaction models ([15:20-16:15](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=920s)).
- For long-form answers, he proposes evaluating atomic factual nuggets, whether citations support the asserted content, and source credibility ([17:56-18:50](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1076s)). The team calibrates an automated evaluator against prior human labels; he reports an observed tendency for the agent evaluator to choose partial support more often than human assessors, who were more decisive ([18:50-20:25](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1130s)).
- ORBIT generates constrained, multi-hop questions from seed pages, then performs same-model self-verification followed by document-grounded verification with other models ([23:49-28:40](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1429s)). Its precision-oriented filtering deliberately accepts losing some hard examples to reduce incorrect training pairs ([30:15-31:10](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1815s)). This was not full human validation: Thakur says quality control began with manual inspection and that he later spot-checked roughly 50-100 examples from a 20,000-item dataset ([28:45-30:15](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1725s)).
- He prefers a simple answer-correct/incorrect reward for an initial short-answer search agent and describes keeping the base model and training procedure fixed while changing the training dataset ([30:56-34:10](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=1856s)). This is an experimental-control and training recommendation for verifiable short answers, not evidence that exact-match rewards fit nuanced RoB 2 judgments.
- A leaderboard example contrasts a 95%-accuracy system using about 210 search calls with a roughly 90%-accuracy, 84%-recall system using about 12 calls. Thakur prefers the latter efficiency profile and cautions that final accuracy omits important behavior; latency was not reported, and his latency conclusion is explicitly an intuition ([35:14-37:25](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=2114s)).
- HawkEye analyzes topic shifts, query provenance, semantic query repetition, and whether retrieved documents add novel information ([37:30-43:55](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=2250s)). In the shown analysis, correct runs used fewer search rounds than unresolved runs, while some unresolved agents continued searching without progress ([41:30-42:20](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=2490s)). The work was under review and had no public artifact when the video was published, so the talk provides an example and hypothesis rather than a reproducible implementation.
- For private corpora, Thakur suggests synthetic queries that connect known relationships across document clusters and recommends evaluating human-authored and model-authored query sets separately because their distributions differ ([46:08-49:20](https://www.youtube.com/watch?v=pi-IW4HYJwU&t=2768s)).

### Overlap with the existing recommendations

- The fixed-corpus/relevance-judgment setup, separate answer and retrieval metrics, controlled retriever comparisons, and warning against copying BrowseComp-Plus settings reinforce recommendations 1, 2, and 8. They are already substantially captured by issues [#282](https://github.com/AliSalman-et-al/rob2-kit/issues/282) and [#283](https://github.com/AliSalman-et-al/rob2-kit/issues/283).
- The warning that top-line accuracy can conceal excessive search calls reinforces recommendation 8 and #282's calls, tokens, latency, failure-coverage, and paired-ablation metrics.
- Citation support at the level of atomic factual claims reinforces recommendation 8's required-premise and unsupported-premise metrics and [#285](https://github.com/AliSalman-et-al/rob2-kit/issues/285)'s source-bound comparison cards. The video's separate source-credibility criterion must not be converted into server-side authority: in rob2-kit, Source role and provenance can be projected deterministically, but scientific credibility remains host/researcher interpretation.
- The agent-driven search loop is compatible with the current `search_sources`/Evidence boundary, but it does not justify adding another tool or moving interpretation into the server. Recommendation 4 and [#284](https://github.com/AliSalman-et-al/rob2-kit/issues/284) already cover compact, question-scoped context and recovery.

### Genuinely new additions for rob2-kit

These are inferences for rob2-kit and require development evaluation before adoption.

1. **Add query-level trajectory diagnostics to #282's evaluation manifest.** Record each search query, exact repeat status, prior-result overlap, count of newly surfaced passage/source identities, governing Domain/question when observable, and stop reason. Derived offline analyses can measure redundant reformulations, topic drift, evidence novelty per call, and unresolved runs that continue without new material. Exact identity/overlap metrics can be deterministic; semantic repetition or provenance inferred from model reasoning should remain a versioned offline annotation/judge output, not authoritative runtime state.
2. **Use synthetic contrast tasks only as development stress tests.** Known Trial documents and adjudicated premise relationships could seed hard queries that require joining, for example, protocol, conduct, outcome-availability, and analysis-plan evidence. Use them to test retrieval ceiling, query reformulation, and tool ergonomics, not as clinical ground truth or the untouched holdout. Require expert review and keep every document family from a Trial in one split; ORBIT's model-only verification and small manual spot-check are not adequate evidence for RoB 2 correctness.
3. **Audit evaluator category bias, not only aggregate agreement.** When a model or agent grades passage support, compare its full/partial/unsupported confusion matrix with blinded expert labels and inspect calibration by Domain, Source role, and premise type. Preserve disagreement and alternative sufficient evidence sets. The video's observed partial-support tendency is a concrete failure mode to test, not a transferable expected rate.
4. **Use progress-per-call to tune stopping behavior.** Alongside total calls, measure consecutive searches yielding no new source/passage identities and no newly supported premise. This can identify loops without asserting that novelty equals relevance or that a no-novelty run has exhausted the evidence. Any runtime cap should be selected from held-out completion, accuracy, and cost trade-offs rather than copied from the video's examples.

### Mapping to open issues

| Issue | Video-derived contribution | Recommended disposition |
| --- | --- | --- |
| [#282](https://github.com/AliSalman-et-al/rob2-kit/issues/282) | Add query repetition, topic/provenance annotation, document/passage novelty, progress-per-call, and evaluator support-category confusion to its trajectory manifest and reports. Synthetic multi-document contrast queries may be a development fixture, never the holdout reference. | Comment/amend the existing issue; no new issue. |
| [#283](https://github.com/AliSalman-et-al/rob2-kit/issues/283) | Its paired retriever ablations and calls/recall metrics are directly supported. Add exact cross-call result overlap and novel-candidate yield as evaluation telemetry, owned by #282 rather than ranking behavior. | Comment only if the telemetry boundary needs clarification. |
| [#284](https://github.com/AliSalman-et-al/rob2-kit/issues/284) | Question association and compact context can make query provenance observable, but the video gives no evidence for a particular Domain projection or context-size policy. | No change beyond cross-linking #282 telemetry if useful. |
| [#285](https://github.com/AliSalman-et-al/rob2-kit/issues/285) | Atomic nuggets and citation-support grading support premise-level evaluation of the proposed cards; they do not validate the card design or automate scientific classifications. | Comment only; evaluate card premises under #282. |
| [#286](https://github.com/AliSalman-et-al/rob2-kit/issues/286) | The video does not discuss negatively framed signaling questions, answer-code polarity, atomic saves, or deterministic save invariants. | No change; do not cite this video as support. |

**Issue recommendation:** comments or body amendments to #282 and, if needed, #283/#285 are sufficient. Do not create a new issue until trajectory telemetry or synthetic development fixtures prove large enough to need separate ownership.
