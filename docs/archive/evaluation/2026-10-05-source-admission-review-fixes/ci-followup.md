# CI integration follow-up

Inspection of failed run 37276933760 found three failures across the test matrix (1584 passed, 8 skipped per reported run): public tool catalog/annotation assertions, schema-outcome expectations and the observation importer allowlist. The type matrix also rejected a test-only mutation callback returning a tuple instead of None. These integration omissions are corrected.

The expanded catalog check then detected missing descriptions on three companion inputs and a measured schema surface of 653,132 bytes. Input descriptions are supplied; the explicit ceiling increases from 635,000 to 660,000 bytes for the two native companion operations and typed status recovery. Closed schemas and non-destructive annotations remain checked; the companion operations explicitly remain non-idempotent.

Affected contract and observation tests: 28 passed, 1 skipped. Changed-file typing, lint and diff checks passed. A freshly rebuilt installed wheel repeated the public stdio MCP proof successfully; metadata is in ci-followup-installed-wheel.json. The cumulative network fixture log has two requests across the two preserved proofs, one per proof. Original proof files and their freeze manifest are unchanged. Zero model and benchmark calls. Independent review and new CI remain pending.
