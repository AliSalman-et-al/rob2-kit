# Incremental research for agent improvement cycles

Date: 2026-09-08

This note supplements [`2026-09-08-agent-evidence-research.md`](2026-09-08-agent-evidence-research.md). It focuses on the two Luna evaluation diagnoses rather than proposing another broad architecture. The 28-cell run reports 98/140 agreement against provisional, Low-heavy labels, 829 searches, 302 zero-hit searches, and 48 actionable repairs; its diagnosis attributes the important residual errors to model evidence use and consistency after the relevant guidance and passages were already available. The 9-cell issue-296 run similarly reports 27/45 agreement, with D3 and D4 semantic overreach and stochastic option selection. These figures are evaluation observations, not estimates of clinical accuracy.

## Primary research with direct implications

**Self-RAG: adaptive retrieval and reflection.** Asai et al. train a single language model with special reflection tokens that decide when to retrieve and evaluate retrieved passages and generated text. Their comparisons cover open-domain QA, reasoning, fact verification, and long-form citation accuracy; they report gains over ChatGPT and retrieval-augmented baselines ([ICLR 2024 paper](https://proceedings.iclr.cc/paper_files/paper/2024/file/25f7be9694d7b32d5cc670927b8091e1-Paper-Conference.pdf); [arXiv record](https://arxiv.org/abs/2310.11511)).

**Transfer limit and practical inference.** Self-RAG changes model training and uses learned reflection tokens; it does not show that adding a second runtime critic to a model-free RoB 2 server improves judgments. Its useful lesson is an evaluation decomposition: test retrieval necessity, passage relevance/support, and generation support separately. For rob2-kit, implement this first as offline labels on existing traces: did the model need another search, did the selected passage entail the premise, and did the answer preserve that premise? Do not add reflection tokens, a new MCP tool, or a second assessor without a held-out ablation.

**FActScore: atomic support rather than answer-level correctness.** Min et al. decompose long-form generations into atomic facts and score the percentage supported by a reliable source. Human evaluation showed mixed supported and unsupported facts inside otherwise plausible generations; their automated estimator approximated human scores with under 2% error on the reported biography setting ([EMNLP 2023 full paper](https://aclanthology.org/2023.emnlp-main.741.pdf); [arXiv record](https://arxiv.org/abs/2305.14251)).

**Transfer limit and practical inference.** FActScore targets factual biography claims and binary source support, so it cannot replace expert RoB 2 judgment or encode whether evidence is sufficient for D3.3 versus D3.4. It does support an offline “atomic premise sufficiency” rubric: split a D3 justification into denominator/population, availability, missingness mechanism, and likelihood claims, then mark each as directly supported, contradicted, or unsupported by selected Evidence. This directly tests why an answer can cite correct counts yet still make an invalid D3 inference.

**ToolBench-X: recovery from tool-environment failures.** Tian, Shi, and Zhao construct executable multi-step tasks with deterministic tools and controlled hazards including specification drift, invocation errors, execution failure, output drift, and cross-source conflict. Their benchmark keeps recovery paths available and reports that failures are driven less by tool volume or inference budget than by diagnosing the hazard and adapting; targeted recovery hints help more than simply scaling test-time effort ([arXiv record](https://arxiv.org/abs/2606.25819)).

**Transfer limit and practical inference.** ToolBench-X is a general tool-use benchmark, not evidence assessment, and its abstract-level results do not establish a particular hint format for FastMCP. It nevertheless maps to this repository's actionable repair traces: evaluate whether the model recognized a truncated/no-hit result, stale revision, omitted Evidence passage, or inactive-question error and chose the correct existing recovery. A repair should be judged by subsequent valid state transition and premise grounding, not by call count. This supports refining descriptions and repair payloads only where trace classification finds a recurring diagnosis failure.

## What the Luna traces imply for the improvement loop

The two evaluations show three separate frontiers:

1. **Retrieval discovery:** zero-hit searches and the small number of cursor continuations require query/mode/rank telemetry, but retrieval changes should wait until repeats, truncation, Source scope, and cursor availability are classified.
2. **Evidence sufficiency:** D3 mistakes persist even when counts are cited. Evaluate premise-level entailment and contradiction, not citation presence or final judgment alone. A correct denominator cannot establish true-value dependence.
3. **Decision consistency:** D2/D4 labels varied across outcomes, sometimes appropriately because the Result changed and sometimes because the same evidence was interpreted differently. Compare sibling outcome traces using the same premise checklist; do not optimize to provisional labels without independent adjudication.

The highest-value cycle is therefore: select a stratified error slice; annotate retrieval availability, exact Evidence support, premise sufficiency, answer option, and deterministic judgment; apply one bounded wording or projection change; replay the same cells with the same model and budget; and require improvement in premise grounding and consistency without added unsupported claims. Keep the existing proposal-review authority and deterministic server logic fixed during this diagnosis.

## Ranked incremental experiments

1. Add an offline atomic-premise annotation for D3 and D4, starting with the known 9-cell mismatches and the 28-cell D3/D4 mismatches. Report support, contradiction, and missing-premise rates separately from raw agreement.
2. Classify every no-hit and cursor opportunity in the existing logs by query repeat, lexical mode, term count, truncation, Source scope, and whether a later call recovered a useful passage. This distinguishes a host policy gap from a retrieval defect.
3. Build a repair-follow-through table: repair type, next tool call, whether the state mutation became valid, and whether the eventual Evidence basis solved the original premise. Tune only repair messages that repeatedly fail this path.
4. Run paired sibling outcomes to measure legitimate outcome sensitivity versus inconsistent reasoning, with blinded expert adjudication for disputed cases. Treat the provisional reference set as a comparison target, not ground truth.

These experiments reuse the current 14 tools, deep cache/cursors, Evidence handles, and bounded context. The cited studies support finer evaluation and targeted recovery; they do not justify a new tool layer, multi-agent voting, or automatic scientific correction.

