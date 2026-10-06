# Paired source-text follow-up to 151c385

Exactly two additional single responses used the same frozen cases, source text,
production reference, CLI 0.159.0, tool-free configuration and `gpt-6-luna`
`medium` harness as the first pair. Only the two current production D3
comparison-card availability propositions were inserted. Removing that exact
section reproduces each prior prompt byte-for-byte. The earlier prompts did
not contain comparison-card propositions: this tests their addition, not an
isolated change to a previously presented card. No custom corrective hint,
reference label, extra source, retry or continuation was supplied. Both responses
were hashed before either was reviewed. Prior outputs remain preserved.

| Case | Seconds | Input | Cached input | Output | Reasoning subset | Tools |
|---|---:|---:|---:|---:|---:|---:|
| AWARD10 | 51.76 | 19,982 | 1,792 | 1,746 | 516 | 0 |
| GetGoal Duo1 | 17.59 | 20,086 | 1,792 | 707 | 0 | 0 |

Total: 40,068 input, 3,584 cached input, 2,453 output. Reasoning is included
in output, not an extra charge added here. Preflight character estimates were
18,036 and 18,439 tokens; these are not exact tokenizer counts. GetGoal's actual
total input exceeded 20,000 by 86; uncached input was 18,294 and within the
20,000 monitored uncached guard. Neither reached the 30,000 total input,
4,000 output, 8 minute wall or 2 minute idle stop. Monitored in-flight overshoot
was approved. Across both pairs: 79,844 input, 7,168 cached, 4,851 output.

## Paired scientific observations

Both D3.1 answers changed from Probably No to No information. AWARD now says
completion/dropout and evaluable-data denominators do not establish observed
endpoint counts. GetGoal explicitly says analyzed denominators cannot establish
either observed availability **or material incompleteness**. These warrants
better preserve the supplied-evidence uncertainty. With one stochastic response
per case, neither causal attribution nor accuracy improvement is established.
The supplied evidence remains incomplete and cannot settle all-source labels.

Other behavior regressed or remained faulty:

- AWARD retains a complete active path, but now states Some concerns despite
  D3.4 No information. The existing production evaluator computes High. Its
  free-form domain label must not be accepted as an evaluated result.
- GetGoal stops at D3.1 No information and omits activated D3.2. The existing
  evaluator rejects it, as it rejected the baseline omission of D3.4. The new
  response is less structurally complete. Its domain label "No information" is
  also not a RoB risk category.
- GetGoal's counterpoint says all randomized participants were in mITT, while
  its own rationale reports smaller mITT analyzed counts. That generalization
  lacks the qualifying baseline/postbaseline eligibility condition. Better
  D3.1 reasoning does not make every supporting statement correct.

All cited coordinate ranges occur in the supplied text. Coordinate presence is
not a claim that every passage entails every proposition. See the exact answers
and `paired-production-check.json` for the distinction between scientific warrant,
active-path completeness, and deterministic risk computation.

## Follow-up without another paid cycle

Keep the small production premise addition: both observed D3.1 warrants improved,
with no algorithm or answer coercion introduced. Treat the structural/label faults
as single-response behavior, **not production validation failures**. The actual
workflow already checks the active path and computes the risk label. Repeating
these same cases again would not justify a stronger scientific claim. A future
bounded production-workflow probe should use a different case and distinguish
uncertain availability from actual outcome-loss accounting; it should export
server-computed judgments and preserve every rejected draft, rather than score
free-form domain labels. Full benchmark discussion remains required.

A cheap read-only source check additionally inspected AWARD supplement PDF pages
7 and 9 and the entire poster page 1 from the Code benchmark corpus. Supplement
page 7 describes LOCF for **lipid/renal outcomes at 26 weeks**, not the target
week-24 HbA1c result. Page 9 is an ITT/MMRM trajectory figure with no per-visit
observed counts. Visual review of the poster confirms distinct study and drug
stopping counts and the same completed-study totals; its HbA1c graphs do not
report observed endpoint counts. Thus these inspected locations do not resolve
D3.1. This is bounded inspection, not a claim that all available sources lack
the information. The flow diagram is not fully represented in extracted text,
reinforcing the need for existing figure/source-reading pathways.

Provenance and exact prompts/outputs/events are included; credentials and stderr
are excluded. No further paid model call, full benchmark, merge or CI wait ran.
