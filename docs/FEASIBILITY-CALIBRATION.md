# V1 feasibility calibration

This note records the measured v1 defaults for parsing, lexical retrieval,
context assembly, and relevance-gated visual inspection. The measurements use
the private local corpus under `eval/reference/`; no PDF text, source filename,
or provisional judgment label is exported by the measurement script.

These are versioned policy defaults, not correctness claims or permanent hard
limits. A project may change them later. Pagination and successive context
views preserve complete coverage when one call reaches a transport target.

## Corpus and method

The corpus contains 37 PDFs (10 primary reports and 27 supporting sources),
2,680 pages, and 83,256,724 bytes. It covers 10 prostate-cancer trials and
includes ordinary appendices, optional-source noise, and compound
protocol/SAP PDFs as long as 354 pages.

The reproducible OCR-off pass used LiteParse 2.10.0 with:

```python
LiteParse(
    ocr_enabled=False,
    include_complexity=True,
    output_format="markdown",
    quiet=True,
)
```

It indexed 20,894 paragraph-like search units in an in-memory SQLite FTS5
table using `porter unicode61`. The pass took 26-27 seconds on the calibration
machine. Run it with:

```text
uv run python scripts/measure_feasibility_corpus.py
```

The script writes a private, Git-ignored temporary JSON report and does not
inspect the judgment CSVs.

## Observations

### Parsing

- OCR-off page text had a median of 2,372 characters and a 95th percentile of
  5,437 characters. Primary-report pages were denser: median 5,964 and 95th
  percentile 10,139 characters.
- LiteParse marked 41 of 119 primary-report pages as `needs_ocr`, but all 41
  already contained 714-12,240 extracted characters. Thirty carried
  `vector-text`; eleven carried `sparse-text`.
- Targeted OCR of those 41 pages took 177 seconds in aggregate. It increased
  extracted characters by only 0-4.6% per report, and every page remained
  flagged. Therefore `needs_ocr`, `vector-text`, and `sparse-text` are routing
  observations, not standalone OCR or failure gates.
- Supporting sources produced 1,659 `needs_ocr` pages. The reasons included
  blank/scanned pages as well as sparse pages in long compound documents.
  Blindly OCRing all of them would be expensive and would ignore relevance.
- No corpus page was marked `is_garbled`. Garbling behavior therefore needs a
  small synthetic fixture; this corpus cannot justify a numeric garble score.
- Layout signals were intentionally broad: 971 pages were complex, 651 pages
  were table-like, and 784 pages had figure signals. Rendering from complexity
  alone would inspect a large, mostly irrelevant fraction of the corpus.

### Search and context

- Search-unit length was 88 characters at the median, 1,182 at the 95th
  percentile, 2,249 at the 99th percentile, and 16,187 at the maximum.
- Trial-scoped semantic probes ranged from one hit to 404 hits. Broad families
  such as randomization and prespecification were dominated by long supporting
  documents; focused phrases such as participant-flow concepts returned at
  most six units per trial in this corpus.
- The measurements support small, repeatable payloads and cursor traversal.
  They do not support a top-k evidence cutoff.

### Visuals

Representative baseline tables, a participant-flow diagram, and a dense
two-column page were rendered at 144, 180, and 216 DPI.

| DPI | Typical full-page dimensions | Observed PNG size range |
| --- | --- | --- |
| 144 | 1,134-1,170 x 1,512-1,566 | 0.37-1.21 MB |
| 180 | 1,418-1,462 x 1,890-1,957 | 0.50-1.63 MB |
| 216 | 1,701-1,755 x 2,268-2,349 | 0.64-2.04 MB |

The baseline table and participant-flow denominators were legible at 144 DPI.
Higher DPI increased payload size without adding useful information in those
examples. Crops remain preferable when they can retain the title, labels,
legend, and relevant footnotes.

## Adopted v1 defaults

### Parser quality and OCR

1. Parse every PDF completely with OCR disabled and complexity enabled.
2. Preserve all LiteParse reason codes. Route only recognized codes through
   the versioned parser-quality policy; unknown codes create a diagnostic
   observation rather than a guessed state.
3. Do not trigger OCR, failure, or visual inspection from `needs_ocr`,
   `vector-text`, `sparse-text`, `multi-column`, `table-likely`, or a figure
   signal alone.
4. Automatically nominate a page for targeted OCR when LiteParse reports
   `no-text` or `scanned` and the page does not yield trustworthy canonical
   text. Also nominate a decision-relevant page when retrieval or
   parse-versus-render checks expose missing or suspect text.
5. Permit full-report OCR only when the required primary report is genuinely
   scanned throughout. Confirm that condition from the page map and visual
   checks of representative early, middle, and late substantive pages.
6. For supporting sources, OCR only nominated decision-relevant pages. Do not
   OCR every blank, sparse, scanned, or garbled supplement page.
7. Make one targeted LiteParse OCR attempt per page under one recovery-policy
   revision. If reliable text is still unavailable, use the visual gate; do
   not repeat the same OCR configuration.
8. Treat parser states as evidence about coverage, not document quality
   scores. A page is usable when its relevant content and page attribution are
   trustworthy. Material unresolved coverage determines the preparation
   consequence.

This policy deliberately has no global percentage-of-pages threshold. A
single unreadable Result locator can be material while many irrelevant blank
protocol pages are not.

### Canonical units, search projections, and FTS5

1. Keep headings, paragraphs, list items, captions, footnotes, and table rows
   as immutable Canonical evidence units. Never split a citable unit merely to
   fit model context.
2. Index with SQLite FTS5 `porter unicode61`. Compile structured terms,
   phrases, prefixes, Boolean groups, and metadata filters deterministically;
   agents never submit raw FTS syntax.
3. Create non-citable search projections for an unusually large unit. Begin
   projection at 2,400 characters, just above the observed 99th percentile,
   and split at a sentence or line boundary with one boundary sentence/line
   of overlap. Every hit resolves to the intact Canonical evidence unit.
4. Return compact search listings in pages targeting 20 hits or 8,000
   characters of snippets and metadata, whichever comes first. An oversized
   single item gets its own page. The cursor continues until every accepted
   query result has a disposition.
5. Before accepting a query into the mandatory protocol, show its unique-hit
   count and source distribution. When it matches both more than 100 units and
   more than 5% of the scoped index, ask the autonomous agent to refine it by
   phrase, discovered terminology, source/component, or metadata, or to
   record why complete traversal of the broad query is appropriate. This is a
   refinement checkpoint, not a hit cap.
6. Preserve source-role ordering for usability, but search all usable acquired
   required, expected, and supplied optional sources.

### Context views

1. Keep the Trial orientation pack near a 12,000-character text target.
2. Keep an SQ context view near a 24,000-character text target, including
   guidance, rules, the evidence matrix, and pivotal passages. Use successive
   views rather than dropping material.
3. Expand at most six ordinary Canonical evidence units in one view and target
   16,000 characters for expanded passages and bounded neighbors. An
   oversized unit gets a dedicated view.
4. Count structured manifests and exact identifiers outside these prose
   targets when necessary for integrity. Hosts may translate the character
   targets into their own token accounting, but the host-neutral manifest is
   authoritative.
5. A complete Evidence consideration manifest, not one model call, proves
   that every accepted item was considered.

The item counts are per-call transport defaults. There is no total evidence or
context-view cap.

### Visual inspection

1. Render the smallest useful contextual crop at 144 DPI by default. Include
   the visual title, required labels, legend, and relevant footnotes.
2. Escalate to 180 DPI when small type or a decision-critical value is not
   clear. Permit 216 DPI as the final automatic resolution step. Continued
   ambiguity becomes a Review finding and requires opening the original page;
   repeated higher-resolution renders are not assumed to solve it.
3. Escalate from crop to full page when flow, cross-panel relationships,
   legends, or footnotes cross the crop boundary. Participant-flow diagrams
   commonly need most of the page.
4. Present one visual candidate per model view by default, or up to three
   tightly related crops from the same source and signaling question when
   their relationship matters. Continue through the candidate queue with
   stable cursors.
5. Never render from table/figure/complexity signals alone. Require a
   ResultSpec locator, Guidance mapping, retrieved reference/caption/row,
   numerical conflict, parse/render discrepancy, or an attributable agent
   nomination explaining possible decision impact.
6. Give the required primary report scheduling priority. Apply the same
   relevance test to supplements and compound documents; do not screenshot
   all supplement tables, figures, or garbled pages.

There is no fixed total screenshot count. The bounded unit is one nominated
candidate and its crop-to-page/resolution escalation. If host usage, time, or
an advanced project ceiling interrupts traversal, unresolved candidates
remain explicit and resumable.

## Findings and preparation consequences

- A visually readable but text-unanchorable claim is `visual_only`,
  `review_required`, and shown beside its crop at sign-off.
- Failed OCR or an ambiguous crop/full-page inspection marks the exact
  page/region `coverage_limited`; it never becomes `No information`.
- If the required primary report is broadly unreadable, page attribution is
  unstable, or the Result cannot be verified after bounded recovery, the Trial
  is `trial_failed`.
- If the primary report and Result are usable but unresolved material coverage
  prevents a valid answer to an active signaling question, preparation is
  `preparation_incomplete`.
- An expected or optional source limitation may yield
  `draft_ready_with_findings` only when every active question still has a
  defensible answer or No-information basis under the Review policy.
- An interrupted or policy-limited search is `search_limited`. It remains
  cancellable and resumable, cannot establish `No information`, and blocks
  sign-off whenever the missing coverage could materially affect the answer.

## Limits of this calibration

This is a feasibility corpus, not an adjudicated benchmark. It is concentrated
in one clinical area, includes no LiteParse-garbled page, and does not measure
RoB 2 answer accuracy or retrieval recall against gold-standard evidence.
The provisional CSV labels were not used. The defaults should be remeasured
when LiteParse, canonicalization, host image handling, or the corpus mix
changes; the same safety consequences remain invariant.
