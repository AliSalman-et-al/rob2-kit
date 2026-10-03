# Two lean tool-free observation contrasts

Exactly two `gpt-6-luna` / Medium invocations produced one response each at clean scientific checkpoint `e6b893b`. No tools, retry, follow-up generation or code edits occurred during the test. These are explicitly synthetic mechanism controls inspired by the Code AWARD-1 article's rescue/analysis pattern, not newly established AWARD-1 facts or clinical validation. The real article/supplement did not establish post-rescue observation, so making that fact explicit in a clearly synthetic pair was necessary for a clean contrast.

## Exact intervention in the prompts

All target, rescue, analysis, unknown-subgroup facts, task instructions and guidance are identical. The only changed sentence is:

- A: `Report: Terminal endpoint measurements after additional treatment were obtained for all such participants.`
- B: `Report: Terminal endpoint measurements after additional treatment were not obtained for any such participants.`

The shared target is an assignment effect on a terminal glycemic endpoint among all randomized participants. Shared facts describe outcome-triggered additional treatment, greater rescue proportion in controls, scheduled terminal collection, pre-rescue-only efficacy measurements, LOCF, and a separate medication-stopping subgroup whose collection status and reasons are unspecified. No subgroup counts or whole-population ascertainment total are provided.

Current production D3.4 guidance was included in full, unchanged. For D2.6, D3.1 and D3.3, the same official excerpt, decision rule, evidence-needed and no-information rule were supplied in both prompts. The task asked for signalling reasoning in at most 600 words, not domain/overall risk labels or a preferred answer. There were no gold labels or leading correction instructions. The updated operational guidance itself contains its production paired-control example; this checks behavior with that guidance, not unaided knowledge or blinded causal efficacy of the guidance change. [Design and exact guidance](design.json), [prompt A](condition_a/prompt.txt), [prompt B](condition_b/prompt.txt).

The first preparation attempt using all four full cards exceeded the deliberately conservative input preflight bound; it stopped before inference. The non-D3.4 cards were compacted identically for both conditions, preserving D3.4 in full. Final preflight bounds were 13,643 and13,647 input tokens including a host-overhead reserve; actual input was 7,829 and7,830. The overfull draft remains in diagnostics as a preparation artifact. No response-informed prompt adjustment occurred.

## Responses and review

A produced 364 words. It explicitly recognized the collected-but-excluded values as an assignment-analysis concern, not genuinely missing outcomes. Whole-Result3.1 remained No information because the separate subgroup and counts were unspecified. It kept 3.3/3.4 conditional No information for the whole Result rather than using outcome-triggered treatment as evidence of missingness when the affected measurements were observed. The fixed unknown subgroup stayed unknown. Its D2.6 response was No information despite recognizing the observed-value exclusion, leaving analysis appropriateness under-explained. Its final3.4 paragraph also mistakenly says “pre-treatment” where the prompt describes post-treatment exclusions; that textual error is preserved, not repaired. [Exact response A](condition_a/response.txt).

B produced 325 words. It recognized actual non-observation after rescue and gave 3.3 Probably Yes specifically for that known subgroup, linking it to outcome-related rescue. It distinguished this from the separate subgroup's unknown collection/mechanism. It did not equate known missingness somewhere with materially incomplete whole-population availability: 3.1 remained No information without counts or a complete total. It returned 3.4 No information for the whole Result, separating plausible dependence from unestablished whole-Result likelihood. [Exact response B](condition_b/response.txt).

B's qualification is not a universal requirement for counts before a probable 3.4 answer. Cochrane permits reasons/trial circumstances to support likelihood; counts or an MNAR sensitivity analysis are not mandatory whenever the mechanism is informative. For this synthetic subgroup, non-observation after rescue is explicit, so the rescue proportion *does* describe a known component of missingness. The response's blanket statement that rescue rates are not missing-outcome rates should have distinguished that known component from unknown total missingness. It could make its assessment of likelihood within the known subgroup more explicit while preserving uncertainty about the whole Result.

B also gave D2.6 Probably No while noting that genuinely unobserved measurements cannot be assumed to be an analysis-only exclusion. Missing outcomes and LOCF concerns do not themselves establish an inappropriate D2 assignment analysis; the supplied guidance permits appropriate modified ITT exclusions for genuinely missing outcomes. The report lacks complete grouping/membership detail in both conditions, so this is an inconsistent or insufficiently explained D2 inference, rather than proof of a correct opposite D2 answer. Neither response establishes a formal alternative estimand.

The mechanism distinction was used in both directions, and unknowns were preserved. That is partial success, not a fully correct signalling assessment. Neither response supplied 3.2 or a complete unqualified Result-wide D3 path; **no offline server label was inferred**. No clinical accuracy, benchmark agreement, causal improvement from the guidance change, or independent human validation is claimed.

## Cost, delivery and stopping

Each condition used one durable response generation, one final message and zero actual provider tool calls, verified against the retained rollout. Response text exactly matches the durable assistant text. [Delivery/count proof](response-proof.json), [summary](summary.json).

A: 7,829 input = 1,792 cached +6,037 uncached; 476 output; 16.27 seconds.
B: 7,830 input = 1,792 cached +6,038 uncached; 426 output; 18.27 seconds.
Combined: **15,659 input =3,584 cached +12,075 uncached;902 output**, zero separately reported reasoning tokens. Each response was below 600 words and 20k input, with zero input/output threshold overshoot. Eight-minute wall/two-minute idle guards remained far from their limits. CLI/config model IDs and Medium effort are retained in each run and manifest. Authentication, private reasoning and raw private rollout metadata are excluded. No owned processes remain.

## Next justified step

Review the D2.6 explanation against the existing source-backed rule before adding more production text or buying another replay. In particular, distinguish available endpoint values deliberately omitted from a genuine modified ITT/missing-outcome case, and identify whether group attribution, membership, measurement choice or assumptions actually fail to match the assignment target. Likewise clarify subgroup likelihood versus whole-Result uncertainty without making counts a new gate. Existing guidance already states much of this, so these replies alone do not justify automatic answer coercion or another wrapper. The two-response allowance is exhausted; no third response or whole-domain probe was run.
