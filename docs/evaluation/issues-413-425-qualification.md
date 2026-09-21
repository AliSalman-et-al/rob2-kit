# Issues #413–#425 qualification decision

Date: 21 September 2026

## Decision

**Hold promotion.** The deterministic implementation and repository test gates
pass, but issue #424 also requires evidence that cannot be manufactured from
unit tests: real supported-host delivery transcripts, paired trial-separated
evaluation on at least two model families or materially different hosts, and
independent scientific adjudication of every material disagreement plus the
prespecified agreement sample.

The checked-in cohort is therefore a frozen baseline, not a corrected-label
dataset or an accuracy claim. It retains 28 assessments, 140 Domain cells, 93
exact matches, and 47 disagreements. All adjudication classifications and
reviewer provenance remain explicitly pending.

## Implemented candidate

- Complete, cursor-bound long-document navigation and canonical search-passage
  deduplication with distinct passage, page, and Source counts.
- Active-branch counterfactual evaluation and auditable conditional outcomes.
- Source-located working premise records, host-assertion attribution, exact
  Result scope, and compatible within-workspace fact reuse.
- Versioned Domain context with one stable page, compact deltas, and a frozen
  page-zero recovery cursor that preserves previews and candidate views.
- Mechanism-specific D3, proposition-separated D4, and plan-to-Result D5
  guidance at the decision point.
- A deterministic post-audit cohort importer and frozen held-out manifest. No
  independent adjudication result is inferred from catalog agreement.

The deterministic overall aggregation policy remains unchanged, as recorded
in ADR 0035. Its scientific fit is an evaluation question, not an implementation
override.

## Verification observed

```text
pytest -q: 766 passed, 6 skipped in 2348.59s (0:39:08)
ruff check .: passed
ruff format --check <changed Python files>: 26 files already formatted
release/contract group: 14 passed
issue-focused group: 114 passed
latest working-checkpoint/context regressions: 42 passed
git diff --check: clean (line-ending warnings only)
```

Relevant changed source and tests pass `ty check`. Repository-wide `ty check`
still reports nine pre-existing diagnostics in `scripts/analyze_rsi_runs.py`,
`scripts/collect_rsi_benchmark.py`, and `scripts/verify_bundle.py`; this gate is
not represented as green.

## Evidence still required for promotion

1. Capture installed-host transcripts for complete context delivery,
   continuation, premise recovery, compaction, restart, and review without
   answer coaching.
2. Run paired free-search, supplied-decisive-Evidence, context, retrieval, and
   guidance conditions on trial-separated held-out cases using at least two
   model families or materially different supported hosts.
3. Independently adjudicate all material disagreement candidates and the
   prespecified ten-cell agreement sample, preserving reviewer identity,
   uncertainty, and rationale.
4. Report confusion matrices and binary agreement separately from premise
   support, counterevidence handling, unsupported reassurance/concern,
   Result-scope correctness, completion, errors, context bytes, calls, latency,
   and cost.
5. Revisit the promote-or-hold decision using those observations, explicitly
   documenting gains, regressions, uncertainty, and residual failures.

