# Issue #473 checkpoint handoff comparison

The public MCP lifecycle test compared a Result-bound checkpoint with stale
pre-Proposal notes. Each case used the same synthetic Trial, one-page main
report, exact Overall Survival Result, Proposal Review, and first D1 judgment.
The host made every tool call explicitly. The test counted the approval
elicitation as one call and used no helper that reads Sources automatically.

| Workflow | Checkpoint adopted | Public calls | Repairs | Main-report reads | Source text repeated after approval |
| --- | --- | ---: | ---: | ---: | ---: |
| Leave pre-Proposal notes stale | No | 17 | 1 | 2 total | 348 bytes |
| Reassess and save notes against the Result | Yes | 18 | 0 | 1 total | 0 bytes |

Both workflows delivered the same 348 source-text bytes before Proposal Review.
Without re-saving, the first Domain save returned
`post_approval_main_report_reading_required`; the host fetched the issued window
and retried. With reassessed notes, `get_domain_context` returned no reading
recovery, and the first Domain save succeeded. The handoff used one extra public
call to save the updated checkpoint.

The decisive D1 premise was whether the allocation sequence was unpredictable.
The fixture says participants were randomly assigned but gives no sequence
generation method. The checkpoint retained that premise as unresolved. This is
a direct source-text check in a synthetic fixture, not an expert adjudication or
a scientific-accuracy result.

Reproduce the comparison with:

```powershell
uv run pytest -n 0 tests/test_working_checkpoint.py::test_result_bound_checkpoint_handoff_avoids_postapproval_main_report_read -q
```
