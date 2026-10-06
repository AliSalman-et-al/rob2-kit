# One seeded production D3 attempt: MONARCH-plus

Frozen code df411cccbdffad707920523efc9a3774f4127039, `gpt-6-luna` medium,
CLI 0.159.0. The case was selected to test event/censoring accounting versus
actual PFS availability, not to favor a risk label. The approved target is
cohort A investigator-assessed PFS, abemaciclib+NSAI versus placebo+NSAI, all
207/99 randomized participants, at the 29 March 2019 interim cutoff. Approved
Result and D1/D2 checkpoints were seeded from the Code benchmark. Prior D3 and
later answers, active histories and derivative retrieval evidence were removed
from the active projection; historical canonical records were retained for
integrity and no history/status tool was exposed. This was not a cold
end-to-end assessment. Two local PDFs were restored with matching hashes;
registry raw bytes were unavailable. Its retained projection was not passed off
as verified raw JSON. Exact provenance is in the manifest.

## Outcome and limits

The single paid attempt lasted 139.06 seconds and started 16 tool calls:
4 context pages, 4 page-read calls (one registry integrity failure), 1 render,
1 visual selection, 1 text selection, and **5 rejected Domain saves**. No D3
checkpoint or final response was accepted in the model-owned workspace. All
owned MCP processes exited; no paid retry or second case followed.

The prompt allowed one correction. The monitor enforced wall/idle/tool guards
but did not automatically enforce this correction limit; the host stopped the
owned process after observing excess repairs. This monitoring failure is
retained, not hidden as a successful run. The interruption emitted no
`turn.completed` usage event, and the ephemeral CLI retained no thread/rollout
or token-count records in its fresh home. Exact input/cache/output consumption
is **unavailable, not zero**. Consequently the token thresholds could not be
verified or enforced in flight; they must not be represented as hard limits.
No usage estimate is substituted for actual billing. Any later paid workflow
probe should retain its local rollout usage events and automatically stop at
its correction limit before launch; no generalized harness was built here.

## Scientific versus structural findings

The first draft answered NI / No / NI / NI. Its D3.1 warrant explicitly
separates the 119 PFS events (66/207 and 53/99), ITT membership, treatment
stopping, and the two placebo-arm losses shown in the rendered profile from
actual ascertainment through cutoff. It does not infer material incompleteness
from unknown observed counts. This is a useful premise-adoption observation,
not a scientifically validated all-source answer or an accuracy gain. The
unavailable registry prevents full evaluation of its censored-patient accounting.
The stronger D3.2 No claim also warrants scrutiny: a cited result/disposition
passage is not by itself proof that no relevant missing-outcome sensitivity
analysis existed. Direct-support tags do not settle that scientific entailment.

Submission failed on wire shape: `use` instead of discriminator `kind`,
integer counterevidence, and repeated nesting of `context`/`limitation` fields.
The last rejected draft had only a nested limitation left to repair. In a
**separate offline copy**, flattening its existing limitation object, without
changing any answers, prose, source IDs or added evidence, produced a successful
production save and server-computed **High**, from D3.4 NI. This mechanical
control isolates the remaining wire failure from active-path or risk-table
failure. It is not an accepted model run; the original workspace and every
rejection remain preserved. See the original/repaired drafts and exact server
receipt. No scientific conclusion is supplied by structural acceptance.

## Changes and verification

The save tool now includes concise, generic examples of flat tagged Evidence
and limitation bases and describes counterevidence objects. It does not accept
invented aliases, infer a scientific answer, or weaken the typed contract.
Behavioral benefit remains untested; no paid follow-up was run.

Narrow inspection of the already completed 151c385 CI also found a stale public
contract output hash from earlier context changes, an outdated expected D3
proposition set, and three test dictionary-variance typing errors. The generated
contract snapshot and those fixtures/types were corrected. These are separate
from scientific judgment quality. 95 relevant tests passed, 2 skipped; typing
for src/tests/docs/release, focused lint/format and diff checks passed. No full
benchmark, merge, broad CI wait or extra model cycle ran.

Full local workspaces and source captures are retained outside Git. Published
artifacts exclude authentication files, home databases and stderr.
