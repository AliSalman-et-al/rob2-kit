# CHAARTED release evaluator

`rob2_kit.evaluation` is an independent consumer of retained run metadata and
finalized artifacts. It does not import proposal compatibility or presentation
logic from the product. The v1 objective manifest fixes only source facts and
terminal expectations: PFS and overall survival are assessed; adverse events is
preapproval `needs_input`. It deliberately does not prescribe RoB 2 labels.

Private inputs and runs belong under `eval/reference/` and `eval/runs/`, which
are ignored. Retain only a `RetainedEvidenceManifest`: hashes, identities,
timings, counts, review/final references, verifier output, and configuration
hashes. Sources, extracted text, credentials, prompts, and paths are rejected.

Run the gate in three fresh host processes. Each requires a zero-source
attestation, unique workspace/project/server/MCP identities, identical source
hashes, and a single attempt. A rerun is permitted only after a documented
external interruption before product or model behavior. For PFS, stop before
Proposal confirmation and use `IsolatedRun.verify_restart` to require exact
workspace/MCP/source-hash rehydration before continuing.

The runner is intentionally host-agnostic. Qualification #247 must invoke it
only when the exact candidate wheel, private CHAARTED inputs, and supported host
are available; absence of those is an external qualification blocker, not an
implementation gap in this evaluator.

For each completed isolated run, the #247 launcher invokes:

```powershell
uv run python -m rob2_kit.evaluation <finalized-artifact-directory> --outcome pfs
uv run python -m rob2_kit.evaluation <finalized-artifact-directory> --outcome overall_survival
uv run python -m rob2_kit.evaluation <finalized-artifact-directory> --outcome adverse_events
```

These commands verify only retained artifacts; they do not launch Haiku or read
private inputs. The launcher records the resulting JSON in the privacy-safe
manifest after the host process has stopped.

Use this researcher prompt for all three runs, substituting only `{outcome}`:

```text
/rob2-workflow Assess the CHAARTED trial for RoB 2 for the outcome "{outcome}". The authorized source root is "." with alias "chaarted" and Trial ID "CHAARTED". Use this exact outcome target. Continue until Verified rob2-kit status requires researcher review or the Batch is finalized.
```
