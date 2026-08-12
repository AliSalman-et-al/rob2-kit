# Deleted source characters get a zero-width canonical span, not an omitted mapping

`_merged_block` (`search.py:335-371`) currently assumes pure concatenation: `offset = len(previous.text)` shifts the candidate's `fragment_spans`/`word_boxes` by exactly the previous text's length. Hyphen-rejoin (ADR-0013) deletes a source character (the trailing hyphen) during merge, breaking that assumption, and CONTEXT.md's Canonical evidence unit entry promises "complete fragment-to-canonical character mapping."

We considered relaxing that glossary guarantee to explicitly allow character-dropping edits as a scoped exception, which would avoid touching the span model at all. We rejected this: it weakens an existing, explicit promise for every future canonicalization edit, not just this one, and the alternative is a small, contained model change.

Decision: extend the fragment-span model to allow `canonical_start == canonical_end` — the deleted hyphen's source position gets a zero-length canonical range instead of no mapping at all. Every source character stays attributable to a canonical position (even a "this character produced nothing" one), so the glossary's "complete" guarantee holds without amendment. This does require downstream consumers of `fragment_spans` to tolerate zero-width ranges.
