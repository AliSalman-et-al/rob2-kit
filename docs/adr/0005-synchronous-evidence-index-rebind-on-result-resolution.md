---
status: superseded by ADR-0017
---

# Evidence-index rebind is synchronous inside `submit_result_resolution`, not a separate work item

Issue #113 settled that the evidence index must rebind after a Result is confirmed, so canonical units carry correct Trial/Result applicability instead of remaining permanently unresolved; it was closed as design-settled but the call was never added — `submit_result_resolution` does not invoke `_index_initial_evidence`, unlike `prepare_run`, `submit_run_proposal`, and reconciliation, which all call it synchronously already. We add the same synchronous call inside `submit_result_resolution`, rather than introducing a new engine-issued `WorkItem` for it, because every other `WorkItem` exists specifically because it requires agent judgment, and "should the index be rebuilt after a Result resolved" does not — it's a deterministic consequence of the resolution itself. The rebind is keyed on `dependency_fingerprint()` (already a general revision-safety primitive) computed over everything the indexer already consumes — the `ResultSpec` revision, Source artifact hashes, and Parse revisions — not the `ResultSpec` alone, so a Source that gets reparsed invalidates the cached index even when the confirmed Result definition itself hasn't changed.
