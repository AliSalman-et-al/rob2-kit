# Separate stable Search packing from exact page accounting

Evidence Search page boundaries use a deterministic worst-case envelope shape with explicit bounds for mutable metadata, while each returned page reports its exact current response size and conservative cumulative and projected traversal-cost bounds. This replaces whole-traversal exact self-accounting because coupling packing to live `ledger_cursor` and coverage progress made valid continuations unusable and caused fixed-point materialization to fail; the Search policy, operation contract, and continuation identity change together without compatibility aliases.

## Consequences

Packing remains stable for one search identity regardless of later Run progress, and a final envelope that exceeds its validated reservation is an internal invariant failure rather than a reason to repack. Only the returned page needs one constrained exact self-measurement calculation; cross-page navigation costs are deliberately upper bounds.
