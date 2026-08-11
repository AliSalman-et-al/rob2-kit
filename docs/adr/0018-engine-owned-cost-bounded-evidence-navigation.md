# Use engine-owned cost-bounded Evidence navigation

Evidence navigation uses lightweight Search projections, deterministic provider-neutral response-cost estimates, opaque continuation, and separate versioned Search and read policies rather than caller-selected budgets or irreversible truncation. Search pages and bounded multi-candidate reads expose their applied limits and continuations, while authoritative text remains behind Evidence read views; this preserves reproducible provenance and context safety while reducing avoidable agent round trips.

## Consequences

Search and read contracts, cursors, page handles, review submissions, and affected operation versions change together without compatibility aliases. Policy limits are calibrated through checked-in scale fixtures and, at an owner's discretion, private CHAARTED replay. Efficiency is measured across Search, reading, continuation, and durable review rather than by Search-call count alone.
