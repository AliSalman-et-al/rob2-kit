# Explicit companion candidate staging

Implemented the small prospective staging path described in the prior
[bounded design](../2026-10-04-registry-document-followthrough/companion-design.md).
It does not insert Sources into an active assessment. The original workspace,
ledger, Source bytes and review bindings remain intact. Only input is copied to a
fresh workspace; the new workspace requires normal intake and researcher review.
The original captured remote Sources remain in the original ledger; they are not
silently converted to local captures in the new workspace. Copied registry
settings retain their normal current/replay behavior and must be reviewed.

Native agent action:

```sh
rob2 stage-companion --workspace CURRENT --reference reference.json --output NEW
```

The typed JSON request retains the Trial, supplied Source/page/exact citation,
requested protocol/SAP role, URL or DOI and linkage rationale. It rejects a
citation absent from the supplied page text and a locator absent from that
citation. Registry references may instead name a validated exact NCT-scoped CDN
PDF filename, as the actual registry JSON does. Image-only references require
textual recovery first. An existing destination or input symlink is rejected.

One explicit public PDF is acquired using HTTPX, with a 20 MB decoded byte limit,
20-second HTTP operation timeouts, identity content encoding, at most four validated requests, TLS verification,
no environment proxies, automatic redirects or persistent cookies. Each request
requires HTTPS, no credentials, a normal HTTPS port, an exact vetted hostname and
public DNS addresses. The document hosts are ClinicalTrials.gov CDN, PLOS journals
and PMC. Unvetted public hosts remain unresolved; this is not arbitrary web
acquisition. The allowlist limits DNS trust to those provider-controlled names;
this does not introduce a general pinned-DNS networking stack.

DOIs use exact [Crossref metadata](https://www.crossref.org/documentation/retrieve-metadata/rest-api/),
verify the returned DOI and accept exactly one advertised PDF link on the vetted
host list. No inferred publisher URLs, citation harvesting, PMC landing-page
scraping, OA-service expansion, browser challenges or paywall workarounds are
implemented. No supported unique link, forbidden redirect, failed access or
non-PDF response produces an explicit unresolved candidate, with readable
provenance. DOI metadata identity does not prove document identity or Trial
applicability. DOI success/unavailable/mismatch behavior was verified using
neutral HTTP fixtures, not a real DOI-to-fulltext acquisition claim.

Captured PDFs are validated with the existing PyMuPDF dependency, encrypted/empty
files rejected, hashes and observed NCT text retained. Requested role remains a
hint. Both PDF and provenance are explicitly declared `other` in the prospective
manifest; intake otherwise defaults undeclared PDFs to main_article. Matching,
missing, conflicting or multiple observed NCT strings remain qualified evidence,
never confirmation of applicability, prespecification, blinded access or conduct.
Metadata/dates in the cited source and DOI response remain separately readable.

## Real public delivery check

The native CLI fetched the protocol explicitly listed in ACTT-1 registry Source
`NCT04280705`, page 1, `Prot_001.pdf`:

- URL: https://cdn.clinicaltrials.gov/large-docs/05/NCT04280705/Prot_001.pdf
- Final capture started: 2026-10-04T19:58:24.115013+00:00; retrieval completed 2026-10-04T19:58:26.156043+00:00.
- 846,604 bytes; 65 pages.
- SHA-256: `99ccc83a958763aa2568591292d8489044f1e355f1d23f2d1977b1837b79f8c8`.
- PDF text contains `NCT04257656`; staging records conflicting/other observed
  identifiers, without deciding what that incidental reference means.
- Normal prospective intake produced an `other` Source, delivered pages 1–3 and
  five Source-filtered search hits. All 8 frozen parent-copy files stayed unchanged.

For this verification only, the new workspace's registry manifest was explicitly
changed to replay the retained provider JSON and disable new registry PDF fetches.
The product does not make that choice automatically. Details are in
[verification.json](verification.json); the exact request is in
[reference.json](reference.json). Two public fetches verified initial delivery and the final content-encoding bound.
The initial capture remains intact; the final capture records completion time and
PDF metadata separately. Both fetched byte hashes match the prior registry PDF.

Prior independent registry-delivery examples remain DAPA-HF `NCT03036124` and
ACTT-1 `NCT04280705`, with separate protocol/SAP Sources and unchanged old captures. Their prior 10-file
and 19-file freezes were rechecked successfully.
See [the prior verification](../2026-10-04-registry-document-followthrough/README.md).
These captures are current enrichment, not October-1 benchmark replay.

## Validation and limitations

50 targeted tests passed: explicit capture/intake/read/search and input/Source
version preservation, unknown/conflicting/matching observed registry identifiers,
exact DOI success/unavailable/ambiguous/mismatched metadata, public redirects,
forbidden/private/link-local/credential/downgrade destinations, private DNS,
timeout, compressed-response rejection, size cap, failed fetch and non-PDF content, existing registry intake
integrity and skill delivery. Type checks over src/tests, focused Ruff and diff
checks passed. Original ledger preservation means no active review/context
invalidation is needed; inline active-Batch additions are unsupported.

Downloaded PDFs and native workspaces remain local under
`diagnostics/companion-source-staging-20261004`. Only code, tests, requests and
provenance/hash reports are published. No paid model calls, judgments, gold,
answer coercion, benchmark, merge or CI waiting. No accuracy benefit claimed.
