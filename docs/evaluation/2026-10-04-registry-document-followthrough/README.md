# Public registry document follow-through

Two unrelated public study records were checked end to end: DAPA-HF
`NCT03036124` and ACTT-1 `NCT04280705`. Both matched the exact requested registry
identifier and official NCT-scoped document paths. The first has separate protocol
and SAP entries; the second additionally lists an ICF, which the planning-document
path did not fetch. This verifies those two observed layouts, not every possible
registry schema. Neutral fixtures cover combined protocol/SAP, missing, ambiguous,
mismatched and failed-fetch cases.

| Registry | Document | Metadata document date | Metadata upload | Retrieval | Pages |
|---|---|---|---|---|---:|
| NCT03036124 | [Protocol](https://cdn.clinicaltrials.gov/large-docs/24/NCT03036124/Prot_000.pdf) | 2017-10-26 | 2020-08-11 09:18 | captured 2026-10-04 | 103 |
| NCT03036124 | [SAP](https://cdn.clinicaltrials.gov/large-docs/24/NCT03036124/SAP_001.pdf) | 2019-07-23 | 2020-08-11 09:18 | captured 2026-10-04 | 52 |
| NCT04280705 | [Protocol](https://cdn.clinicaltrials.gov/large-docs/05/NCT04280705/Prot_001.pdf) | 2020-04-02 | 2020-09-16 16:07 | captured 2026-10-04 | 65 |
| NCT04280705 | [SAP](https://cdn.clinicaltrials.gov/large-docs/05/NCT04280705/SAP_002.pdf) | 2020-05-29 | 2020-09-16 16:08 | captured 2026-10-04 | 133 |

Exact retrieval timestamps, document hashes/lengths and statuses are retained in
[the first capture](../2026-10-04-registry-document-acquisition/public-capture.json)
and `NCT04280705-capture.json`. DAPA protocol SHA-256 is
`f2cf95437aa48759484b4bea996d56e2640d23c8467c81c640a4839a26322f5e`;
SAP SHA-256 is
`1ede27af86fb4859ebd7b7f0f1b4cf9e406c618f5a60c2b43c43b6351bed83f0`.
`verification.json` records all four distinct Source identities and hashes,
per-Source read/search checks and successful first-page rendering.

The 103-page protocol and 52-page SAP are separate protocol/SAP Sources; their
original bytes match their respective Source hashes. Each document produced
source-filtered search hits using a word from delivered text. Image-only sampled
pages remain image-reading tasks; rendering succeeded, with no model
comprehension claim. No Proposal or Domain judgments were created. Source records
have no prespecification-certainty field. Metadata warnings explicitly distinguish
role/date labels, plan finalization, unblinded access and actual conduct.

DAPA reading/search/render checks ran on a separate copy. All ten files in its
original current-capture freeze still match. Existing archived/current integration
tests prove archived registry byte hashes remain unchanged, current discovery
metadata is separate, capture versions have distinct identities, and retry does
not refresh an existing Batch. Neither benchmark corpus nor frozen Chua artifacts
were modified; these public captures are not exact October-1 replay.

A small general refinement now distinguishes registry metadata not marked
protocol/SAP (such as the observed ICF) from malformed/ambiguous metadata. The
original ACTT capture retains its earlier unsupported status; it was not rewritten.
The new distinction is tested with a neutral fixture. Another neutral test proves
an official CDN redirect to a private URL is not followed, and an arbitrary
metadata URL does not replace the NCT-scoped official filename route.

The explicit companion-source gap remains bounded in
[companion-design.md](companion-design.md). No existing DOI/public-URL intake path
was found. Candidate identity, public access/redirect safety and immutable captured
source scope need a separate staging boundary; that path was not implemented
piecemeal. An agent can currently request official registry planning documents
through `registry.acquire_documents=true` before prospective intake, then read,
search, render and select their Sources through existing tools. It cannot fetch
an arbitrary companion DOI/URL into an already prepared/approved Batch.

Raw PDFs and native capture workspaces remain local under
`diagnostics/registry-document-followthrough-20261004`; only code, tests and
provenance/hash reports are committed. No paid model call, gold, judgment,
automatic NI/PY, benchmark, merge or CI wait occurred. No accuracy gain claimed.

Validation: 28 targeted tests passed (registry acquisition, intake state integrity,
and pack descriptor compatibility); `ty check src tests`, focused Ruff and
`git diff --check` passed. These are delivery/safety checks, not scientific
accuracy evaluation.
