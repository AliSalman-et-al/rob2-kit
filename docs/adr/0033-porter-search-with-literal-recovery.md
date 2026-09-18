# Use Porter search with a literal wording mode

Status: accepted design; implementation pending.

Use one Porter-based FTS configuration for broader word-form recovery and an
explicit literal mode for wording-sensitive searches. Accept changed phrase,
prefix, and ranking behavior only with visible semantics, exact source-span
recovery, and qualification that tests misleading matches as well as recovered
Evidence.

Source-scoped spelling suggestions remain optional retrieval advice and never
execute automatically. Search changes do not make source text or scientific
judgments authoritative in a different way.
