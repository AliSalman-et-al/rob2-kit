# Two-case human-reference provenance audit — 2026-10-03

Read-only scope: DAPA-HF and DELIVER from the Code benchmark repository, September 29 dataset and October 1 campaign. No assessment, label or benchmark input changed; no model calls. New public evidence is dated and hashed separately, not an original benchmark capture.

## Reference recovered

[Neuen et al., DOI 10.1001/jama.2025.20834](https://jamanetwork.com/journals/jama/fullarticle/2841163), Supplement 1, eTable 2, physical page 4 matches the archived locator, trial order and labels. Both rows specify dapagliflozin versus placebo and five Low domains. The footnote binds ratings to each trial's primary outcome. No overall rating or per-result worksheet appears. Review assessors were B.L.N. and H.J.L.H. using RoB 2. Its pooled kidney endpoint is distinct from these trial-primary assessments.

This strongly reconstructs review identity, but does not establish archival chain of custody: retained workbook-source metadata lacks review DOI/title/hash and original workbook binaries are absent. Staplin's nearby review (10.1001/jama.2025.20835) has a different trial set and eTable 3 and does not fit. Access methods and limitations are recorded; no access challenge was bypassed.

## Findings

| Case | Supported reference scope | Unresolved selected-result binding |
| --- | --- | --- |
| DAPA-HF | Trial-primary endpoint and dapagliflozin–placebo contrast; D1–D5 Low, overall absent. Review reference 17 identifies primary report. | Archived full-cohort HR 0.74 (0.65–0.85), assignment effect over trial follow-up, is plausible reconstruction. Human table does not explicitly bind population, estimate, window or estimand. |
| DELIVER | Same contrast and trial-primary endpoint; D1–D5 Low, overall absent. Review reference 18 identifies primary report. | Archived overall-population HR 0.82 (0.73–0.92). Original Code primary PDF physical page 3 describes concurrent primary analyses overall and at LVEF <60%, with separate alpha allocations. Human table does not select a population branch or explicitly bind estimate/window/estimand. |

Review eTable 1 full cohort sizes (4744 and 6263) provide context, not proof of RoB assessment population. Median follow-up is not a fixed endpoint time. Host-asserted target_relation=exact concerns target versus reported result, not human-reference alignment.

## Decision

Keep both outside a fully matched selected-result accuracy denominator. They support descriptive primary-endpoint/contrast-matched warrant analysis. DAPA-HF is the stronger candidate for later independent, explicitly declared reconstruction adjudication; DELIVER retains concrete primary-population ambiguity. Do not relabel, recompute accuracy, infer overall Low or trigger paid runs. Available sources reviewed do not establish exact binding; this does not claim no further public evidence exists.

## Evidence and validation

JSON files preserve archived fields, unchanged Code source/archive hashes, new public retrieval provenance, findings, audit boundaries and CI snapshot. The public PDF and rendered page 4 support inspection. Raw public main-text retrievals remain outside git in ../diagnostics/human-reference-provenance/.

CI checked once: latest completed branch revision 6178e93 succeeded in [run 37138424879](https://github.com/AliSalman-et-al/rob2-kit/actions/runs/37138424879). HEAD e8f0157 was in progress (37139802441). No wait/recheck or new regression observed. Artifact-only checkpoint; no implementation tests rerun.
