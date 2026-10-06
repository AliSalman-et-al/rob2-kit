# Bounded explicit companion-source design (not implemented)

Audit: the only network acquisition clients in the product are exact
ClinicalTrials.gov JSON capture and its newly added NCT-scoped document capture.
`sources.toml` supports contained local path/file declarations, not URL/DOI
locators. `list_sources`, search and readers operate on already captured Sources.
There is no existing public URL/DOI path to expose. A prepared Batch is immutable;
its Sources, approved scope and evidence references are bound to that capture.
A generic fetch cannot silently add an uncertain publication to an approved Trial.

This crosses two boundaries beyond the present small registry path: public URL
redirect/access safety and staged publication/Trial identity. The authorized stop
condition is therefore used: keep the verified registry feature and specify a
concrete narrow next path. No general crawler, inline admission mechanism,
per-publisher scraping or partially safe downloader was added.

The smallest prospective implementation should stage one explicitly cited
candidate into a **new dossier version before intake**, rather than mutate an
approved Batch. Suggested CLI/API request vocabulary (design only):

```json
{
  "locator": {"kind": "doi", "value": "10.1234/example"},
  "trial_id": "trial-a",
  "registry_id": "NCT00000001",
  "requested_role": "protocol",
  "cited_by": {"source_id": "source_example", "page": 3, "citation": "explicit citation"},
  "destination": "new-dossier-version"
}
```

Exactly one DOI or public HTTPS URL; retain the locator and citation as caller
assertions, not verified facts. Resolve a DOI through an exact official metadata
lookup; reject returned DOI mismatches and ambiguous matches. Record title,
publisher, dates, DOI and response hash as metadata. Crossref's
[REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
provides publication metadata, not a guarantee of publicly retrievable full text.
For a supported PMC identity, the
[PMC OA service](https://pmc.ncbi.nlm.nih.gov/tools/oa-service/)
is a candidate official file-discovery boundary; public-page availability must
not be treated as permission to scrape or as proof of an OA PDF.

Only explicitly advertised supported public full-text/PDF links may be fetched.
Start with a narrow vetted official-host set; unsupported publisher hosts remain
candidate locators. Verify each redirect before issuing its next request; reject
private/reserved destinations, file URLs, userinfo/credential URLs, HTTPS downgrade
and unbounded redirect chains. No authentication, paywall circumvention, browser
challenge workaround or guessed publisher URL. Missing PDF, inaccessible content,
provider error and unsupported host remain separate nonblocking outcomes.

Validate PDF/public full-text bytes and preserve requested/resolved URLs, redirect
chain, DOI/provider identity, document dates, capture time, media type and byte
hash. Preserve each capture under a new version identity. A matching DOI verifies
publication metadata identity, not Trial applicability. Registry identifiers and
explicit citations supply linkage observations; conflicting or missing linkage
stays uncertain. Record `trial_relation=unverified` by default. Keep the requested
role as a role hint; stage uncertain material as `other` with a qualified candidate
label, never as a confirmed applicable protocol or prespecified SAP.

A staged candidate PDF/text plus its provenance JSON can use the existing local
Source inventory/search/read/render/select mechanisms after a new prospective
intake. Reading and plan-versus-conduct/timing/applicability assessment remain
host work. Importing original archived assets into a new dossier preserves their
bytes and provenance; that corpus is explicitly enriched/current, not exact
October-1 replay. Inline use during an already approved assessment would require
separate source-scope/revision and bundle-verifier design, outside this proposal.

Acceptance fixtures before implementation: single explicit DOI and explicit
supported URL; public allowed redirect; unsafe redirect and credential/private
URL; DOI mismatch; multiple/ambiguous DOI matches; no full-text link; HTML/paywall
instead of PDF; timeout/404; PDF identity or registry-link conflict; unknown Trial
relation retained; role hint not promoted; unique versions and archive preservation;
normal reader/search visibility after prospective intake. These are a test plan,
not executed DOI-path tests. No DOI acquisition exists in this checkpoint.
