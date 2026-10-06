# Two supplied-evidence D3 responses, 2026-10-02

Exactly two single-turn responses ran with `gpt-6-luna`, reasoning effort
`medium`, Codex CLI 0.159.0, frozen code
56363e5c2850f4e8a1195e65c66319a7e511e346. No tools, network source capture,
continuations, retries or reference labels were supplied. These are selected
source-text diagnostics, not natural-retrieval assessments, exact registry
replays, or benchmark accuracy measurements. The prompts retain complete
selected article pages and enrollment/flow/primary-outcome registry sections;
other material is explicitly absent. Raw registry JSON remains unrecovered.
Both prediction hashes were frozen before scientific review.

| Case | Wall seconds | Input | Cached input | Output | Tool calls |
|---|---:|---:|---:|---:|---:|
| AWARD10 | 33.41 | 19,836 | 1,792 | 1,385 | 0 |
| GetGoal Duo1 | 23.24 | 19,940 | 1,792 | 1,013 | 0 |

Total: 39,776 input, 3,584 cached input, 2,398 output. Neither response reached
30,000 input / 20,000 uncached input / 4,000 output / 8 minute wall / 2 minute
idle thresholds. Input estimates were conservative character estimates, not
exact tokenizer counts. The output threshold was monitored, with in-flight
overshoot explicitly authorized. The historical `predictions-frozen.json`
misnames completion time as `started_at_utc`; case run records correct this
and give approximate start times derived from elapsed time.

## Residual scientific failure

Both responses distinguish analysis denominators from observed outcomes, yet
select Probably No at D3.1 while acknowledging that observed endpoint counts
and the relation between discontinuation and missing outcomes are unknown.
AWARD10 states that discontinuations "suggest" incomplete availability;
GetGoal concludes that outcomes were "not shown" available. Neither supplies
a sufficient bridge from those facts to *materially incomplete* availability
for the target. This reverses the burden of evidence despite the supplied
production reference explicitly requiring No information when extent remains
unknown. This conclusion is limited to supplied evidence; it is not a certainty
claim about all trial sources or a declaration of the gold answer.

AWARD10's completed answer path deterministically yields High because D3.4 is
No information. That structural consistency does not validate its D3.1 warrant.
GetGoal omits activated D3.4 and asserts Some concerns. The existing production
evaluator rejects that incomplete path; this is **not a production validation
defect**. See `production-evaluator-check.json`. No gain or regression rate can
be inferred from these two selected responses.

## Small structural response

The existing D3 comparison card exposes one positive availability proposition.
It now also exposes the distinct host-owned proposition that availability was
materially incomplete. Both start unknown; counts, analyzed populations and
source metadata classify neither. This places the negative premise beside the
positive premise at question time, using the existing typed proposition
contract. It adds no mandatory field, answer coercion, text keyword heuristic,
or new validation authority. Existing question-linked working premises already
retain observations, inference and unresolved components; another rationale
schema would duplicate them. Scientific classification still requires the host
and source evidence. Behavioral benefit of the additional proposition remains
unmeasured; no further model call was authorized.

The existing comparison-card test now verifies both premises remain unknown
when a reported completer population differs from the randomized target.
Prompts, responses, exact usage events, run records and source identifiers/hashes
are preserved here. Local credential homes and stderr are excluded.

Validation: all 10 comparison-card tests passed; source typing, focused lint,
format checks and `git diff --check` passed. No full benchmark or broad CI wait.
