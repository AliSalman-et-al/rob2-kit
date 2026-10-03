# Proposal scope representation safeguard

This is an offline response to the Allsop scope audit. No model invocation, historical-data relabeling, artifact edit or caregiver gate was added.

## Exact failure mechanism

The approved Allsop target has typed `time_point_or_window.kind: described`, with days 1–6 in its description. The reported comparative-effect object has an endpoint label, numeric F statistic and analysis-population summary, but **no separately typed reported timing or estimand**. Its endpoint definition is null. The days 1–9 model window occurs in Table 2's source footnote and in the caller's `relation_rationale`. The source-bound fields are only `/reported/effect_measure`, `/reported/estimate` and `/reported/endpoint/name`.

Thus the inherited `relation: exact` and all-specified clarity conflict scientifically with the selected passage, but there are not two structured window bounds the server can compare. This is an inherited unsupported scope assertion, accepted through structural and source-reference validation plus researcher approval; it is not a numerical-binding failure or deterministic proof that the product accepted incompatible typed windows. Knowing a target window and binding an F statistic cannot establish that statistic's exact analysis window. The source and interpretation are qualified in the [preceding audit](../2026-10-03-verifier-and-result-scope-audit/README.md).

## Smallest implemented change

A typed, read-only `scope_review` now appears in successful proposal validation and pending Proposal status. Both modern and legacy approval protocols display the same comparison alongside the original identity-bound Review. It preserves the exact Result identity, target outcome definition, measurement, window, assignment estimand and population, and shows the reported endpoint/definition and analysis population. It lists the paths with actual source bindings. Reported timing and effect of interest are explicitly null because those fields are not separately represented, and `verification: requires_source_interpretation` prevents treating the projection as an equivalence certificate.

The instructions ask the model/researcher to compare each critical dimension with the selected source passages, preserve material conflicts or unknowns in clarity and rationale, and choose a supported non-exact candidate when exactness is not established. They distinguish the reported model window from the medication/follow-up window. Null representation is not a finding that the source omitted a fact. Numeric binding or specified target metadata is not an exact-scope proof.

Existing precise structural repairs remain: `exact` with a caller-declared unclear, unavailable or conflicting facet returns `exact_result_scope_not_established` at that facet. The caller can resolve the uncertainty from source evidence, retain a supported non-exact relation such as `related`, or select another candidate. The target is never silently changed. A contradictory rationale with every facet falsely marked specified still requires scientific interpretation; this change exposes that limitation rather than guessing from keywords. No fuzzy wording comparison, model judge, new canonical field, or automatic semantic gate was introduced.

## Validation and limits

Eighteen focused controls passed: nine declared-facet cases and compatible/unknown/different-word-scope projections, immutable inherited identity, validation/status consistency, both approval protocols, and stale/declined/cancelled approval behavior. Alternate target wording does not trigger string-based mismatch repair; its source-owned endpoint label remains unchanged. The natural-language days 1–6 versus days 1–9 contradiction is deliberately not claimed as deterministic scope validation. Shape-control acceptance is not a source-entailment certificate.

Ruff, format and production type checks pass. Both bundle verifiers still accept the untouched Allsop artifact, SHA-256 `845b43ae089382cfd53c3f32dd492c5222752ce60e4cd1ddf880cb4427a0c6d6`. Its selected Result identity remains `sha256:4ccb6a6304e544e3da19a9fbe9cc321edcb70fc01a5370269577a6f9ed423030`; original exactness, risk judgments and source evidence remain unchanged. The scientific pack hash is unchanged.

This is a concrete context and source-binding visibility safeguard, not evidence that a model will now choose the correct relation or calibrate caregiver masking certainty. A separately authorized future mechanism check would be needed to observe that behavior. Independently aligned Results remain necessary before making accuracy or All-Low comparisons. This pass added zero paid invocations; the [usage ledger](../2026-10-03-verifier-and-result-scope-audit/usage-ledger.json) is unchanged.
