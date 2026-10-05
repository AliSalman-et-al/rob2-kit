# Source navigation at document entrypoints

This is a metadata/navigation improvement, not a demonstrated scientific or accuracy gain. No paid calls, new scientific case, clinical answer changes, ranking retuning, or full benchmark occurred. The earlier frozen assessment and [scientific qualification](../2026-10-05-monaleesa-audit-qualification/README.md) remain unchanged.

## Demonstrated affordance gap and route

Previously, companion admission returned Source IDs, admitted-companion status offered a page-1 read, and read responses offered page/window continuations. None supplied a bound route to the existing outline. An agent needed to discover and construct a separate source-scoped list_sources request.

Admission now returns an optional executable `navigation_action` for its admitted PDF. Status exposes the same route after admission, including after the Source has been read. Source listings provide each Source's outline action. Read responses provide one action per actually returned Source; these links participate in the existing 24,000-byte fit calculation rather than being appended after truncation. Staged documents have no active Source navigation route. Existing workflow next actions and reading requirements are unchanged.

Following an action uses the existing list_sources tool and bounded cursor. Each outline entry now provides a read_pages action: exact line windows for literal entries, and a physical-page request for a PDF bookmark. Navigation is optional; it does not select Evidence, mark pages read, or impose a checklist. There is no new tool or framework.

## Authored PDF metadata without invented coordinates

The same outline presents authored local PDF bookmarks first in their authored order, followed by the complete existing literal index. This general ordering applies to every captured PDF, not a trial-specific selection. Each bookmark retains its original zero-based outline index, authored nesting level, one-based physical page destination, bounded label and SHA-256 of the full label. Labels longer than 512 characters are explicitly marked truncated. Nonlocal/unmapped destinations and empty labels are excluded and counted; no physical destination is invented.

A distinct `pdf_bookmark` schema declares labels to be PDF metadata, not destination-page quotes or Evidence. Bookmark entries contain no fabricated line/character coordinates, date classification, version precedence or inferred scientific role. The outline carries the verified captured-PDF SHA-256 and persisted text-projection identity. Captured bytes and projections undergo the existing Source-integrity check; bookmark extraction also verifies the bytes it parses against the canonical Source hash. Corrupt bytes fail closed.

The maximum transport page remains 12 entries. The existing cursor traverses all authored local bookmarks and literal entries. Navigation recipe v0.5 prevents old offsets from being interpreted in the new combined index; an old v0.4 cursor returns the explicit stale-cursor condition and requires a fresh outline. PDFs with no bookmarks and non-PDF Sources retain the literal index. Historical scientific/reading/search receipts and canonical Source inventories were not rewritten.

## Offline availability and path measurement

The metadata-only audit used a separate copy of the frozen in-place diagnostic workspace. It followed the newly exposed status action and traversed both complete outlines through the native API. It did not read either destination page or run a model. Canonical state and reading coverage were compared unchanged. Every prior literal entry's content, coordinates and metadata remained present; public-model default-null fields are not treated as new content.

| Captured Source | Local authored bookmarks | Unchanged literal entries | Combined entries | Native calls to traverse the full index | First structured response bytes |
|---|---:|---:|---:|---:|---:|
| Protocol, 185 physical pages | 0 | 612 | 612 | 51 | 11,878 |
| SAP, 106 physical pages | 144 | 483 | 627 | 53 | 9,665 |

The first 12 SAP entries include authored labels pointing to physical pages 30 and 43 with executable page-read actions. The previous literal-only index first reached those pages at offsets 108 and 281: sequential traversal at the default limit required 10 and 24 outline calls respectively, followed by a read call. The new route exposes either destination after one outline call, followed by one read call. These are sequential cursor-path measurements, not claims that an agent previously had no other route, that it will follow the new action, or that metadata supplies the destination's scientific assertions.

Each encountered admission/status/Source-list/read response now offers a bound outline action where previously it offered none. The call path from that encountered response to the first outline remains one call; the improvement is a discoverable executable route. [Availability measurements](availability.json) preserve the exact initial entries, page destinations, actions, Source hashes and comparison scope. No recovered passage is credited to the frozen agent's warrant.

## Focused checks and integration

The independent review of [search grouping](../2026-10-05-search-window-grouping/README.md) requested cheap boundary follow-ups. Four focused controls now cover exactly 80% versus slightly lower overlap and 2,048 versus 2,049 UTF-8 bytes for the union cap. An explicit cross-recipe search cursor test rejects an old offset while its v0.9 receipt remains verifiable. These tests do not change search ranking behavior or rerun the private search-conservation checker.

Navigation controls exercise nested authored levels, long labels/full-label hashes, unmapped destinations, exact physical-page reading, complete cursor recovery, explicit old-recipe cursor rejection, and corrupt-byte rejection. Outline delivery leaves reading status unchanged; executing a page-read action changes coverage only for the delivered page. No-bookmark legacy PDFs and ordinary literal navigation retain their existing controls.

Local checks passed: 11 navigation/deferred-page checks; seven focused boundary/navigation/status checks; 19 bounded read/no-hit/navigation checks; three refined admission/history/bookmark checks; the public contract size check; and 95 release/launcher/preflight tests with two skips. These groups overlap and are not summed as a test or accuracy denominator. Changed-file lint/type checks and CI-equivalent formatting checks pass.

Published typed schemas grow from 653,132 to 667,054 bytes (about 14 KB) for bookmark provenance and executable routes. The explicit narrow budget is now 675,000 bytes. Read response limits remain unchanged. This is a disclosed metadata cost, not a usage-reduction claim.

CI for the preceding checkpoint exposed a missed generated artifact: the checked public contract still described the v0.3 navigation schema after the v0.4 update. The final public contract is regenerated. Source release verification and installed-wheel release verification both pass. The wheel SHA-256 is `805cda436f27e1a1c65bfa025eb8407d6f2e647b93863fd8ce1f2dda84741989`; all modified packaged Python members match source bytes exactly. Installed verification used a fresh installed environment with child PYTHONPATH unset, preventing source-import fallback.

Failed checks remain preserved privately: the first metadata comparison incorrectly treated public default-null fields as changed literal content; admission assertions were briefly placed in the staged acquisition test helper and were moved to admission; a preflight command used a nonexistent test path and was rerun with the actual release manifest tests; the first offline build cache lacked Hatchling and an isolated writable build cache completed the build. No shared dependency environment, case input or earlier diagnostic was overwritten.

The prior public review seal and all 71 frozen raw diagnostic output hashes were checked unchanged. This report has its own seal. CI results after the new push remain a separate integration observation; no green CI or scientific-gain claim follows from these local checks.
