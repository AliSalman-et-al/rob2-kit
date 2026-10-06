# Offline acquisition request-construction diagnosis

The schema and literal-reference guards were correct. No failure in this run demonstrates an incorrectly rejected supported reference.

| Attempt | Actual request construction | Observed result |
|---|---|---|
| 1 | `expected_revision` plus Trial/Source/page/citation/locator fields all at the top level; `reference` missing. Citation also appended `(Study Protocol), lines 59-67`. | Native schema validation reported missing `reference` and unexpected top-level fields. Acquisition was not reached. |
| 2 | Fields correctly nested inside `reference`; the same annotated citation retained. | `invalid_request`: citation must occur in the supplied Source page text. The annotation was not a literal page substring. |
| 3 | Nested fields; citation prefixed `Exact Source quote, page 1, lines 59-67:` and joined filename/label/date field lines with inserted semicolons and a final period. | Same citation guard rejection. The assembled string was not a contiguous page substring. |
| 4 | Nested fields; citation was only the exact quoted protocol filename field line. | Successful protocol capture through the existing verified NCT-scoped CDN filename rule. |
| 5 | Nested fields; citation was only the exact quoted SAP filename field line, at the new current revision. | Successful SAP capture through the same existing rule. |

The five exact calls are in acquisition-attempts.json. This is agent request-construction friction: the first call flattened a correctly declared object, and the next two treated `citation` as an annotated bibliographic citation rather than literal source text. The schema already declares `reference` as an object and the D5 reference already shows `reference={...}`. The rejection message is accurate, although it does not explain how to separate quote text from coordinate/rationale annotations.

The general guidance clarification makes the existing contract explicit in SKILL.md and references/selection.md: place all reference fields inside `reference`, with `expected_revision` beside it; use a contiguous literal quote without read_pages numbering or added annotations; put the page and linkage explanation in their own fields. It also explains that a verified registry filename field line can satisfy the supported CDN case without appending a constructed URL to the quote. This uses the observed failure pattern without naming this case or changing scientific guidance.

No schema alias, citation normalization, fuzzy matching, automatic stripping, fetch expansion or literal-guard relaxation was added. No error wording or runtime code was changed. No paid call or retest was run, and no gain is claimed for this documentation clarification. The previously frozen installed-wheel condition and saved scientific output remain intact.
