Pre-inference safety check

Prior c28b9a2 CI had 44 failures in the inspected Ubuntu Python 3.12 job. Relevant current fixes: wheel filename updated to v0.11; test helper typing and union narrowing repaired; formatted schema budget fixture; remaining skill input aliases removed. Current focused proposal/release/contract tests: 24 passed; installed skill tests: 12 passed. Historical original Code Guitton bundle still verifies through application and standalone verifier (see selection-historical-verification.json).

The working-checkpoint public fixture used the obsolete pre-v0.11 request shape. It now constructs selections through the test-only fixture adapter. Result-bound handoff still authorizes assessment without repeating a read; unbound notes require actual assessment reading. Reading recovery reports phase-local delivery gaps separately from that authorization. No production provenance gate was weakened.

Known broad CI remains failing: historical revision/output fixtures and other domain tests have not all been reconciled. Current full type scan leaves the pre-existing replay_domain_probe_delivery import in tests/test_domain_probe_controls.py unresolved; source typing passes. No claim of clean full CI or improved judgment accuracy.
