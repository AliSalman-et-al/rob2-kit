# Recent full-workflow tool friction audit

Scope: original completed Attal, Castoldi and Ashar full-assessment event streams.
No judgments were rerun or changed. `trace-replay.json` binds their byte hashes,
completed call counts, errors and bounded measurements. These streams are assessment
continuations, not every preceding proposal/supervision event.

## Supported simplification

Attal fetched `references/selection.md` at event lines 88 and 94; Castoldi at
86 and 92. Both second responses delivered the exact same document hash and
complete body as the first. They occurred amid D5 reasoning/recovery, with no
instruction change. Re-reading may be legitimate when text is no longer available;
a caller should not have to receive it again merely to check for changes.

`read_guidance` now accepts optional `known_content_sha256`. When the complete
text remains in context and its hash matches current packaged bytes, it returns
`content_unchanged=true`, the document, hash and links, preserving the workflow
head. An absent or mismatched hash returns the full exact document. Default reads
and guidance resources retain full content; no session cache, hidden suppression,
mandatory workflow or changed official guidance is introduced. The public typed
receipt validates either full content or an unchanged confirmation. The tool and
skill explain when to omit the hash for recovery.

The operation also uses the existing status-head reader for the three continuation
fields it actually needs, rather than building discarded working/evidence/status
projections. This is an implementation simplification; no timing saving is claimed.

Offline replay validates the conditional data against the current public type and
preserves each recorded head, document identity and links. Measured compact UTF-8
JSON of `structured_content`: Attal 16,015→716 bytes; Castoldi 15,980→681 bytes,
30,598 bytes combined. These are counterfactual optional-call replay measurements,
not observed runtime delivery/token savings. They assume the caller still has the
previous complete text; an actual reread must request full recovery. Ashar has no
repeat guidance document in this assessment stream, so no reduction is assigned.

## Friction distinguished from scientific work

- Domain context delivery already uses page-zero scientific headers and continuation
  deltas. The recorded continuation pages do not repeatedly ship the full Result or
  official guidance. No second fix or increased default page size is justified.
- Castoldi refreshed D3 after changing its interpretation; Ashar refreshed D5 after
  admission changed the source inventory. Those snapshots legitimately differ and
  preserve dependencies and source-bound state. Repeated evidence/comparison pages
  can support scientific rereading; identical bytes alone do not establish waste.
- Attal's identical status calls at lines 6/12 and Ashar's at 6/10 deliver unchanged
  status, but later calls recover cursor/checkpoint conditions. No scientific/status
  fields were removed and no request-suppression state was added.
- Ashar's full `SKILL.md` read (line 93) delivered 39,814 bytes under JSON string
  encoding. The stream shows renewed orientation, not an explicit schema error
  preceding it. It does not support claiming a schema-recovery token saving.
- Castoldi's two definitive-answer basis repairs and Ashar's D4 basis repair are
  real interruptions. Existing domain instructions already explain the exact
  definitive-answer relationship rule; the recorded repairs supply targeted paths
  and retain the answers. There is no missing-schema evidence to justify another
  guidance layer or a changed evidence/answer gate.
- Castoldi's stale-context rejection follows a review/correction and protects exact
  canonical lineage. Its recovery supplies the native context operation. Do not
  suppress the refresh or auto-rewrite the scientific submission.
- Ashar's invalid companion request used a locator not explicitly in its cited
  reference; the next corrected request succeeded. Exact citation/link requirements
  remain. Its successful capture duplicated original protocol bytes: already
  addressed by `2deeb0e` current-Trial hash hints, without merging Source identities,
  reading credit or provenance. No additional deduplication was added.

## Validation and limits

Six guidance tests pass, including native full/conditional/full recovery equivalence,
wrong-hash recovery, genuinely changed instruction delivery, resource equality,
transitive exact packaged guidance and no canonical state mutation. Ruff lint/format
and focused `ty` pass. The replay validates the two historical conditional payloads;
original event files remain untouched. Scientific pack content, question dependencies,
Evidence/source identities and canonical scientific records are unchanged.

This is a bounded ergonomics improvement. No paid case, accuracy claim, token-cost
claim, full benchmark or merge. Whether an agent uses the conditional option
appropriately remains untested in paid workflows.
