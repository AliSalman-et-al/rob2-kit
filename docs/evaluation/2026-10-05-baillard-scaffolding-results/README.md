# Baillard: frozen scientific-scaffolding comparison

Both authorized original `gpt-6-luna` / medium sessions completed. Their unedited
answers pass the frozen runtime's closed assessment schema, exact active branches
and canonical citation checks (Trial ownership, immutable Source bytes/projection
and selected Evidence integrity). Those checks establish structural validity and
source identity, not semantic support. Source-first review finds important warrant
failures in both arms. This pair does not justify removing local scientific
scaffolding or claiming improved accuracy.

## Computed proposals

| Domain | Minimal | Rich |
|---|---|---|
| D1 randomization | Low | Low |
| D2 deviations | Low | Some concerns |
| D3 missing outcomes | High | Some concerns |
| D4 measurement | Low | Low |
| D5 selection | Some concerns | Some concerns |
| `overall_default` | High | Some concerns |

The unchanged branch evaluator computes these proposals. `overall_default` does
not perform native review/finalization or adjudicate whether several concerns
substantially lower confidence. No model supplied risk labels; no operator
repaired answers or supplied a preferred label. No historical Domain answers or
human gold were read. This corrected minimum-SpO2 target is not compared with
human labels for the original, ambiguously described mean-drop target.

## Source-first warrant audit

The reference for this audit is the captured article plus the complete applicable
2019 official guidance, rather than either arm's label. Exact source words and
inspected figure coordinates are in the adjacent preparation's
[source receipt](../2026-10-05-minimal-assessment-preparation/source-words-receipt.json).
The figure establishes 57 randomized and 53 analyzed after two exclusions per
arm for incomplete records; it does not identify which selected outcome values
were unavailable. The continuous measurement and reported minima are documented.
The Methods' primary mean-drop wording remains an unresolved correspondence
issue, rather than evidence that results-dependent selection occurred.

- **D1:** Rich correctly retains unknown all-randomized baseline information.
  Minimal answers No to baseline imbalance from the final-analysis table despite
  acknowledging that limitation. Official p.18 explicitly discusses this case.
  Both answer Yes to concealment from opaque, sealed, numbered, sequential
  envelopes; the article does not establish every safeguard described on p.17.
  Probably Yes could reflect the reported protections without insisting on an
  unavailable tamper-proof or irreversible-assignment record. This is a certainty
  issue, not evidence of compromised allocation; proposed D1 labels coincide.
- **D2:** Both keep visible treatment differences separate from trial-context
  deviations, a sound distinction. Standardization supports Minimal's probable
  absence judgment, while Rich explicitly retains the unknown trial-context
  mechanism; neither has evidence of a harmful context-caused deviation. More
  seriously, both use incomplete-record exclusions as if they were established
  missing-outcome-only exclusions to justify an appropriate assignment analysis.
  Rich's Probably Yes is more qualified than Minimal's Yes, but the exact
  exclusion content remains unknown. Official pp.29 and 39 distinguish omitted
  available outcomes from unobserved outcomes. A probable judgment needs an
  explicit inference supporting missing-outcome-only handling, not just the
  phrase incomplete data. Uncertainty does not itself prove inappropriate analysis.
- **D3:** Minimal turns 53 analyzed into 53 observed, and reasons principally from
  93% versus a 95% example. Rich explicitly warns that the observed count is
  unknown, yet starts its rationale by asserting that outcomes were unavailable
  for the full randomized population and reuses the same 7% inference. Neither
  establishes an outcome-specific observed count or explains why the unresolved
  availability could materially affect this mean difference. Both acknowledge
  unknown reasons; neither documents outcome-linked missingness. Minimal's
  No information at 3.4 produces High through the official branch; that branch is
  not an evaluator bug or proof that outcome dependence actually occurred.
  Rich's Probably No at 3.4 relies on equal exclusions and the absence of described
  outcome-related reasons. Those facts do not establish outcome-specific missing
  counts or make dependence unlikely. A source-supported contextual probable
  judgment remains permissible, but this rationale supplies a weak negative
  warrant. Thus the D3 label difference is not a demonstrated scientific gain.
- **D4:** Both identify continuous numerical pulse oximetry and distinguish
  measurement from the true oxygenation effect of treatment. Rich retains unknown
  assessor identity/awareness; Minimal infers awareness from visible treatment.
  Both reach No for possible measurement influence. This is plausible for an
  instrument-derived minimum, with a residual extraction/windowing uncertainty;
  objectivity alone does not establish assessor blinding. No observed domain-label
  benefit is claimed.
- **D5:** Both preserve the Methods/results correspondence and chronology unknowns
  at 5.1. Neither claims proved results-dependent selection. Minimal's Probably No
  for multiple analyses relies on there being no suggestion that alternatives
  were tried, despite explicitly acknowledging unknown alternatives. That is not
  the positive correspondence/no-opportunity warrant in official pp.64–65. Rich's
  No information better preserves that unresolved opportunity. For measurements,
  Minimal's narrow eligibility argument needs a distinction between the exact
  numerical result and the user's independently eligible outcome measurements;
  defining eligibility after seeing the reported minimum can conceal selection
  opportunities. Rich retains that uncertainty but cannot infer selection merely
  from other study-stage time points. Both remain Some concerns.

These findings concern the strength of warrants, not a new case gold standard.
In particular, neither automatic High for uncertainty nor a less severe label is
an accuracy measurement. Some probable judgments are defensible with indirect
information; demanding exact missing counts, a timestamp, a protocol, or a
sensitivity analysis for every decision would introduce another distortion.

## Delivery and execution

Both prompts contained identical target, initial Evidence, complete applicable
official text and all-source access. Minimal read all seven trial pages and
rendered official pages 17, 28, 29, 45, 54, 63 and 64. Rich read pages 1–5, then
1/6/7, rendered the native flow-diagram page 2 and official page 17. All nine
Minimal and five Rich tool calls completed without tool errors. The trial page
text was delivered; reading a page is not proof of attending to every fact. Both
had the contrary mean-drop wording and missing-record descriptions available.
Source omission or unavailable source tools therefore does not explain these
particular unsupported conclusions.

Both original requests first failed HTTP 400 `invalid_json_schema`, before model
inference/source calls. Raw failures were frozen. A wire-only schema adaptation
made nullable uncertainty explicit and expressed the homogeneous coordinate
array with supported `items`, retaining its four-coordinate count and bounds.
The `ge` annotation became `minimum`; defaults were removed. This follows the
[official Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
The authoritative Pydantic/evaluator/citation validation, source, target, prompts
and guidance remained unchanged. Text and visual fixtures passed both schemas;
three/five-coordinate fixtures remained invalid.

Exactly the two saved original IDs resumed once each with the identical generic
instruction, “Continue the original assessment task and return its final JSON.”
No third session, new credentials, answer feedback or improvement retry occurred.
Actual original and continued profiles were `gpt-6-luna` / medium. Both final
outputs/raw failures were hash-frozen before comparative inspection. Original
input hashes were checked again after completion. The first offline validation
attempt used relative workspace paths and tripped native containment checks;
absolute paths passed unchanged validation. Failure logs are preserved privately.
The preparation CLI now resolves the workspace path before those same checks.
This ergonomics repair has no scientific or production policy effect.

| Recorded response usage | Minimal | Rich |
|---|---:|---:|
| Input tokens | 312,126 | 452,469 |
| Cached input | 215,296 | 314,624 |
| Uncached input | 96,830 | 137,845 |
| Output tokens | 4,894 | 5,432 |
| Reasoning output (subset of output) | 946 | 1,829 |
| Deduplicated response generations | 4 | 4 |

Usage is from durable per-response records. Repeated input explains cumulative
input exceeding the single context size; this is not a context-overflow measure.
Rejected initial requests recorded no durable usage; their billing is unknown.
Dollar cost is unknown. Raw rollouts/stderr stay private because they include
account telemetry and full guidance/source content. Their hashes and unedited
final JSON are preserved here; full private artifacts remain in preparation v14.

## Decision and next scientific step

Retain production defaults. This single, context-length-confounded pair gives
mixed scientific effects: Rich better preserves baseline, denominator and D5
uncertainties, while still failing to carry them consistently into conclusions.
Minimal does not meet the frozen source-warrant criterion for removing scaffolding.
Neither arm's labels establish superiority to All-Low or human agreement.

The actionable mechanism is **premise consistency across conclusions**: the same
unknown observation/exclusion mechanism is correctly named, then silently treated
as known to answer D2 and D3. Existing local guidance already describes the right
count distinctions and probability rules. Adding another case-specific warning
would not address the demonstrated failure. A subsequent implementation should
make the outcome-availability and analysis-exclusion premises shared, source-bound
assessment state with explicitly retained unknowns, so submission/review can
surface contradictory uses across Domains without automatically choosing answers.
The existing native premise/checkpoint architecture should be audited first;
this lean host intentionally did not expose it. That native route was not tested
here, so these results cannot justify either removing it or claiming it already
prevents the observed failure. Preserve probable source-supported inference and
avoid hard count/timestamp gates. Test contrasting observed-but-excluded versus
unobserved cases, not a Baillard-specific desired label.

Paid work stops with these two outputs. Full benchmark remains off. Any later
paid contrast needs a new frozen design and explicit authorization. This checkpoint
is evidence for the next architecture investigation, not an accuracy release.
