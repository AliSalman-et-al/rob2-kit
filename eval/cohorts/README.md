# 21 September 2026 evaluation cohort

`2026-09-21.json` is a post-hoc, held-out baseline joined from the pinned
assessment traces and the reference catalog. The importer binds each of its
140 Domain cells to the campaign, Trial, approved Result, Domain questions,
checkpoint, and source projection actually present in the trace.

Rebuild it from the checked-in labels and traces with:

```powershell
uv run python scripts/build_adjudication_cohort.py `
  --reference eval/reference `
  --run-root eval/runs/21-Sep-26/benchmark-trial-specific-luna-medium-20260921 `
  --model-labels eval/cohorts/2026-09-21-model-labels.csv `
  --output eval/cohorts/2026-09-21.json
```

The baseline reproduces 28 assessments, 140 Domain cells, 93 exact label
matches, and 47 disagreements, including the published per-outcome and
per-Domain totals. Reference and model labels are immutable inputs to the
comparison. No disagreement is assigned a scientific classification by this
artifact.

Independent reviewer identities, disagreement classifications, uncertainty
assessments, and review of the prespecified ten-cell exact-agreement sample
remain pending because they were not supplied with the pinned audit. The
development partition is intentionally empty; all 28 pinned cases are
held-out, and the manifest explicitly denies model access to adjudication
labels and rationales.
