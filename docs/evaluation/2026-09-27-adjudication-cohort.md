# September 26–27 adjudication cohorts

This import reconciles the two frozen benchmark campaigns against their selected
assessment bundles and the provisional label catalog. It records machine-checkable
provenance and score totals. The source reviews are AI-authored audit observations;
they are not independent human adjudications, and they do not calculate corrected
accuracy.

## Scores and scope

| Campaign | All requested cases | Primary exact/equivalent scope | Accepted-scope sensitivity |
| --- | ---: | ---: | ---: |
| September 26 | 85/130 across 26 cases | 51/70 across 14 cases | 63/85 across 17 cases, adding 3 proxies |
| September 27 | 78/130 across 26 cases | 70/120 across 24 cases | 78/130 across 26 cases, adding 2 accepted differences |

These totals reproduce the campaigns' original reports. Scope sensitivities are
shown separately because accepted proxies or scope differences do not have the
same status as exact or equivalent results.

## Trace and provenance

The trace inventory contains all 123 JSONL files found under the September 26–27
run roots: 59 files from September 26 and 64 from September 27. The files contain
6,461 completed items, 5,716 started items, three error events, and no malformed
JSON lines or identical-content duplicate groups. The selected benchmark bundles
refer to 52 September 26 segments and 54 September 27 segments. Seven additional
September 27 issue-465 end-to-end segments are inventoried separately.

Each of the 260 Domain cells retains the frozen Trial and outcome, expected and
observed labels, selected Result and review hashes, question and checkpoint
identities, source projection identities, and SHA-256 references to selected
trace segments. The reconciliation lists all 45 September 26 and 52 September 27
disagreements. Source-audit sidecars preserve question-level evidence and the
reviewer's identity and role.

## Source-audit coverage

The sidecars contain 65 question records for 28 case-Domain cells. Eight cells
are disagreement cases from September 27. The other 20 are the two campaigns'
predeclared matching-label samples. The first source review of ARASENS overall-
survival D3 found unsupported reassurance: deaths plus censorings do not prove
complete outcome availability. The new review also found unsupported
reassurance in LATITUDE adverse-events D4: the saved answer notes but dismisses
median intervention exposure of 24 versus 14 months without assessing the
unequal time at risk for a cumulative grade 3 or higher AE outcome. Both
question-level records are classified as likely model errors while their
matching Low Domain labels remain unresolved.

Across the 28 reviewed cells, source-audit support is two likely model errors,
18 agreement findings, five indeterminate findings, and three defensible
deviations. The LATITUDE question is classified separately from the two other
questions in that cell, whose reasoning is supported. In September 27, eight of
52 disagreement cells have source-audit records; the other 44 remain pending.
All 45 September 26 disagreement cells remain pending. The audit reviewed every
question in both ten-cell agreement samples, but it is AI-authored, not
independent expert adjudication or human certification. It does not change the
saved labels or calculate corrected accuracy.

Each campaign has a deterministic ten-cell agreement sample, with the seed and
all selected cells in the reconciliation artifact. The September 26 sample
pins the previously identified ARASENS OS D3 matching-label case, then selects
the other nine by seed; it is not a random prevalence sample. The September 27
sample selects all ten by seed. All 20 sample entries have
completed AI source reviews. The pre-existing ARASENS D3 review retains its
14:04 timestamp; the 19 additional cells were reviewed at 14:28 +05:00 on
September 27. Each new question record binds the saved justification to the
selected Result and original captured Source locators, including evidence
handles, page/line ranges, source versions, and selected trace hashes. The
remaining uncertainty and follow-up needs are recorded per question.

The reconciliation keeps separate fields for source availability (projection
observed in trace), retrieval (saved answer window or case inventory), context
delivery (not observable in JSONL), interpretation (sidecar or pending),
response mapping (trace judgment matched to the score), and policy attribution
(not assessed). This records what the artifacts establish without treating a
retrieved source as proof that the model received it or that a policy caused an
answer.

## Rebuild

Run from the repository worktree. The September 26–27 raw run roots must be
available in the original checkout; the generator reads them without modifying
assessment workspaces.

```powershell
$raw = "C:\Users\Ali-Salman\Documents\Code\rob2-kit"
uv run python scripts/build_september_adjudication_cohorts.py `
  --run-26-root "$raw\eval\runs\2026-09-26\rob2-trial-benchmark-luna-medium" `
  --run-27-root "$raw\eval\runs\2026-09-27\rob2-trial-benchmark-latest-8ae8016"
```

The command writes the cohort manifests and source-audit sidecar under
`eval/cohorts/`, plus the score reconciliation and full trace inventory under
`docs/evaluation/`. The score input hashes are retained in the reconciliation.

## Artifacts

- [`2026-09-26.json`](../../eval/cohorts/2026-09-26.json) and
  [`2026-09-27.json`](../../eval/cohorts/2026-09-27.json): immutable label,
  Result, review, question, checkpoint, and source-projection bindings.
- [`2026-09-27-source-audits.json`](../../eval/cohorts/2026-09-27-source-audits.json):
  65 source-located question-level audit findings, including all questions in
  the predeclared samples and all questions in the 8 reviewed disagreement cells.
- [`2026-09-27-cohort-reconciliation.json`](2026-09-27-cohort-reconciliation.json):
  all-case score, scope totals, disagreement inventory, sample status, and
  per-cell trace observations.
- [`2026-09-27-trace-inventory.json`](2026-09-27-trace-inventory.json): hashes,
  sizes, event counts, and selected/retry/E2E classification for every JSONL file.
