# Bounded validation proposal — not executed

## Hypothesis

With the frozen improved kit, a fresh `gpt-6-luna` medium assessment can distinguish
observed outcome availability at the approved time point from analysis membership,
without being told a signalling answer. Success requires source-grounded warrants
and explicit remaining gaps, not agreement with a reference label. The earlier
intervened Albert/DAPA runs cannot establish this.

## Existing Code inputs

Use exactly these dossiers under
`/home/ali/Documents/Code/rob2-kit-benchmark/rob2-meta-set-full-2026-09-29/trials`:

- `award-10-2018`: `S2213-8587-18-30023-8.pdf`, `mmc1.pdf`,
  `other-AWARD10-poster-ADC2019.pdf`, and `sources.toml`.
- `getgoal-duo1-2013`: `2497.pdf`, `dc122462supplementarydata.pdf`,
  and `sources.toml`.

The first is a source-semantic stress case; the second is a comparator whose old
warrant already separated postbaseline/LOCF analysis membership from observed
week-24 HbA1c. Prior targets and source hashes are recorded in local
`diagnostics/next-validation-inputs.json`; they are audit material, not model input.

Before launch, adjudicate the exact endpoint, week-24 window, assignment estimand,
randomized population and contrast. AWARD-10's old target names all three groups,
while the approved reported effect may represent a narrower contrast. Do not
silently inherit that scope or compare unmatched judgments. A small probe could
pin dulaglutide 1.5 mg versus placebo; that choice needs explicit scope review.
The comparator targets lixisenatide versus placebo after the insulin-glargine
run-in, with the same background-treatment context.

Registry inputs need a preflight decision. The Oct 1 text projections and hashes
remain, but raw registry bytes were not found at the expected server-owned source
paths in this Code checkout (70/70 retained registry sources absent there). The
existing intake supports hash-checked registry replay. Recover matching original
raw bytes for NCT02597049 and NCT00975286 before claiming exact replay. Otherwise,
explicitly approve and fingerprint new captures as changed inputs; do not call
that an exact Oct 1 comparison or reconstruct raw JSON from flattened text.

## Minimal execution and review

Freeze one code commit and its exported skill. Use separate fresh case directories
and isolated model homes; expose no prior judgments, traces, gold labels or audit
conclusions. Verify the launcher/model catalog's exact model ID and medium effort.
Use the normal source/proposal workflow and record exact researcher scope approval.
Then assess only D3 and its activated questions, preserving all other domains as
pending; do not finalize or claim a full RoB assessment. This can test premise
handling cheaply. A full five-domain run would be a separate decision.

Use cold starts, not resumption of the old sessions. Maximum one proposal turn and
one continuation after scope approval per case. No automatic repair restart or
retry after failure; preserve scope failures and incomplete attempts. No source
replacement or answer coaching during a run. If the product requires earlier
Domain commits for a D3-only probe, stop and discuss scope rather than fabricate
them or enlarge the paid run.

Proposed stop guards per case: 1 million cumulative input tokens, 100,000 uncached
input tokens, 15,000 output tokens, 60 MCP calls, 20 minutes total, or 3 minutes
without scientific/tool progress. Stop at the first limit, retain all events and
classify the attempt as incomplete. Monitor cumulative rollout usage rather than
summing resume summaries. These guards are stop triggers, not a guarantee against
an in-flight request overshooting them. No extra case or retry is authorized here.

Review separately: source delivery, literal evidence validity, correct count roles,
justified inference, unresolved uncertainty, and scope match. An affirmative D3.1
answer needs actual endpoint-availability or follow-up evidence; analysis counts
alone do not establish it. A changed risk label is not itself success. Both cases
would be diagnostic only; neither establishes cohort accuracy or improvement over
All-Low. Decide whether to continue only after inspecting these two retained warrants.

## Replay preparation result

Authorized recovery inspection found no matching raw bytes for either registry
capture. It hashed 1051 current JSON candidates, 2122 JSON archive members from
112 archives, and 523 candidate Git blobs; this benchmark repository has one
reachable commit. No network fetch or model call was made. Both complete retained
text projections reproduce their recorded projection hashes and are preserved
locally as `NCT02597049.projection.txt` and `NCT00975286.projection.txt`, distinctly
from raw JSON. Details are in `2026-10-02-registry-replay-recovery.json`.

The existing raw-replay prerequisite therefore remains unresolved in the searched
scope; path-independent hashing found no moved copy there. A future approved
capture should be labeled `new_registry_capture_not_exact_oct1_replay`, retain
its new capture timestamp/raw hash/projection hash, and compare the endpoint,
population, imputation and denominator fields with the preserved old projection.
Record differences before any model call. Semantic similarity does not establish
byte-identical replay. The proposal and its guards above remain unexecuted.

## Authorized supplied-evidence diagnostic preflight

A later instruction authorized precisely two supplied-evidence D3 diagnostics
(AWARD-10 and GetGoal-Duo1) using the preserved projections and existing dossiers.
These would isolate interpretation under production guidance; they would not be
exact benchmark replay, natural retrieval, or end-to-end fresh assessments. No
raw JSON or new network capture is required for this distinct diagnostic.

The instruction tightened per-case limits to 30,000 cumulative input tokens,
20,000 uncached input tokens, 4,000 output tokens, 15 tool calls, 8 minutes wall
and 2 minutes idle, with no retry or third case. It required preflight reporting
before any model call if the harness could not safely enforce these caps.

Preflight stopped before launch. Installed `codex-cli 0.159.0` rejected
`model_max_output_tokens = 4000` under strict configuration validation as an
unknown field. This local check used an empty isolated auth home and a nonexistent
output-schema sentinel, and exited during configuration loading. No diagnostic
model turn started. No supported hard completion cap was verified. Completion-time
usage events can support monitored stop triggers, but cannot guarantee that an
in-flight response stays within a hard charged-output limit. A supported request
cap, or an explicit decision allowing monitored limits with in-flight overshoot,
is needed before launch. Neither the strict caps nor the model/provider have
been silently changed. The earlier broader proposal remains unexecuted as well.
