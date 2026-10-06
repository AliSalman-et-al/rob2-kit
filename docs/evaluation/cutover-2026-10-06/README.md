# Final scientific-premise cutover

All ten fixed cases have finalized artifacts passing the product and standalone
verifiers. This is a development-exposed operational test, not a held-out accuracy
estimate or ten flawless autonomous first attempts. No accuracy gain is claimed.
The full 106-case benchmark remains off. All ten have bounded independent AI source reviews, with the scientific qualifications
below retained. Final reporting review and required exact-head CI remain separate
merge gates.

## Candidate and verification

The implementation supplies one complete source-bound official RoB 2 core across
D1–D5: all 22 questions/elaborations, relevant background, examples and scoped FAQs,
delivered through lossless bounded MCP pagination. Competing local answering rules
and comparison dependencies were removed. Comparison cards display the assessment
target, reported result and their relationship together. Structural verification
permits supported inference-based firm answers while retaining provenance, quote,
ownership, count, descriptor and historical-pack checks. These checks do not certify
source entailment. Companion acquisition accepts DOI citation boundary punctuation
and explains recovery from bare registry filenames without relaxing URL/host checks.

The final production revision `d77b16fe85f2265a3b393d49d9dde54ab0b2baec`
passed a clean full regression: **1,663 passed, 8 skipped**, exit 0, in 3,508.85 seconds.
The complete log SHA-256 is
`64e9ee7a1129b3b020ef41c905de00c6155e4c23ad6e417a7e43d68bc2c4b291`.
Its normal installed-wheel release verification passed for all five Domain projections,
the workflow and both verifiers. Wheel SHA-256:
`63b232e4da69fc2878f6d7e925fc17add92383739d19f7292426b901a11e4038`.
See the [regression receipt](final-regression-receipt.json) and
[installed-runtime receipt](post-doi-installed-runtime.json).

The `45326861` overlay changes only test decoding/formatting, historical-fixture
checkout attributes, CI concurrency and review receipts. Independent portability/
architecture review gives scoped GO; no production, scientific, verifier, dependency,
skip or guard change occurred after the tested production revision. Focused portability
checks passed 28 tests; ownership concurrency passed separately. Explicit cp1252 and
Git autocrlf controls preserve Unicode guidance, frozen fixture bytes and the intended
EXSCEL missing-evidence rejection. CI concurrency preserves jobs, matrices and permissions.
The subsequent `ea9c024` Windows 3.13 job exposed a remaining test-only newline
mismatch: raw CRLF reference bytes embedded by the runner versus universal-newline
translation in the expectation. The existing full-content assertion now compares
raw UTF-8 decoded bytes. A negative control reproduced the mismatch, the corrected
CRLF control passed, and all four runner tests passed. The runner and source bytes
are unchanged. See [byte-recovery receipt](windows-reference-byte-recovery.json).
A later Windows job at `81a5d52` reproduced an ownership-fixture barrier timeout.
The fixture now creates/resolves its shared parent before the controlled exclusive
workspace claim. Timeouts, the one-winner/one-exact-rejection assertions and source-byte
checks are unchanged. Twenty repeated controls and all 23 RSI-script tests passed;
a bypassed ownership guard was rejected. This is fixture isolation, not a claim of a
proven production defect. See [ownership fixture receipt](windows-ownership-fixture-recovery.json).
Required checks must pass on the final PR head before merge.

## Fixed cases and recoveries

The source corpus is the original `/home/ali/Documents/Code/rob2-kit-benchmark`
at `d04473df4a07a3117f3171df2d8471ec0defd522`, not older main-repository evals.
The eligible manifest, OS entropy, sorting algorithm and fixed order were frozen
before selection. No exclusions, redraws or replacements occurred. All ten cases
have original benchmark development exposure; additional prior exposure is recorded
or remains unknown. Human reference labels were excluded from model inputs.
The alignment audit found zero fully aligned cases, with 80 unknown and 26 mismatched
among 106; matching these references cannot establish accuracy.

Implementation used Sol Low. Every observed assessment turn used exact
`gpt-6.1-sol` / `medium`, checked from durable session records. Normal scope approval
was source-checked and supplied no Domain answers or preferred labels. Proposal-to-
assessment continuation is part of the workflow, separate from technical recovery.

| Fixed order | Case | First-attempt disposition and later completion |
| --- | --- | --- |
| 1 | [Albert 2013](albert-2013-sealed-answer-source-projection.json) ([completion](albert-medium-host-recovery.json)) | Proposal and five Domains completed; export blocked by a retired verifier predicate. Host-only export after the reviewed fix finalized the unchanged answers, with no paid rerun. |
| 2 | [SUSTAIN-6](sustain-6-sealed-answer-source-projection.json) ([completion](sustain-medium-operational-completion.json)) | Proposal completed; first assessment stopped idle. Preserved same-session technical recovery finalized. |
| 3 | [Bendix 1996](bendix-1996-sealed-answer-source-projection.json) ([completion](bendix-1996-medium-operational-completion.json)) | First proposal and assessment completed natively; scientific D2.6 qualification retained. |
| 4 | [TESTING](testing-sealed-answer-source-projection.json) ([completion](testing-medium-operational-completion.json)) | First proposal and assessment completed natively; self-corrected proposal relation validation retained. |
| 5 | [Beerendonk 1999](beerendonk-1999-sealed-answer-source-projection.json) ([completion](beerendonk-1999-medium-operational-completion.json)) | First proposal and assessment completed natively; source-checked component scope retained. |
| 6 | [Chua 2022](chua-2022-sealed-answer-source-projection.json) ([completion](chua-2022-medium-operational-completion.json)) | First proposal and assessment completed natively despite companion acquisition failures; those failures remain recorded. |
| 7 | [MONALEESA-2](monaleesa-2-sealed-answer-source-projection.json) ([completion](monaleesa-2-medium-operational-completion.json)) | First proposal stopped idle with zero completed responses. Preserved same-session proposal recovery and subsequent assessment finalized. |
| 8 | [STOP-IgAN](stop-igan-sealed-answer-source-projection.json) ([completion](stop-igan-medium-operational-completion.json)) | First proposal and assessment completed natively; source conflict and allocation-timing qualification retained. |
| 9 | [`sanctuary` archive slug: felzartamab IGNAZ, NCT05065970](sanctuary-sealed-answer-source-projection.json) ([completion](sanctuary-medium-operational-completion.json)) | First proposal and assessment completed natively; stale-context recovery and two native public-source acquisition/admission extensions retained. |
| 10 | [FR-AS 2018](fr-as-2018-sealed-answer-source-projection.json) ([completion](fr-as-2018-medium-operational-completion.json)) | First proposal and assessment completed natively; normal self-review revisions and one native public-document extension retained. |

The first two used the original frozen runtime `0dc9002` (production identical to
installed `98f3ea7`). Albert's host-only corrected export is a separate verifier
stratum. SUSTAIN's same-session recovery used its original runtime. The remaining
eight used frozen `7d116f9eea98d3f8aa308c0400d2026f7c64e90d`, which does not
include the later DOI fix. No case was silently rerun under the final implementation.

Chua's later unpaid technical replay first demonstrated the DOI validation fix,
then exercised native acquisition, admission, listing and reading of the cited
NCT03396094 document through the existing allowed CDN route. Its original answers,
Sources and sealed session stayed unchanged. The captured document's role and
applicability remain qualified. SANCTUARY’s two public PDFs/sidecars and FR-AS’s one public document, marked
`cited_public_document`, were the only assessment source augmentations and occurred
normally within their assessment sessions; current registry documents are dated
augmentation, not substituted historical evidence. See
[DOI replay](chua-doi-technical-replay.json) and
[native registry replay](chua-registry-native-replay.json).

The inherited `sanctuary` identifier refers here to the original manifest’s
felzartamab IGNAZ/NCT05065970 dossier, not the ravulizumab SANCTUARY study.
The original fixed identifier and source target are preserved; no case was redrawn
or silently renamed. Future label matching must use the actual study identity.

## Scientific interpretation and limits

Artifact integrity, scientific support and reference agreement are reported separately.
Independent source-aware AI review found a material consequential overconfidence in
Bendix D2.6: contactability and exclusion do not establish that observed workability
outcomes were discarded. Missing-only omission versus a distinct completer-restriction
mechanism remains unresolved. Original answers were preserved rather than rerun toward
a preferred label. D3 concerns remain independently supported. See
[Bendix qualification](bendix-source-warrant-qualification.json).

Albert, SUSTAIN and TESTING retain source/population/model/timing conflicts and
qualified warrants; SUSTAIN's ITT label alone is not reassurance and its SAP date
does not prove pre-unblinding timing. MONALEESA distinguishes efficacy/safety counts,
discontinuation/censoring and planned/conducted sensitivity analyses. STOP-IgAN keeps
randomized, observed and imputed populations separate; its minor D1 allocation-timing
uncertainty qualification is retained. Large protocol binaries and selected visuals
were not all independently rendered by reviewers. Operator visual checks are recorded
separately and do not erase these review limits. See
[first four reviews](first-four-independent-scientific-review.json) and
[MONALEESA/STOP reviews](monaleesa-stop-independent-scientific-review.json).

Beerendonk’s independent closure found no material unsupported premise. Chua’s
D1–D4 warrants were defensible; its D5 acquisition gap arose from the verified DOI
parser defect. The later technical repair/replay does not give the original assessment
retrospective source credit or alter its answers. These are source-aware AI review
findings, not expert accuracy certification; the detailed review was relayed by the
parent, and no blanket independent rendering of all raw source binaries is asserted.

The final IGNAZ and FR-AS review found no blocking material scientific defect and
supports qualified operational closure. It corroborated the three-dose Part 1 UPCR
target, PPS/exposure versus missingness distinction, central-laboratory UPCR and
July 2023 direct-percent SAP addition after April unblinding. For FR-AS it corroborated
all eight 26-week HbA1c contrasts, mITT/post-rescue distinctions, protocol rescue and
central-laboratory rules, and the publisher-supplement/SAP prior/model discrepancy.
Six FR-AS rescues are reported, but individual indications and timing are unknown;
the protocol also classifies more than 14 days of required insulin as rescue. The
claim that all six were proven sustained-high-FPG rescues is therefore unwarranted;
the broader D3 concern remains defensible. The review checked 44 archived matching
passages plus official protocol/SAP/publisher-supplement text. Full binary/visual
glyph verification was unavailable and is not claimed. See the
[final scientific review](final-independent-scientific-review.json).

## Usage and preserved evidence

The ten sealed sessions contain **883 unique observed response identifiers**:
105,715,177 input tokens, including 101,188,608 cached input tokens; 258,006 output
tokens, including 33,684 reasoning output tokens. Cached input and reasoning output
are subsets, not additional totals. Dollar cost and provider-internal/unrecorded
idle usage are unknown. These figures cover observed final Medium sessions including
preserved same-session recoveries, not the superseded Low development experiments.
See the [final ten-case ledger](final-ten-case-report.json) for per-case hashes and observed usage.

All ten artifact bytes match their sealed receipts. Original inputs, source captures,
failed attempts, launch/preflight logs, scope approvals, session prefixes, canonical
histories and finalized artifacts remain preserved. Earlier receipts are historical
snapshots and are not rewritten to erase active, failed or superseded states.
The archive branch `archive/scientific-premise-20261006` preserves checkpoint
`800f4afaadc1b1bb913fa3414b7e91e3b49d33f6`; the raw Code corpus is unchanged.

For chronology, follow the [execution protocol](execution-protocol.md),
[original freeze](final-medium-freeze.json), [amended freeze](verifier-amended-medium-freeze.json),
[verifier recovery](verifier-uniform-basis-recovery.json), per-case completion and
sealed projection receipts, and [experiment disposition](experiment-disposition.md).
The earlier 14-failure aggregate, failed followups, two-case held-launch interval and
active-recovery receipts describe prior states; they do not contradict the terminal
regression and operational results above.
