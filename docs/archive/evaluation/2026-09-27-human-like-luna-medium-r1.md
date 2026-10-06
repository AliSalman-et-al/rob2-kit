# Uncoached ENZAMET workflow check

This check used Codex CLI 0.157.1 with `gpt-6-luna` at medium reasoning. Each
outcome had a separate workspace, `CODEX_HOME`, source copy, session, and JSONL
trace. The initial prompts were exactly:

```text
/rob2-assess Assess risk of bias for overall survival in ENZAMET.
/rob2-assess Assess risk of bias for progression-free survival in ENZAMET.
/rob2-assess Assess risk of bias for adverse events in ENZAMET.
```

The only model-facing continuation was `Continue.` after each Proposal Review.
The human role inspected each proposed Result and approved its exact review
identity through `rob2 review`; no reference labels, desired Result, correction,
or suggested judgment was supplied to the model. The frozen case files and
reference labels remained outside the model workspaces. The runner used the
Windows `workspace-write` sandbox and separate temporary `CODEX_HOME`
directories. This is workspace isolation; the stricter deny-by-default host
profile was not used.

| Requested outcome | Approved reported Result | Proposal relation | D1 | D2 | D3 | D4 | D5 | Run |
|---|---|---|---|---|---|---|---|---|
| Overall survival | Overall survival; HR 0.67 | exact | Low | Low | Low | Low | Low | Finalized and verified |
| Progression-free survival | PSA progression-free survival; HR 0.39 | related | Low | High | Low | High | Low | Finalized and verified |
| Adverse events | Serious adverse events; 235/563 (42%) vs 189/558 (34%) | component | Low | Some Concerns | High | High | Some Concerns | Finalized and verified |

The frozen evaluation cases specify clinical progression-free survival (HR
0.40) and patients with grade 3 or higher adverse events (321/563 vs 241/558).
The PFS and AE selections therefore differ from those cases. The short user
prompts did not specify a PFS variant or an adverse-event severity threshold;
these differences are evidence about autonomous Result choice under that
ambiguity. Their Domain ratings should not enter a score against the frozen
labels without a separate Result-scope adjudication.

Both CLI phases exited zero with complete JSONL traces for all three outcomes.
OS first supplied a malformed evidence handle to `validate_proposal`; AE first
supplied an extra reported-Result field and later made two malformed
`save_domain_judgment` calls. The model recovered from those tool validation
errors and finalized. PFS and AE also had a shell command exit with status 1;
neither stopped the workflow. All three final bundles passed `rob2 verify` and
`scripts/verify_bundle.py`.

The retained [OS](../../eval/runs/2026-09-27/human-like-luna-medium-r1/runs/overall-survival/ENZAMET),
[PFS](../../eval/runs/2026-09-27/human-like-luna-medium-r1/runs/progression-free-survival/ENZAMET),
and [AE](../../eval/runs/2026-09-27/human-like-luna-medium-r1/runs/adverse-events/ENZAMET)
run directories contain `phase-1.jsonl`, `phase-2.jsonl`, phase metadata,
execution records, and the verified bundles. They are local ignored evidence,
not release artifacts. All three phase-1 records pin the same
`475ef1e378b9f1c030a79e0b3f82aba0cf622ee5d7e383a237bbbbd139bd554d`
build SHA-256.

This verifies completion and artifact integrity for the three uncoached runs.
It does not establish scientific accuracy or absence of defects. The 27
September cohort remains development evidence with external adjudication
pending; see [the reconciliation README](../../eval/cohorts/README.md) and the
[Result-scope report](2026-09-27-result-scope-report.md).
