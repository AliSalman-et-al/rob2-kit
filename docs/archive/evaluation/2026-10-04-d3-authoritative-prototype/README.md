# D3 authoritative-context prototype

The implemented, opt-in MCP profile `official_d3_prototype` replaces competing scientific rules with a single official source core for all four D3 questions. Example:

```json
{"domain_id":"domain:missing","guidance_profile":"official_d3_prototype"}
```

The default remains `current`. A frozen continuation inherits its selected profile. D2 and D5 context contents remain unchanged, including their existing page budgets. No model calls, full benchmark, merge, or answer/algorithm changes were made in this implementation turn.

**Decision: keep the prototype; revise before production default adoption.** Source fidelity and neutral preservation support the implementation. Behavior has not been evaluated, so neither fewer bytes nor passing structural tests justifies adoption or an accuracy claim. The next matched experiment is specified in `evaluation-plan.md` and needs separate authorization.

## Actual replacement

The prototype removes seven operational fields on each of four questions: `bias_construct`, `decision_rule`, `evidence_needed`, `no_information_rule`, `answer_anchors`, `considerations`, and `invalid_shortcuts`. That is **28 fields containing 61 delivered statement/items**. `removed-question-statements.json` records every removed item verbatim; these are delivery units, not an invented count of independent logical propositions.

It also removes the five D3 comparison propositions, five illustrative pairs, the comparison's scientific prompt, five unrelated Domain traps, and the shared definitive-answer Evidence-role gate. It replaces the separate response-framework summaries with the complete official sections 1.1 and 1.1.1. Source navigation, quantities, slots and passage coordinates remain, with an interface-only comparison prompt.

Three skill assets lose the duplicated D3 answer rules. Their old/new contents are preserved in `skill-before-after.json`. They retain source recovery, scope/type meanings, count preview/submission, dependencies, unknowns and counterevidence. The release verifier previously **required** an unknown-extent → No information sentence in the skill. It now checks official source coverage, identity/options, dependencies and interface availability instead of enforcing scientific paraphrases. The prototype source module must be present in the wheel.

This removes the stricter maintainer SQ3.2 certainty language and the contradictory skill SQ3.1 unknown-extent rule from prototype delivery. The previous prespecification example is also absent from the prototype. There is no new sensitivity method whitelist, missingness threshold, MNAR requirement, certainty gate, label rule or automatic scientific judgment.

## Authority, completeness and provenance

The complete Box 8 elaboration for each question is supplied once, with source version, locator, SHA256 and full-document URL. Text is reflowed for whitespace only. This restores source material omitted by the older compact excerpts: the dichotomous-event context and NI wording in 3.1, time-to-event/CONSORT paragraph in 3.3, and all five reasons plus the analysis-adjustment exception in 3.4.

The shared core includes complete official response sections 1.1/1.1.1 (p3), D3 Background section 6.1 (p39), and section 6.3 (p44). These preserve probable judgments, contextual NI reasoning, question independence, D2/D3 separation and sensitivity analyses by trial investigators **or review authors**. They are source text, not a replacement synopsis.

The [current official download](https://www.riskofbias.info/welcome/rob-2-0-tool/current-version-of-rob-2) was verified to point to the 22 August 2019 guidance. The previously captured PDF's SHA256 matches the canonical pack's source identity. The source-layout captures, question transcription and source locators accompany the prototype. No official wording, canonical response options, activation predicates or algorithm were edited.

The [official Cochrane FAQs](https://www.cochrane.org/learn/courses-and-resources/cochrane-methodology/risk-bias/about-risk-bias-2-rob-2) were independently checked for SQ3.1 unknown extent and SQ3.2 method-list clarification. Short exact quotations and question locators link to the **full original answers**; they are not claimed to reproduce the entire FAQ. The undated page is honestly versioned by retrieval date, with raw HTML hash and private capture path. No maintainer paraphrase is presented as official text. The full guidance/FAQ remains accessible at its source URLs; `complete` denotes complete delivery of this specified core, not the entire 72-page document or webpage.

Canonical scientific-pack content remains byte-identical to `f548c03`. Its content hash identifies the existing options/algorithm/recording pack and is **not** claimed to hash the new delivery core. Context snapshot digests bind the complete prototype text and profile; each source section carries independent source provenance. Historical bundles and records retain their recorded semantics.

## Frozen-source demonstration and limits

`attal-2016` and `nefigard` come from the user's required October 1 **Code benchmark repository**. Their existing frozen source pages and independently verified finalized bundles are used, without new extraction claims or label scoring. Production question assembly and prototype projection create both scientific-section views. The approved Result, stored evidence, historical answers and source pages are identical across each pair.

| Scientific-section metric | Current | Prototype |
|---|---:|---:|
| Attal serialized bytes | 36,693 | 28,460 |
| NefIgArd serialized bytes | 58,380 | 50,147 |
| Words in root official material | 276 | 1,955 |

Both pairs remove 8,233 bytes while delivering substantially more actual official guidance. This is an offline section comparison, **not** a production token estimate or a behavior experiment. Archived answers remain for provenance; future model inputs must exclude them and reference labels.

The Code cases no longer retain `.rob2-kit/sources` blobs. Disposable replay attempts correctly failed source-integrity checks; no verifier was bypassed and no missing raw blob was fabricated. The failed copies and explanations remain private. Native MCP delivery, continuation/recovery, source fidelity and untouched D2/D5 controls are verified separately on an intact neutral workspace.

A focused test found nullable prototype metadata increasing an unchanged D2 header beyond its existing 16KiB budget. The implementation now omits inapplicable new metadata from legacy wire responses. The original page-budget test passes, with no raised limit or relaxed assertion.

The context is still produced by one model-free server and interpreted by its host. Submission role/ownership constraints remain structural and do not independently establish scientific certainty. This prototype does not remove those constraints, alter canonical judgments or remedy corpus alignment. It therefore supports a fidelity-oriented capability claim, not benchmark accuracy or manuscript readiness.
