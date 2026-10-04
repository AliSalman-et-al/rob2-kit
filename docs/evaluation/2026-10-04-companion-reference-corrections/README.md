# Companion reference corrections and native handoff

Corrected four independent-review findings from `d824f767b5711f6798ccd31ca4bd894772128da7`,
plus its corpus-transfer qualification. No paid inference or new public acquisition
was needed for this follow-through.

## Scientific metadata correction

The retained ACTT-1 protocol PDF has SHA-256
`99ccc83a958763aa2568591292d8489044f1e355f1d23f2d1977b1837b79f8c8`.
On page 63, References item 12 cites `NCT04257656`, a separate remdesivir trial.
Its own headers identify ACTT protocol 20-0006, version 3.0, dated 2 April 2020.
The previous generic all-text regex incorrectly called that body mention a
conflict with registry record `NCT04280705`. Registry-link association and body
identifiers are distinct evidence.

The generic replacement retains every observed identifier occurrence with a page
and surrounding snippet. Other body identifiers yield `other_identifiers_observed`,
not mismatch. Narrowly labelled front-matter registration claims are recorded
separately; one differing claim yields `document_registration_claim_differs`,
multiple claims stay qualified, and no explicit identity remains unresolved.
These are literal claims, not semantic proof that a protocol is applicable.
`applicability` remains `unverified` even with a matching claim. The front-matter
recognizer covers explicit labels in the first two pages, not all possible ways a
document might identify itself; hosts must read the surrounding document.

Neutral tests cover own ID plus another-trial citation, a genuinely differing
front-matter registration claim, umbrella/multiple registrations and no explicit
ID. [ACTT-context.json](ACTT-context.json) records the actual offline reanalysis:
one other identifier mention on page 63, no front-matter registration claim.
Old captures and their previous classification receipts were preserved unchanged.

## Actual native agent action

`request_companion_source(reference={...})` is now a discoverable typed MCP tool.
The reference contains the native `sh_` Source handle from `list_sources`, page,
exact textual citation, possible-linkage rationale, protocol/SAP role hint, URL or
DOI and optional expected registry ID. It records an immutable local request bound
to the Canonical parent Source/hash and returns structured host handoff arguments.
Both this boundary and direct CLI staging resolve actual `sh_` handles through the
existing resolver; the capture provenance retains full Canonical identities.
Wrong or genuinely stale Source versions are rejected.

The receipt states `reference_recorded=true`, `document_staged=false`,
`admitted_to_active_batch=false`, `document_read=false`. It does not acquire
anything or make it readable in the current assessment. The host action is:

```sh
rob2 stage-companion --workspace CURRENT --reference REQUEST --output NEW \
  --registry-policy require-offline-replay
```

The host chooses a fresh destination and one of these explicit policies:

- `require-offline-replay`: reject copied input with a live registry fetch or
  current-document acquisition configured. Existing local registry replay is reused.
- `retain-input-settings`: explicitly retain the copied settings and their
  potential future current-registry requests.

The returned input-transfer inventory shows pre-staging input file versions,
Sources absent from copied input, replay matches, changed inputs and registry
settings. The target manifest gets Other candidate/provenance declarations;
other input bytes are copied unchanged and checked. Concurrent input change
causes an error with the incomplete new workspace retained for inspection.
No captured-corpus-plus-one equivalence is claimed generally: previously fetched
remote Sources may remain only in the original ledger, and future registry intake
may refresh when explicitly configured. No archive-import framework was added.

After a successful host stage, the candidate is staged in NEW but unadmitted to
CURRENT. To use it, the host selects NEW for ordinary prospective intake and
review; then its Sources can be read/searched. Current assessment, historical
Source versions, Result bindings and workflow continuation stay intact. This
optional handoff introduces no scientific approval gate, automatic restart or NI.
Reference text and linkage rationale are data; they never enter executable host
arguments. A native assessor without filesystem/shell access can record the
handoff and continue the existing assessment.

## Reference identity and shared document transport

Citation matching now requires the entire normalized DOI token or exact URL,
including meaningful query/version, in both the actual parent page and caller
quotation. A truncated quotation cannot admit `10.1234/neutral` from
`10.1234/neutral-other`, or a bare PDF URL from a versioned URL. Registry filename
fallback requires a quoted exact filename, a verified registry Source and its
matching NCT-scoped official path.

Registry PDFs now use the same bounded HTTPX reader as companion PDFs:
20 MiB identity-encoded bytes, TLS, no environment proxies or persistent cookies,
validated provider-controlled public HTTPS hosts and DNS addresses. Compressed
responses are rejected before reading; private/link-local/credential/file or
unvetted destinations are rejected. Registry PDFs follow no redirects; companion
fetches keep the existing bounded validated redirect behavior. Crossref metadata
retains its separate 2 MiB limit. This fixes an unbounded/proxy-trusting registry
PDF path; no demonstrated SSRF exploit is claimed. It does not retrofit registry
JSON transport or create a general pinned-DNS/crawler stack.

## Supporting checks and limits

The final focused run passed 53 tests across companion requests/acquisition,
registry documents, guidance delivery, closed schemas and surface budget.
Two additional native/copy-integrity checks passed after the copy-verification
refinement. A broader 100-test intake/schema run passed 99; its sole failure was
the expected tool-name table, updated for the added action and separately passed.
Type checks over src/tests, focused Ruff and diff checks passed.

The actual in-process FastMCP Client lifecycle checks discovery, source-parent
citation/hash retention, idempotent request records, real native-handle CLI
staging, no overwrite, ordinary fresh MCP intake/read/search and the full Source
set delta. Its explicit offline replay fixture preserves both original SourceID/
hash pairs and adds exactly two Sources (candidate PDF and capture provenance).
That verified fixture delta does not establish corpus equivalence for other
workspaces. An active-assessment fixture retains the same state/head through
request rejection and a failed optional fetch, without forced NI or new judgments.
DOI/publisher and transport failures use neutral HTTP fixtures, not live model
or public-acquisition tests. There was no live Codex inference/tool-choice trial.

Prior DAPA-HF `NCT03036124` and ACTT-1 `NCT04280705` capture freezes of 10 and 19
files, plus the 8-file companion parent copy, remain unchanged;
[freeze-checks.json](freeze-checks.json) records those checks. PDFs/native captures
remain local. No paid model, gold, scientific answer coercion, full benchmark,
merge, CI wait, Astra or unrestricted-shell capability. No accuracy gain claimed.
