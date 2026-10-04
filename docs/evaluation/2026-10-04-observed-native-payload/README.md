# Observed native delivery, not repository schema totals

This audit uses the completed Bagg native D5 run, its permitted rollout, frozen
instructions, config, and exported public MCP tools. No inference was launched.
It reads no credentials, SQLite session indexes, unrelated sessions, account
metadata, or encrypted reasoning. `measure.py` exports counts, field paths, and
hashes, not source quotations. The original Code benchmark PDFs remain the source
corpus; no older main-repository evaluation was substituted.

The frozen implementation was `f7bbe3886a578fd8da7837a4cbf04bc1a1eff699`.
The current implementation before this audit is
`e6b13031ddfa72437f3e1f2f9ca3b38ea58a064c`. This audit changes no production behavior.
Its before/after model-facing payload therefore remains unchanged. It is an
evidence checkpoint, not an accuracy or efficiency improvement claim.

## What the model demonstrably received

The recorded first provider input was **24,237 tokens**, zero cached. The supplied
instruction file was **71,401 UTF-8 bytes**. Eleven tools were enabled, including
the normal source, visual, context, checkpoint, and judgment tools. There were 19
tool calls and 18 retained tool outputs. The accepted final judgment receipt is
in the run artifacts but absent from the provider rollout: no further provider
response followed it. Do not count that receipt as a demonstrated model exposure.

| Retained output | Count | Compact JSON bytes |
| --- | ---: | ---: |
| Domain context | 4 | 58,677 |
| Page reads | 5 | 93,679 |
| Status | 2 | 10,510 |
| Source inventory | 2 | 10,688 |
| Source search | 1 | 7,017 |
| Evidence selection | 4 | 8,625 |
| Total | 18 | 189,196 |

The actual tool-output strings, including native wall-time/output prefixes, total
**189,808 bytes**. Source `quote` and `numbered_text` strings contain **98,694
bytes**. Neither quantity is an estimate of tokens or per-response input cost.
The durable usage records report 981,058 cumulative input tokens, including
890,624 cached and 90,434 uncached; repeated retained context affects successive
requests, so output bytes and cumulative input tokens have different meanings.

The rollout does **not** retain the serialized provider tool definitions. For the
11 enabled tools, exported reconstruction is 62,890 input-schema bytes, 287,967
output-schema bytes, 8,888 description bytes, and 9,104 metadata bytes. Those
objects are not proof of what the provider received. The earlier approximately
503 KB total across all 18 repository tools must not be presented as measured
prompt overhead. No exact tool-definition token cost is claimed here.

## Duplication and reduction decision

Nine exact strings longer than 100 characters recur in tool outputs; redundant
occurrences total **6,710 UTF-8 bytes**, not 6,710 tokens. Of those, 3,757 bytes
are the 221-byte authoritative workflow wording repeated in 18 response heads.
Three repeated official D5 excerpts contribute 1,379 bytes: the questions and
the top-level provenance-bearing official guidance both contain them. Other
repetition includes target/result facets and two equal search previews. Paths
and hashes are retained in `metrics.json`.

Normative field costs and recovery field costs are recorded individually. These
categories can nest and overlap; summing them would overstate their share. The
complete source reader already has a single `numbered_text` field and no duplicate
raw `text` field. Comparison-card passages are navigation references, not copies
of full quotations. No lossless large source duplication was demonstrated.

This evidence does not justify removing official question guidance, source text,
active coverage, or recovery information. Removing 1.4 KB of duplicate excerpts
would require changing an existing public presentation without evidence that it
caused the scientific errors. Shortening repeated workflow wording would be a
small metadata edit, not a demonstrated source-to-judgment improvement. There is
no new flag, wrapper, tool, cap, truncation, question projection, or trial rule.

## Remaining scientific failure hypotheses

| Observation | Status | Testable failure hypothesis |
| --- | --- | --- |
| Freeman D3 imports poor medication adherence from CBD 200 mg into CBD 400 mg/placebo reasoning | Demonstrated source attribution error; canonical path and label remain valid | The model reads the whole multi-arm figure but does not bind each reason to the approved comparison before writing its warrant. |
| Bagg D5 claims alternatives were reported, but selected bases omit the actual relevant results | Demonstrated citation coverage gap; does not prove the No answers wrong | Reading a results table and citing a methods passage can be conflated with evidence that the eligible results were fully reported. |
| Bagg D5 original protocol measurement times were not reconciled with later SAP/report | Demonstrated unexamined source, uncertain eligibility and selection consequence | Latest-plan correspondence is treated as exhaustive reconciliation; earlier alternatives require scope evaluation, not automatic bias. |
| Bagg 5.1 NI despite earlier plan and blinded-statistician intent | Qualified judgment, not demonstrated error | Timing of actual unblinded access remains unknown; NI and a supported probable inference may both be defensible. No timestamp gate is warranted. |
| Aarnoutse D2 confidence about PK analysis applicability | Underexplained qualified judgment, not demonstrated wrong | Intended PK sampling and assignment analysis can be confused with completeness or representativeness of the analyzed subgroup. |
| Target/report mismatch and Albert conflicting estimates | Established interpretability limit | Exact endpoint, group, window, population, and estimator must match before benchmark agreement is meaningful. |

Canonical acceptance verifies shape, evidence identity, branch coverage, and
durability; it does not verify that a passage entails a scientific assertion.
The compact citation path preserves this distinction. Existing synthetic offline
fixtures can demonstrate faithful resolution and rejection, not correction of
the Freeman attribution error or measured agreement with human reviewers.

## One next held-out test

Use **AWARD-1 2014 D3** from the actual Code benchmark repository, including both
`2159.pdf` and `dc132760supplementarydata.pdf`. It is a proposed holdout from these
native diagnostic cases, not a claim of no historical benchmark exposure. Before
launch, freeze the exact benchmark Result, verify its comparison and endpoint
against both sources, and independently enumerate each arm's missing-outcome
counts and reasons with page/line or figure locators. If this inventory lacks a
distinct out-of-comparison reason, this proposed attribution test is not valid;
do not launch it merely to obtain completion.

Run one paired comparison on that one frozen case using the verified existing
isolated `gpt-6-luna`, medium launcher: the pre-change and candidate implementations
must differ only in a justified generic source-attribution improvement. Both
receive the full figure and source corpus. Freeze the criterion before launch:
every missingness reason asserted in the D3 warrant must belong to the approved
arms or be explicitly identified as outside scope; uncertainty, full evidence,
and canonical checks must remain intact. Demonstrated benefit requires the old
run to make a source-verified attribution error and the candidate to avoid it,
without losing supported reasons. If both are correct, report no measured gain;
if both err, reject the hypothesis. Label agreement and completion alone do not
pass. This proposal authorizes no paid calls; full benchmark remains off.

## Offline validation

At the current production HEAD, `tests/test_lean_domain_submission.py` passed
**9/9** in 44.28 seconds. It covers ordinary read/selection and supported or
uncertain D2/D3/D5 submission through canonical storage, preservation of actual
source quotes and unknowns, and rejection of malformed/unsupported references
and incomplete scientific claims. No working observation is required. No new
behavior was introduced, so no fabricated before/after gain is inferred from
these tests.

Reproduce measurement with `measure.py ROLLOUT native-tools-list.json
home/config.toml native-instructions.md metrics.json`, using only the preserved
Bagg diagnostic artifact paths. The script deliberately ignores session metadata,
world state, and reasoning rows. Production source and source availability are
unchanged; this checkpoint includes only the audit and reproducible measurement.
