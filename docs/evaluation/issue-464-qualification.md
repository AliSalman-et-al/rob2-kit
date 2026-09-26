# Issue #464 qualification ledger

Decision: **hold**. This ledger does not contain a completed held-out campaign
or installed-host qualification. The ten development Trials are not eligible
as held-out evidence, and this record makes no scientific-accuracy claim.

The requester selected the existing `eval/` Trials for internal comparison.
All ten captured Trials have already informed development. The three later
uncoached Codex CLI assessments of ARASENS overall survival, TITAN rPFS, and
ENZAMET adverse events are retained under
`eval/runs/25-Sep-26/audit-successor-realistic-cases/`. Both product and
standalone commands verified all three finalized bundles. Their
[`smoke-review.md`](../../eval/runs/25-Sep-26/audit-successor-realistic-cases/smoke-review.md)
records Result-scope and decisive-warrant problems. These runs establish a
working host and bundle path while leaving scientific qualification on hold.

A later four-draw TITAN rPFS development comparison is documented in
[`RESULTS.md`](../../eval/runs/development-comparison-titan-pfs-2026-09-26/RESULTS.md).
Both baseline and both protocol-available draws completed; their bundles
verified independently. The normalizer marked all four Results
`scope_unverified`, and the receipt retained six unrun draws from the other
declared arms. It contributes no eligible provisional-label comparison and
does not change the held-out qualification decision.

## Implementation verification observed here

| Gate | Result | Evidence boundary |
|---|---|---|
| Focused qualification-report tests | Passed: 27 tests | `tests/test_qualification_report.py` only |
| Focused lint | Passed | Report validator, CLI, and focused test |
| Focused type check | Passed | Report validator and CLI |
| Repository formatter and type check | Passed on the integrated candidate | Ruff check and format passed for `src`, `tests`, `docs/release`, and changed comparison/benchmark scripts; targeted `ty` passed for `src`, `tests`, `docs/release`, and changed comparison scripts |
| Full test suite | Passed: 1042 tests, 3 skipped | `.venv/bin/python -m pytest -q` exited zero in 971.48 seconds after the final harness fixes |
| Public-contract checks | Passed | `ROB2_WORKSPACE="$(mktemp -d -t rob2-public-contract-XXXXXX)" .venv/bin/python docs/release/verify.py` exited zero |
| Independent bundle verification | Passed for all three smoke cases | `.venv/bin/python scripts/verify_bundle.py` returned `bundle verified` for ARASENS attempt 5, TITAN attempt 4, and ENZAMET attempt 4 |
| Installed-host checks | Partial | JSONL and bundle artifacts establish tool calls, review, and continuation; compaction, restart, structured/text/image visibility remain unqualified |
| Trial-separated, multi-platform held-out comparison | Not run | No comparison receipt or analysis artifact is attached |

The independently verified bundle byte identities are:

| Development smoke case | SHA-256 of `.rob2.zip` |
|---|---|
| ARASENS overall survival, attempt 5 | `8635b13b7c2cb825ccb32504767d2800066dcf44302230742ac45f4f1f65a67c` |
| TITAN rPFS, attempt 4 | `57be0bd87fcda1bc9841b0fec8c74344b5a404265eb6a1921689da4d28315e95` |
| ENZAMET adverse events, attempt 4 | `17bca40b15e5bba009a77cd4bbb468c58958211021ba72d731bc74bbd33d684d` |

## Evidence required before reconsidering promotion

1. Freeze the candidate identity, prompts, scorer, campaign split, platform
   versions, and all declared draws. Keep every outcome from each Trial in one
   split and retain failed, incomplete, and drawn attempts.
2. Run the declared baseline and successor cells on the untouched held-out
   Trials using at least two model families or materially different supported
   hosts. The current ten development Trials do not satisfy this gate.
3. For every frozen platform, retain installed-host evidence for tool calls,
   structured delivery, text delivery, image delivery, continuation, context
   compaction, restart, and review. Record artifact identities for the captured
   evidence; an unobserved check remains missing.
4. Run the repository formatting check, type check, full test suite, public
   contract verification, and independent finalized-bundle verification.
   Record each actual command outcome and the identity of its output artifact.
5. Produce a privacy-safe analysis artifact with source identity, per-arm
   three-class confusion matrices, Low/Some concerns/High support, non-Low
   support, High sensitivity (or explicitly unavailable), Trial-clustered
   uncertainty, Result-scope correctness, decisive-warrant validity,
   completion, provisional agreement, and cost. Cross-check agreement,
   class-recall, completion, and cost against the retained comparison receipt.
6. Evaluate the current ADR-0035 aggregation separately against retained
   provisional overall labels and label that basis as provisional. Do not call
   provisional agreement independently adjudicated accuracy. An absent
   reference class or fewer than two Trial clusters leaves the relevant result
   unestimable and the promotion gate on hold.

The report validator accepts only a complete, identity-bound qualification
v3 record. Historical v2 reports still replay structurally but are held by the
integrated gate. Missing or failed mechanical/host evidence, detached metric values,
unsupported class claims, or absent Trial-cluster uncertainty cannot authorize
`promote`.

For v3, `mechanical` has exactly one hash-bound result for each of
`formatting`, `types`, `full_test_suite`, `public_contract`, and
`bundle_verification`. A result is `passed`, `failed`, or explicitly `missing`.
`host_checks` contains exactly one hash-bound result per frozen platform for
`tool`, `structured`, `text`, `image`, `continuation`, `compaction`, `restart`,
and `review`. `diagnostics` contains a three-class matrix and Trial-cluster
interval for both frozen arms, plus a separate ADR-0035 overall-policy
evaluation. All source references are SHA-256 identities; private captures
remain outside the report.
