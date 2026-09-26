# Post-benchmark accuracy successor ticket breakdown

Status: approved and published on 2026-09-22.

Parent specification: [#427](https://github.com/AliSalman-et-al/rob2-kit/issues/427)

This breakdown contains entirely new tickets. Existing issues are related prior
work only. They are not blockers and will not be modified.

## Approved testing boundaries

- Exercise deterministic behavior through the public application/MCP contract.
- Exercise official activation and judgment mapping through the pure evaluator.
- Exercise benchmark preparation, execution, verification, and scoring through
  their command and artifact boundaries.
- Exercise actual delivery, restart, compaction, tool visibility, and review in
  installed hosts.
- Test externally visible behavior rather than private helper structure.
- Preserve the current overall aggregation policy and model-free authority
  boundary.

## Proposed vertical slices

### 01. Resume the intended host session or stop with a diagnosis

**Blocked by:** None.

**What it delivers:** A benchmark phase either resumes the exact recorded host
session with the expected tool inventory or stops before another blind attempt
with a typed, actionable diagnosis. Current and supported legacy session-event
shapes work, and model/effort overrides are explicit and recorded.

### 02. Record one replayable benchmark attempt from launch to verification

**Blocked by:** 01.

**What it delivers:** One immutable attempt record binds the case, declared
selection policy, prompt, Sources, build, pack, skill, contract, host, model,
effort, phases, resumptions, terminal outcome, artifact, and verification.
Failures and resumptions remain visible, and collecting the same run reproduces
the same identities.

### 03. Reject a verified artifact for the wrong Result

**Blocked by:** 02.

**What it delivers:** A new benchmark case is scored only when its approved
Result matches the expected Trial, comparison, endpoint definition, population,
window or cutoff, estimate, and precision. Any mismatch hard-fails before label
scoring; historical mismatches remain explicitly unscored.

### 04. Keep investigation choices visible after structural validation

**Blocked by:** None.

**What it delivers:** Status, Domain context, validation, and Trial review expose
one compact investigation view derived from the existing premise record. The
view separates the active proposition, observed coverage, supporting and
contrary Evidence, unresolved information, recovery choices, and stopping
rationale from the next permitted mutation. A valid draft may be saved, revised,
searched, read further, or retained with an honest limitation.

### 05. Preserve source observations across unrelated Domain revisions

**Blocked by:** 04.

**What it delivers:** Source-located observations remain resumable while the
captured Sources and approved Result are unchanged. A Domain revision marks only
dependent inference, drafts, and stopping decisions stale. A Source or Result
change invalidates affected material and gives an exact reorientation action.

### 06. Reconcile participant flow before D2 and D3 commitment

**Blocked by:** 04.

**What it delivers:** The host can inspect a source-bound chain from randomized
through eligible, treated, observed, analyzed, imputed, excluded, and event
counts for the exact Result. Incompatible endpoint, population, severity, unit,
or window quantities remain visibly distinct. Deterministic calculations expose
only verified consequences or bounds and never choose an answer.

### 07. Distinguish permitted care from trial-context deviations in D2

**Blocked by:** 04.

**What it delivers:** At the D2 decision point, the host receives concise
officially faithful distinctions and paired neutral examples separating an
ordinary or permitted treatment change from protocol-inconsistent conduct
caused by the trial context. The final answer remains host-owned and Evidence-
bound.

### 08. Keep D3 availability and missingness mechanisms separate

**Blocked by:** 06.

**What it delivers:** D3 presents outcome availability, mitigation, possible
outcome dependence, and likely outcome dependence as separate propositions for
the approved Result. It distinguishes event counts, analysis membership,
administrative censoring, unavailable outcomes, and genuine informative
missingness without fixed thresholds or suppressed High branches.

### 09. Keep D4 awareness, susceptibility, and likelihood separate

**Blocked by:** 04.

**What it delivers:** D4 context and review start from the approved outcome and
measurement method, then separately expose suitability, differential detection,
assessor identity and awareness, susceptibility to influence, and likely
influence. Paired controls cover objective and judgment-dependent outcomes
without automatic rules for mortality, open-label trials, or adverse events.

### 10. Bind D5 plan chronology and alternatives to the exact Result

**Blocked by:** 04.

**What it delivers:** D5 distinguishes document availability from plan
applicability, data cutoff from unblinded access, eligible measurements from
eligible analyses, and multiplicity from likely result-based selection. The
host can navigate source-bound versions and dates while remaining responsible
for chronology and the final answer.

### 11. Focus recoverable Domain context on the active premise

**Blocked by:** 04, 05.

**What it delivers:** The default decision view orders the exact Result, active
proposition, material gap or contradiction, decisive Evidence, compact relevant
guidance, and recoverable support. Context reconstruction remains deterministic,
and every omitted passage has an exact recovery operation.

### 12. Route versioned and layout-dependent Evidence without overstating it

**Blocked by:** 11.

**What it delivers:** Human-readable Source labels, logical sections, embedded
document/version spans, date meanings, and layout-dependent conditions route the
host to the right read or render action. Roles, dates, delivery receipts, and
visual transcription remain factual provenance rather than applicability or
comprehension claims.

### 13. Review facts, warrants, and answers before Trial closure

**Blocked by:** 05, 07, 08, 09, 10, 11, 12.

**What it delivers:** The existing same-host Trial review reconstructs each
material facts-to-warrant-to-answer chain and surfaces counterevidence,
population mismatch, chronology conflict, unsupported links, and accessible
uninvestigated routes. The host can reopen only affected Domains before closure;
no second model or duplicate full assessment is introduced.

### 14. Qualify the integrated successor without an adjudicated-accuracy claim

**Blocked by:** 01, 02, 03, 06, 07, 08, 09, 10, 11, 12, 13.

**What it delivers:** A predeclared Trial-held-out campaign compares the baseline
and integrated successor across at least two model families or materially
different supported hosts. Paired premise-changing controls and autonomous
source-grounded review measure Result scope, premise support, counterevidence,
unsupported concern and reassurance, completion, errors, context bytes, calls,
latency, cost, and provisional agreement separately. The final report makes a
bounded engineering promote-or-hold decision and explicitly avoids a claim of
independently validated scientific accuracy.

## Dependency rationale

- 01 establishes reliable session identity and host preflight before attempt
  provenance can be authoritative.
- 02 gives exact campaign and artifact identity to the Result-matching gate in
  03.
- 04 establishes the shared decision-facing investigation projection used by
  the scientific and context slices.
- 05 makes working observations safe to reuse before the focused context and
  final review depend on them.
- 06 establishes compatible quantities before D3 can reason about missingness
  mechanisms.
- 07–10 are independent scientific vertical slices once their shared input
  seams exist.
- 11 establishes focused, recoverable context before 12 adds version/layout
  routing and before 13 consumes the integrated review view.
- 13 integrates the scientific slices at the existing preclosure gate.
- 14 is the only integrated qualification ticket and starts after every
  behavior it compares is independently verified.

## Publication record

The owner approved the breakdown without changes. The tickets were published in
dependency order with `ready-for-agent`, parent #427, and native blocking edges:

| Slice | Issue |
|---|---|
| 01 | [#428](https://github.com/AliSalman-et-al/rob2-kit/issues/428) |
| 02 | [#429](https://github.com/AliSalman-et-al/rob2-kit/issues/429) |
| 03 | [#430](https://github.com/AliSalman-et-al/rob2-kit/issues/430) |
| 04 | [#431](https://github.com/AliSalman-et-al/rob2-kit/issues/431) |
| 05 | [#432](https://github.com/AliSalman-et-al/rob2-kit/issues/432) |
| 06 | [#433](https://github.com/AliSalman-et-al/rob2-kit/issues/433) |
| 07 | [#434](https://github.com/AliSalman-et-al/rob2-kit/issues/434) |
| 08 | [#435](https://github.com/AliSalman-et-al/rob2-kit/issues/435) |
| 09 | [#436](https://github.com/AliSalman-et-al/rob2-kit/issues/436) |
| 10 | [#437](https://github.com/AliSalman-et-al/rob2-kit/issues/437) |
| 11 | [#438](https://github.com/AliSalman-et-al/rob2-kit/issues/438) |
| 12 | [#439](https://github.com/AliSalman-et-al/rob2-kit/issues/439) |
| 13 | [#440](https://github.com/AliSalman-et-al/rob2-kit/issues/440) |
| 14 | [#441](https://github.com/AliSalman-et-al/rob2-kit/issues/441) |

No pre-existing issue was modified.
