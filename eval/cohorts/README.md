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

# 27 September 2026 fresh campaign

`2026-09-27-fresh.json` registers the selected fresh campaign
(`9da4171216eb4d06a40889994e584a0f`) in the same immutable cohort format.
All 26 cases are marked as development evidence; the cohort has no held-out
partition and supports no held-out performance claim.
Rebuild both its cohort and the machine-readable trace reconciliation with:

```powershell
uv run python scripts/build_fresh_adjudication_cohort.py
```

The importer joins the selected attempt in `selected-attempts/index.json` to
the final assessed review receipt in its phase traces and the frozen
provisional-label catalog. It verifies 26 cases / 130 Domain cells, 83/130
exact agreement, 96/130 Low-vs-non-Low agreement, 2/26 exact overall agreement,
and the 104/130 all-Low reference baseline. These are catalog-agreement counts,
not adjudicated accuracy estimates.

`2026-09-27-fresh-reconciliation.json` accounts for all 102 same-day JSONL segments:
59 selected scored segments, 3 superseded original PEACE-1 PFS attempt segments,
33 unfinished unscored segments, and 7 issue-465 E2E segments. PEACE-1 PFS
attempt 2 is the selected replacement; the original attempt remains identified
but does not contribute to the scored 26-case cohort.

Its 57-row `review_matrix` binds all 47 disagreements and a deterministic
10-cell matching-label sample to the frozen reference catalog row and file
hash, selected Result, final assessment review, active questions, checkpoint,
source IDs and projection hashes, and a phase-specific trace locator. The rows
include active and driver question IDs and the assessed review event line, and
record whether evidence citations and expansions appear in the trace.
Decisive-evidence availability and scientific interpretation remain pending;
a source projection, Evidence handle, delivery receipt, or review call does not
validate entailment. No reviewer identity is present because independent review
has not been supplied. Both artifacts preserve pending classifications and
uncertainty.

A separate, source-grounded AI triage pass reviewed the 47 disagreements and
the ten predeclared matching-label controls. It identified four plausible
defensible-alternative mechanisms: PEACE-1 OS D2, CHAARTED PFS D4, PEACE-1 PFS
D4, and PEACE-1 adverse-events D4. The other 43 disagreement rows remain
indeterminate in that pass; two of those, ARASENS adverse-events D2 and D5,
carry an unresolved Result-scope caveat. No checked case establishes a uniquely
wrong model label, and the ten matching-label controls appeared plausible with
caveats; ARCHES adverse-events D1 retains a sequence-generation caveat. These
are AI triage leads, not independent expert adjudications or
corrected labels; matrix classifications and independent reviewer provenance
remain pending. The reconciliation's `source_triage_addendum` records those
provisional dispositions and links each candidate/control to its trace line and
source page/line locators by cohort-cell identity.

The campaign recorded 26 Result-scope decisions as equivalent, but this cohort
does not certify them as independent Result correspondence. ARASENS adverse
events is specifically flagged for review because the approved safety Result
uses treatment received, including one crossover in actual-exposure grouping,
while the frozen expected scope differs. The #480 review keeps this Result-scope
decision pending; its caveat also applies to the ARASENS AE D2/D5 triage leads.
The source-triage leads and unresolved facts are in
`docs/evaluation/2026-09-27-fresh-audit.md` and
`docs/evaluation/2026-09-27-fresh-audit-evidence/science.md`; they are not final
adjudications. The machine-readable premise contrasts are tagged for #476 and
#463 and bind each candidate cell to its question IDs and assessed trace line.
The trace handle alone does not establish source entailment. No adjusted
accuracy or held-out performance claim follows from this pending development
cohort.

# September 26–27 adjudication cohorts

The two September campaigns have separate [provenance and score
reconciliation](../../docs/evaluation/2026-09-27-adjudication-cohort.md).
They reproduce 85/130 and 78/130 all-case Domain agreements. The primary
exact/equivalent scope totals are 51/70 for September 26 and 70/120 for
September 27; accepted proxies and accepted scope differences are reported as
separate sensitivities. Every disagreement is present in the reconciliation,
and source-audited sidecars identify reviewed findings and pending cells.

The September manifests use all-development partitions because they are
post-run material. Labels and assessment traces remain unchanged. Source-audit
records are AI-authored observations, not independent human certification or
corrected accuracy. See the report for score details, review coverage, trace
inventory, limitations, and the rebuild command.
