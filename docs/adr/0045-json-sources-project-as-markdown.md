# Project JSON Sources as structured Markdown

Date: 2026-10-12

Status: Accepted

## Context

JSON Sources, chiefly the ClinicalTrials.gov record captured for each Trial,
were projected as sorted leaf paths, one per line
(`resultsSection.participantFlowModule.periods[0].milestones[1].achievements[0].numSubjects: "651"`).
Sorting put MeSH ancestor terms before the protocol, and a results table became
hundreds of indexed lines. The ARASENS record took 8,222 lines and 732,000
characters. Per-arm flow and outcome counts, which Domains 2, 3 and 5 depend
on, could not be read as a table.

## Decision

`application/json_markdown.py` projects every JSON Source as Markdown:
objects become headings, scalars `- key: value` lines, and object lists
numbered entries. Every value is copied literally, and JSON `null`, `true` and
`false` are kept as written.

A ClinicalTrials.gov API v2 study record also gets:

- readable field labels;
- protocol modules first, then results, documents and derived terms;
- milestone-by-arm and category-by-arm tables for participant flow, baseline,
  outcome measures and adverse events.

ARASENS now projects to 3,615 lines and 186,000 characters, with no value lost.

The Domain context's registry navigation (registration dates, registered and
posted outcomes, section windows) reads these headings and field lines.
`registry_field_paths` becomes `registry_sections`, which lists module
headings. The page projection recipe is `rob2-kit.page-projection.v5`.

## Consequences

The captured bytes and their hashes are unchanged; only the derived text
differs. Finalized bundles verify as before because verification does not
re-project Sources. A workspace prepared under v4 is refused, as for any
projection change, and must be started fresh. The renderer and the navigation
share heading constants and must change together.
