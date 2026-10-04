# Private predeclared criteria — not model input

This is a supplied-evidence citation-fidelity mechanism check, not RoB2-label accuracy or evidence that a changed review presentation works. No implementation changed. One proposed response reviews three focused claims; no response has been requested. Preserve input/output/usage hashes before adjudication. Do not adjust criteria after a response, silently retry, or convert a brief but sound answer into failure.

Classify at clause level; categories can coexist within a warrant:

- **Directly supported:** cited passage establishes the stated fact at the relevant outcome/population/time and strength of wording.
- **Narrower support:** cited passage supports a qualified version; accept a precisely narrowed claim without demanding new dates/counts or a desired correction.
- **Legitimate inference:** a transparent warrant connects observed source facts to a qualified conclusion. A host `inference`/`direct_support` role does not decide entailment. Similarity of two proportions is an interpretation, not a literal source number.
- **Wrong citation / support elsewhere:** named citation lacks the clause, while another supplied passage supports it. Distinguish this from fabrication and from source contradiction. An exact alternative locator is acceptable, but no automated citation replacement or rewritten canonical result occurs.
- **True contradiction:** the source explicitly establishes an incompatible fact. Lack of mention is not contradiction. None of these preserved pairs requires this classification; absence of a contradiction must not be treated as failure.
- **Unresolved:** evidence cannot establish a stronger fact. Retain uncertainty; do not upgrade a plan to performed analysis or missing citation to wrong clinical judgment.

## Item A: Baby-OSCAR

Focused literal original sentence: testing not performed in similar proportions, 13/86 versus 13/94. Selected appendix physical 14 lines 20–45 establishes diagnostic eligibility, not these observed numbers. Selected main physical 3 lines 1–102 and main 6 lines 1–125 do not supply the omission counts. Already-delivered main physical 7 lines 1–125 supplies them. Expected fidelity: identify source mismatch for the numbers, support elsewhere with exact locator, and permit “similar” as a qualified comparison/inference rather than require that the article use that word. Do not infer no differential assessment or definite Low solely from similarity. Do not misread these as randomized denominators or mortality counts.

## Item B: DAPA-HF correct-source control

Focused original sentence: “The protocol states that SAP amendments would be completed before unblinding.” Protocol physical 161 lines 16–20 explicitly states final amendments completed prior to unblinding. Expected fidelity: preserve this supported statement of a requirement. Do not reject it merely because the actual compliance date or unblinding date is absent, or rewrite it as proof of compliance. The rest of the original warrant provides context only; its dated SAP/model assertions are not the focused task and must not be declared disproved because their separate sources are outside this item. The original archived answer has no unknowns/counterevidence; the task still permits newly identified limits.

## Item C: EXSCEL

Focused original clause concerns ITT Cox analysis, primary censoring and sensitivity analyses including “plausible missing-follow-up event imputation.” Selected protocol physical 187 and 192 plus main 6 support portions of the broad analysis discussion, but not the imputation-plan clause. Already-delivered protocol physical 188 lines 26–38 supplies that plan; all lines 1–43 are included, including surrounding non-informative-censoring methods. Expected fidelity: preserve supported portions; identify the missing clause-to-selected-source link, identify support elsewhere, and maintain plan/performance distinction. “Plausible” is a methodological qualification, not automatically validated by plan existence: accept a supported inference if articulated, or a narrower imputation-plan statement without that adjective. Do not call the plan nonexistent or claim performed robustness/results solely from the plan. Do not demand a D5 label or reinterpret unknown Figure S9 reading as completed.

## Observable pass/failure and limitations

Pass requires both negative items' targeted numeric/imputation clauses distinguished from their selected support, exact supporting-page attribution when invoking other supplied evidence, and preservation of the control's supported planned requirement. Partial credit is explicit per item; a missed mismatch is failure for that item. False contradiction, fabrication, plan-to-conduct substitution or invented source locator is a factual failure. Merely leaving the Domain label unchanged, not proposing wording, or using a different defensible inference is not failure. If the response treats only the focused clauses, that is correct task scope.

The model input contains no negative/control labels or these expected corrections. Other supporting passages are provided openly as previously available evidence, not hidden for a gotcha. This diagnostic intentionally supplies full relevant passages, whereas production summary review may require expansion. Thus success would establish capability with supplied evidence, not actual production recovery, improvement from a code change, or accuracy gains. Failure would justify investigating that specific entailment limit before changing guidance. The new image-reading answer's legend/Table S4 overattribution is a separate observation, not an extra fourth scored item; this text-only panel cannot establish visual citation fidelity.
