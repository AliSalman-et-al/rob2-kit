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

## Offline transport refinement after the case diagnostic

A larger explicit context budget previously still forced separate section pages.
The transport now returns one complete page when the unchanged full projection,
including metadata and envelope headroom, fits that larger budget. Default
pagination, oversized-item checks, frozen cursors and completeness gates remain.
Offline replay of actual first D3 views changes Albert from four calls to one
(51,712 bytes), and DAPA from four to one (59,055 bytes), with all scientific
projection data exactly equal. No paid rerun was used. The oversized preview
still requires bounded pages; tests retain that path and prove complete-view
identity and the save continuation for the fitting path.

The Albert final page already supplied the correct save action. Its later
nonresponse therefore does not establish a transition bug or a pagination cause:
the prior duplicate drain is observed agent behavior, while the later inactive
model/provider call remains unexplained. Only task-owned isolated CLI processes
were stopped and their absence confirmed.

The new single-page path also exposed a registration seam: its only cursor is
`stable_recovery`, so view registration must use that cursor when both current
and next cursors are absent. A regression check now recovers the frozen complete
view and submits its Domain draft successfully. Focused ordinary cursor,
conditional-question and oversized-evidence checks passed, as did the large
preview pagination check; source type, lint and format checks passed. A broad
repository-wide type invocation included 67 diagnostics in existing scripts and
audit utilities outside the source-check scope; no blanket type-clean claim is
made for that invocation.

## Second lean round: preserve question-level retrieval provenance

Read-only inspection of the existing Code Oct 1 corpus covered 101 canonical
case states containing 964 D2/D3/D5 answer records. Search receipts include 1299
question-scoped requests across 72 case directories. In the retained tool captures, six active-candidate
groups in five cases pooled every passage under every Domain question. That is
an observed presentation defect in those groups, not evidence that all 101
cases have a scientific error.

Two source-verified examples motivate the change. Allsop's 15 D5 candidates came
from prespecification-purpose queries but were grouped under all three D5
questions. ENVISION pooled searches for missing-outcome availability with
searches for bias-correcting sensitivity analyses under all four D3 questions.
The recorded purpose is available in the existing receipt; the context projection
was discarding it. This makes the availability and bias-correction premises
harder to distinguish and can select an unrelated first-page evidence preview.

The projection now preserves unambiguous recorded question scope in existing
workspace groups and in typed comparison passage references. The first active
question's preview can use its associated candidate. All candidates and source
coordinates remain available in every comparison card; canonical identities,
answers, counterevidence and read recovery are unchanged. Search intent is
provenance, not proof of support or exclusivity. An unqualified or ambiguous
session remains broad, and an exact passage retrieved through multiple purposes
retains their combined scope. No risk label, trial name or percentage threshold
is encoded in the implementation. The default compact context does not newly
include candidates; this applies when candidate views are requested.

Focused checks exercise availability versus sensitivity evidence, first-page
preview, exact passage reuse across two questions, broad unqualified reuse,
unchanged candidate identity sets, and recovery of adjacent uncited source text.
Ordinary conditional-question delivery, frozen cursors after new searches,
existing active-question previews and question-preserving search continuations
also passed. Source typing and changed-file lint/format checks passed. No paid
rerun or broad test rerun was used; this is a tested presentation mechanism fix,
not demonstrated improvement in agent judgments or benchmark accuracy.

A tempting alternative was rejected after checking source and final reasoning:
142 unread literal SAP mentions occurred in five D5 No-information cases, but
all five final records had inspected applicable analysis plans. Their remaining
issue concerned chronology. Unread repeated headers or alternative versions do
not prove a missed applicable plan, and do not justify forcing Probably Yes.
Other suspect count-based D3 warrants, including evaluable mixed-model
populations, require outcome-specific source adjudication; grammar alone cannot
safely decide whether their availability judgments are wrong. This round does
not manufacture a decision rule for that unresolved scientific question.

Final cheap validation for this round: five focused context/search checks passed,
the strengthened multi-question/adjacent-read integration check passed, and 13
comparison-card/contract-budget checks passed. These checks establish projection,
reuse and recovery behavior, not a measured agent accuracy benefit.

## Final bounded pass and decision point

The remaining strongest source-verified hypothesis is semantic enactment after
reading, rather than another demonstrated delivery failure. AWARD-10 read its
registry's evaluable-data population definition (line 1323, recorded read window
1250–1330); its D3 Probably Yes warrant nevertheless treats the evaluable MMRM
population as near-complete availability while admitting observed week-24 counts
are unknown. MONARCH-plus read its censored-population definition (line 3190,
windows 3156–3337 and 3165–3339); its affirmative warrant leans on events plus
censoring accounting, while actual post-discontinuation assessment remains a gap.
GetGoal-Duo1 read the analogous postbaseline/LOCF definition (line 1830, windows
1816–1835 and 1830–1857) and retained No information about observed week-24 outcomes.
These contrasting warrants justify a targeted hypothesis, not a retrospective
error count or forced answer. Full-source adjudication is needed before deciding
whether the affirmative judgments are defensible.

Across the previously extracted D2/D3/D5 records, 55 counterpoints refer to bases:
27 direct support, 15 context, five contradiction, three indirect support and five
inference. Fifty non-contradiction counterpoints occur across 28 cases. A basis's
relationship kind therefore cannot alone identify counterevidence. The existing
checkpoint projection retains the actual counterpoint array and referenced bases;
no observed dropped-counterpoint mechanism justified another runtime change.
Instead, the existing cache-loss regression now covers direct-support and context
counterpoints with candidate delivery off. It checks implication/index preservation,
canonical identity retention and an exact source reread after derivative-cache loss.
The explicit-contradiction grouping check also passed. An initial test fixture
incorrectly duplicated an identical direct-support basis and was rightly rejected;
the corrected two variants passed. No unresolved failure from this focused batch
remains, and no broad suite rerun was made.

Reproducibility also needs a preflight decision: all 70 registry Sources in these
retained Code states lack raw bytes at their expected server-owned paths in this
checkout. Text projections and fingerprints survive; this does not prove that raw
bytes are unavailable everywhere. Exact future replay requires recovering matching
captures or explicitly declaring new captures as changed input. No registry data
were reconstructed or silently substituted.

The companion `2026-10-02-next-validation-proposal.md` proposes two cold-start,
D3-only probes using the existing AWARD-10 and GetGoal-Duo1 dossiers, with explicit
scope review, registry replay preflight and token/tool/time/idle stop guards.
It has not been executed. This is the decision point: validate the cumulative
mechanism changes and adjudicate their source-grounded warrants before adding
more unmeasured runtime rules. No new checklist, label heuristic or deterministic
semantic gate was manufactured in this final pass. Earlier test totals remain
checkpoint-specific; no latest-full-suite or latest-CI-green claim is made.

## Registry replay recovery follow-up

A bounded search of the authorized Code benchmark checkout, current archives and
reachable Git history found neither proposed case's raw registry hash. Logical
registry paths and physical source-ID paths were considered; path-independent
hashing covered 1051 current JSON candidates, 2122 archive members across 112
archives and 523 candidate Git blobs. The repository has one reachable commit.
There were no inspection errors, network captures, model calls or changes to
original benchmark data. This distinguishes absence in the searched scope from
an assumed path-remapping issue; it does not establish absence elsewhere.

Both full structured projections survive: NCT02597049 has 2323 lines and
NCT00975286 has 2205. Each reproduces its recorded projection identity using the
captured Source metadata and exact retained pages. That confirms projection
preservation, not recovery of the original source bytes. The isolated preserved
files are explicitly `.projection.txt`, not reconstructed raw JSON.

The AWARD-10 warrant used mixed-model analysis, denominators 132/134/133 and the
population receiving a dose with evaluable data. The GetGoal-Duo1 warrant used
mITT counts 221/215, at least one postbaseline assessment and LOCF. Those semantics
are inspectable in the retained projections; endpoint-observed week-24 counts
are not established by those fields alone. Any future new capture must be labeled
as changed input, fingerprinted and semantically compared before a model call.
The two-case D3 hypothesis and committed stop guards are unchanged and unexecuted.

## Supplied-evidence diagnostic cap preflight

The next authorized step changed from exact raw-input replay to two explicitly
labeled supplied-evidence projection diagnostics under current production D3
guidance, using `gpt-6-luna` medium. Its stricter caps were 30k total input, 20k
uncached input, 4k output, 15 tools, 8 minutes wall and 2 minutes idle per case.
A local strict-config check rejected the proposed hard completion-limit field
in installed CLI 0.159.0 before any model call. Completion-time usage observations
cannot guarantee an in-flight charged-token ceiling. The preflight blocker was
reported as required; no scientific output, retry, new capture or model substitution
occurred. Local structured evidence is retained in
`diagnostics/registry-recovery/diagnostic-cap-preflight.json`.
