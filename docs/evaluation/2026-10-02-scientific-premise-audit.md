# Scientific premise diagnostic, 2 October 2026

## Corpus and execution provenance

This diagnostic used the Code benchmark repository, not the older main-repository
evaluations: `rob2-kit-benchmark/benchmark-luna6-medium-2026-10-01` logs and
`rob2-meta-set-full-2026-09-29/trials/{albert-2013,dapa-hf}` dossiers.
The isolated launcher and model catalog identify **gpt-6-luna**, **medium**.
Reference risk labels were hidden. The full benchmark remains off.

Recovered uncommitted work and source-reading fix `622b90c` were preserved on
`improve/scientific-premise-20261002`. Cases used a frozen continuation source
at `7c8ca15`/`ad312a4`; the later compact-status change was not applied mid-case.
These are intervened diagnostics, not autonomous cold-start accuracy trials.
Exact prompts, approvals, source hashes, SQLite state and model traces remain
in the local task's `diagnostics` directory; private model homes are excluded
from Git. Do not sum resume summaries: usage reports are cumulative per session.

Albert interventions corrected substitution of Table 3 medians for the requested
abstract result, an invented statistic label, and an unsupported narrower/subset
relation. One continuation launched from the wrong directory was interrupted
and retained, then repeated from the proper case directory. The abstract's 5.7
and Table 3's 7.0 are unresolved source conflict, not proof that the reference
answer is wrong. Researcher approvals identify exact Result receipts.
DAPA had one observed 180-second preparation timeout among two calls; the next
call succeeded. The continuation restored the existing runner's 600-second
allowance, retained validator repairs, and proceeded after exact CLI approval.
No signalling answers were supplied in continuation prompts.

## Changes and evidence

- `56faa95`: comparison cards expose assessment target, exact reported result,
  and their relation together. Randomized and reported populations stay distinct.
  D3 guidance separates ITT membership from outcome availability. D5 guidance
  distinguishes prospective promises from evidence of actual conduct, while
  allowing supported Probably Yes without a direct timestamp. Overall aggregation
  is explicitly the retained local ADR0035 policy, not an unqualified statement
  of Cochrane's confidence-based overall rule.
- `ad312a4`: a reported group statistic can explicitly be null when unidentified.
  Albert's abstract verb “changed” had passed literal binding as a statistic,
  while an honest unidentified label failed. Null now preserves the source value
  without fabricating mean/median semantics; specified clarity cannot accompany
  null. Result semantics v0.9 and both verifiers enforce this. Historical v0.8
  remains strict. Behavioral tests cover rejection, acceptance, finalization,
  both verifiers, and historical compatibility.
- `301de33`: routine status omits exactly recoverable narrative quotations and
  retains recovery coordinates/identities; opt-in restores bounded inline text.
  Visual and nonrecoverable evidence stay inline. Offline projection comparison
  measured selected-evidence payload reduction of 52.0% for Albert and 26.9% for
  DAPA, with all handles/identities and exact recovery preserved. These are byte
  reductions, not measured token savings or scientific gains.
- `970528b` and the subsequent visual check establish compact/expanded status
  equality for all non-selected-evidence data, including unresolved premises,
  counterevidence, gaps and next actions. Warning tampering remains rejected;
  a brittle assertion of the verifier's exact source line was removed.

## Case comparison

| Case | Oct 1 domains D1–D5 | Current diagnostic D1–D5 | Key warrant and limit |
| --- | --- | --- | --- |
| DAPA-HF | Low / Low / Low / Low / Low | Low / Low / Low / Low / Low, finalized | D5.1 Yes → Probably Yes; actual access timing remains unknown. D3 remains Probably Yes with explicit 14/20 incomplete follow-up and uncertain overlap of two unknown vital statuses. |
| Albert 2013 | Low / Low / High / Low / Some concerns | Low / Some concerns / unfinished / unfinished / unfinished | D2 acknowledges differential gastrointestinal effects as possible participant awareness, distinguishes awareness from trial-context deviations, and retains uncertain applicability of completer analysis to the abstract result. No final overall comparison is available. |

DAPA's current bundle passes both verifiers. This establishes structural and
source-binding validity, not correctness of every scientific inference. Its
D5 Probably Yes has an actual correspondence warrant: the applicable SAP
specifies the primary composite, time-to-first-event ITT Cox analysis and HR/CI;
the report says conduct/reporting followed that plan. The prospective protocol
commitment alone does not demonstrate final SAP timing relative to unblinded
access, which remains explicit uncertainty.

DAPA D3 is unchanged plausible Low, not an improvement in agreement. The old
run already related missingness to the 386/502 events. The current justification
cites those events but mainly uses the less-than-one-percent randomized fraction;
it does not explicitly explain potential effect or resolve missingness reasons
and timing. The two unknown vital statuses are no longer assumed independent
of the 20 incomplete follow-ups. Neither event counts nor all-randomized analysis
prove complete ascertainment. Existing guidance already asks for conditional
impact comparison and reasons/timing/outcome-dependence without a fixed threshold;
this run illustrates incomplete enactment of that guidance, not missing wording.

Albert stopped after more than 17 minutes without scientific/tool progress,
after draining D3 context twice. No MCP request was pending, but the isolated
model process remained alive. Its partial records and entire trace were retained;
no paid retry was launched. D2 Some concerns is a hypothesis requiring review,
not a demonstrated correction of the old Low judgment. The 77/90 and 67/72
one-year Table 3 counts must not silently establish the abstract result's
population while that correspondence remains unresolved.

## Remaining general failure mechanisms

1. Literal source binding does not establish semantic truth. Target substitution,
   ambiguous statistic labels and population correspondence require explicit
   typed uncertainty and researcher review; the null-statistic fix addresses one
   concrete seam, not all semantic errors.
2. Agents can cite event/loss counts without explaining missingness impact, even
   when guidance already requires it. Missing reasons/timing should remain gaps,
   rather than reassurance from an ITT label or a universal percentage threshold.
3. Prospective plan promises can become overconfident factual timing judgments.
   D5 calibration improved here, but actual applicable analysis correspondence
   and access timing must remain separately inspectable.
4. Context retrieval can dominate the loop. Albert re-opened and drained the
   entire D3 context after already draining it; DAPA repeatedly requested missing
   context while repairing rows. Compact status reduces one measured redundancy,
   but does not prove resolution of repeated context/schema-repair loops.
5. The Oct 1 alignment audit accepted 98/106 cases but found zero fully aligned
   (80 unknown, 26 mismatched). This prevents credible cohort accuracy claims
   until outcomes, time points, populations and estimands are adjudicated. It
   does not justify switching to an easier corpus.

## Verification and cost limits

A broad local run completed with **1129 passed, 8 skipped, 3 failed**. The three
failures asserted the verifier source line and were corrected; their focused
retest passed all three. Four absent historical/private test inputs have explicit
skip conditions rather than fabricated replacements. Relevant comparison,
workflow, semantics and verifier suites passed; current DAPA and both original
Oct 1 case bundles pass both current verifiers. Compact restart and visual checks
passed individually; lint/format/type checks passed on their checkpoints.

Background CI at `301de33` reported the same three source-line assertions and one
visual test expecting the old inline status quote. Focused repairs cover both
causes. Later CI is not a completion gate and must be reported as pending until
observed terminal; no claim of a fully green latest full suite is made.

Cumulative retained usage: Albert last observed 10,355,485 input tokens,
10,045,440 cached input, 41,949 output; DAPA completed with 12,184,613 input,
11,900,672 cached input, 31,012 output. These large cached contexts motivate
measurement-led compression. They are diagnostic expenditure, not an estimate
of cost per successful autonomous case. No extra paid cases, full benchmark,
merge, or demonstrated accuracy-gain claim accompanies this checkpoint.
