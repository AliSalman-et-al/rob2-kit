# Official registry-linked protocol/SAP acquisition

Audit found a substantive acquisition gap: intake fetched an exact verified
ClinicalTrials.gov study record (or replayed an archived response), but retained
only its JSON. It did not retrieve PDFs identified by `documentSection` /
`largeDocumentModule` / `largeDocs`. Existing source inventory, projection,
search, reading, image rendering and provenance-aware Evidence already support
PDF protocol/SAP sources. No equivalent remote-document tool was disabled by an
experimental allowlist. The fixed experimental dossiers and already prepared
Chua assessments therefore remain unchanged; no retrospective upgrade is made.

Prospective intake now supports this explicit dossier option:

```toml
[registry]
nct = "NCT########"
acquire_documents = true
```

Default remains false, including archived registry replays. Opting in with an
archived replay fetches **current** official metadata separately, preserves the
archived registry Source/bytes, and records the new discovery response as another
Source. A prepared workspace is immutable/idempotent: retry does not refresh it.
Acquisition needs a new prospective workspace/dossier version; it does not append
silently to a closed or approved historical assessment.

The path uses the existing verified registry client and only NCT-scoped official
ClinicalTrials.gov CDN PDF filenames explicitly present in its document metadata.
Identity mismatch, duplicate filenames, conflicting role flags, unsupported path
shapes and missing document lists are explicit acquisition unknowns. Redirects,
failed requests, invalid/non-PDF or encrypted/empty PDFs are not adopted. There is
no general crawler, web search, new MCP tool or scientific-answer rule.

Captured documents use existing protocol/SAP inventory roles and registry origin.
Combined protocol/SAP files use the protocol role with both roles retained in
metadata. A readable discovery/provenance Source records normalized registry
record hash, capture timestamp, exact source URL, document date and upload date
as distinct metadata, each PDF's byte hash/length and unresolved acquisition
outcomes. Versioned logical paths create new source identities on each new
capture. Original inputs are untouched. Both existing batch verifiers recognize
the unchanged Source schema. Existing archived bundles remain compatible.

The existing `list_sources`, `search_sources`, `read_pages`, `render_page` and
Evidence selectors expose the new Sources. Fetching establishes availability,
not reading or understanding. Source text remains untrusted data. Domain context
now attaches primary registry retrieval metadata only to registry-record Sources,
so a newly acquired protocol/SAP does not inherit an archived record's timestamp.
Document role/date labels do not prove plan finalization, pre-unblinding access,
Trial/content applicability or actual conduct. D5 guidance preserves those
separate judgments and treats missing capture as different from unavailable
publication.

30 focused tests passed, including legacy-bundle compatibility, guidance delivery
and both batch-verifier recognition. Full source/test type checking, touched lint
and diff checks passed.

Two unrelated registry fixtures cover combined and separate document layouts;
additional cases cover missing, ambiguous, mismatched, failed/non-PDF fetches,
archive preservation, new version identities, source search/reading, idempotency
and both batch verifiers. Existing intake/replay tests remain offline by default.
No model judgments, gold labels or trial-specific decision logic entered tests.

A small public end-to-end check of NCT03036124 retrieved the official 103-page
protocol and 52-page SAP as **current public captures**. `public-capture.json`
retains metadata/URLs/dates/hashes; `public-example.json` retains Source identities,
page counts and limited reading checks. Protocol page 1 had extractable text;
SAP page 1 had none, page 2 did, and original page rendering succeeded. This
checks delivery/provenance, not semantic comprehension or D5 accuracy. Complete
raw Source bytes and the isolated workspace remain under task-workspace
`diagnostics/registry-document-acquisition-20261004/public-example`.

Limits: no publisher DOI/URL companion-protocol acquisition was added. Existing
source reading/search can expose explicit report citations, but remote companion
retrieval and linkage remain unverified. Empty official large-document metadata
cannot rule out a separately published protocol/SAP. New current evidence changes
the corpus; it is not an exact historical replay or matched benchmark comparison.
No paid model call, benchmark run, automatic NI/PY, merge or full CI wait occurred.
No accuracy gain is claimed.

The isolated current public capture and source-tool receipts were frozen after
inspection in `diagnostics/registry-document-acquisition-20261004/capture-freeze.json`.
