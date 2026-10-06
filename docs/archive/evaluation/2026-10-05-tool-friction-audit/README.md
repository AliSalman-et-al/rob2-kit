# Recent full-workflow tool friction audit

Scope: original completed Attal, Castoldi and Ashar full-assessment event streams.
No judgments were rerun or changed. `trace-replay.json` binds their byte hashes,
completed call counts, errors and bounded measurements. These streams are assessment
continuations, not every preceding proposal/supervision event.

## Negative result: conditional guidance API removed

Attal fetched `references/selection.md` at event lines 88 and 94; Castoldi at
86 and 92. Both second responses delivered the same verified 15,076-byte document.
However, neither request nor adjacent visible message establishes an intention to
check for changed instructions. Attal read D5 context between the calls and described
finishing reporting-selection assessment; Castoldi searched sources twice between
the calls. Legitimate instruction recovery or scientific rereading remains possible.

Commit `4294802` added an optional prior-hash API on the assumption that these
rereads could be change checks. That assumption was unsupported. The API, conditional
receipt schema, added conditional tests and usage instructions have been removed in
an ordinary follow-up commit. Exact full-read behavior, resources and the required-content schema are restored;
git history and evidence remain. The existing status-head reader is retained for
the three metadata fields this operation needs, avoiding discarded derivative status
projections. Those fields are checked for exact equality against the full reader.

`visible-request-evidence.json` records the exact requests, result metadata, intervening
calls and nearest visible agent messages, bound to full original trace hashes. It
contains no private reasoning text. Original trace bytes were not changed.

The historical `trace-replay.json` remains an audit artifact, not current API behavior.
Its 30,598-byte counterfactual reduction assumed the complete instructions remained
available and a change check was wanted. Identical delivered bytes established neither
assumption, so this measurement was insufficient to justify added API complexity.
No actual runtime, token-cost or scientific improvement was demonstrated. This is
a rejected speculative optimization, not a production safety incident. Independent
review reproduced the byte arithmetic and recovery behavior, but confirmed that a
retained hash without its text intentionally omitted instructions and that the proposed
schema did not itself express the content/confirmation exclusivity.

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

The restored guidance tests check transitive exact packaged content, full resource
recovery and no canonical state mutation. Focused schema inspection verifies the native
input again accepts only `document`, the receipt requires full `content`, and historical
full responses still validate. Five focused guidance/tool-schema checks passed (17.93 seconds); all 21 historical
full guidance receipts validate under the restored schema. Application guidance,
public contracts and caller skill instructions match the pre-API bytes exactly.
Ruff lint/format and focused type checks pass.
No scientific pack, question dependencies, Evidence/source identities, canonical
scientific records or acquisition improvements were changed.

No paid case, answer change, full benchmark or merge. This bounded audit produced a
negative result rather than a supported new tool feature.
