# Flat scientific Result proposals and partial-read receipts

This is an offline implementation checkpoint following the proposal-only Allsop
run at b12fe455. No model inference, full benchmark, approval, or merge occurred.
The native trace and required Code benchmark corpus are preserved. This does not
establish improved judgment accuracy or model construction success.

## Old and new public shape

Previously, an assessable card required `kind:assessable`, nested `applicability`,
`target.measurement`, tagged `target.time_point_or_window`, and tagged
`reported.form`. The observed model instead sent a canonical-shaped target,
`reported_result`, invalid `kind:quantitative`, and `relation:supports`.

The replacement input contains these flat scientific fields:

- `trial_id`, explicit `relation`, `relation_rationale`, optional `clarity`;
- `design`, `design_rationale`, `design_evidence`;
- `target_measurement`, `target_window`, optional paired `target_time_value` and
  `target_time_unit`, `comparison_groups`, `baseline_subgroup`,
  `intended_effect_measure`;
- `reported_outcome`, optional source-tied `reported_definition`,
  `analysis_population`, and either `effect_measure`/`estimate`/optional
  `precision`, or complete `group_values`;
- inspected `passage_refs` and optional typed numerical/source `evidence`.

A descriptive category profile retains explicit scientific category fields and
cannot proceed to comparative assessment without the comparator result. Missing
Results supply `trial_id`, explicit `relation:ambiguous|unavailable`, and typed
`missing_facts`. Basis types and complex numerical proofs remain explicit: they
identify evidentiary claims rather than redundant Result-record tags.

The server derives record kind, reported form, timing representation, captured
outcome/metric, assignment effect, target analysis population, canonical source
bindings and bookkeeping. It does **not** translate `supports`, infer scope
relation, infer scientific equivalence from prose, or repair invented field names.
The only existing narrow input recovery retained is the missing group-unit
sentinel, which reaches an explicit application repair and cannot be persisted.

The old internal/canonical models and validators are unchanged. The MCP boundary
converts the replacement strict input to that exact draft shape. There is no
parallel legacy model-facing Result branch, permissive alias parser, state
migration, new inference framework, or canonical artifact rewrite. Test fixture
translation lives only in test support. Complete fictional requests in the
installed skill reference are schema-tested against the new input.

## Scope review

The server still projects target/report comparison, raw Result identity,
relation/rationale, caller-declared clarity, binding paths and the explicit
`requires_source_interpretation` instruction. Target and endpoint summaries use
compact typed fields rather than reproducing canonical model schemas and their
long descriptions. Reported timing and estimand remain explicitly null because
they are not separately represented; this is not a claim of source absence.
Review metadata is derived and never supplied by the caller or stored in the
canonical Result. Existing exactness gates reject declared conflicting/unclear
facets, but a caller's falsely confident `specified` assertions still require
source interpretation; structural validation does not certify semantics.

`schema-sizes.json` compares complete compact UTF-8 tool declarations with the
frozen b12fe45 contract. `validate_proposal`: 48,153 → 33,821 bytes; `get_status`:
53,845 → 51,096 bytes. This is schema size, not token usage or accuracy.

## Separate page 11 receipt diagnosis

The four original native `read_pages` requests were replayed through live MCP in
a disposable sqlite backup of the preserved diagnostic workspace. Sources and
original databases were not changed. The final recovery begins at character 20
of page 11 line 1, then delivers complete lines 2–186. Previously cumulative
fragment status suppressed coverage for every line in that response.

Coverage now records each contiguous complete-line portion of the delivered
window independently of whether its first line was partial. The exact replay
records page 11 lines 2–186. It does not claim line 1 was complete, combine
character fragments into a fabricated line receipt, select a continuous passage
across fragments, or alter the captured primary report budget. A portable MCP
regression test reproduces the same partial-first-line/complete-suffix behavior.
See `page11-replay.json` and `replay-page11-flat.py`.

## Validation and limits

80 focused checks passed, followed by one additional unsupported-estimate check
(81 passed in total). Ruff, formatting, `ty check src`, and `git diff --check`
passed. `test-results.txt` records the 80-check run.

Focused tests cover exact old-to-new internal draft equality, actual invalid
native shapes, unsupported relation values, declared scope conflicts and related
alternatives without target rewriting, incomplete timing/design/quantities,
unsupported source estimates, documented examples, proposal save and researcher
approval, partial-read receipts, and current/historical/tampered bundle
verification. Ruff, formatting, type checking and diff checks also run.

No paid rerun is authorized at this checkpoint. The model may still make an
unsupported relation or scope claim; offline construction and gate checks do
not show that Luna will choose better science or successfully construct this
new request. A later bounded model-owned test requires separate authorization.
