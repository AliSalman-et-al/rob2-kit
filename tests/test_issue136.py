"""Regression for GitHub #136: get_work_context returned empty sources[] for
the pre-confirmation submit_source_role_review work item.

Both the pre-confirmation ("source-roles") and post-confirmation ("sources")
SUBMIT_SOURCE_ROLE_REVIEW work items produce a WorkToken with trial_id=None,
so get_work_context's is_global_source_work branch handles both. That branch
unconditionally filtered by _active_trial_ids, which is correct post-
confirmation but always empty pre-confirmation (#119: no Trial is confirmed
yet) -- so context.sources was unconditionally empty for the very work item
whose job is listing sources to review.
"""

from __future__ import annotations

from pathlib import Path

from rob2_kit.application.contracts import (
    ContinueRunRequest,
    GetWorkContextRequest,
    PrepareRunRequest,
    RunOperation,
)
from rob2_kit.application.lifecycle import RunState
from rob2_kit.application.run_engine import RunEngine
from tests.test_run_proposal import StubParser


def test_pre_confirmation_source_role_review_lists_every_issued_source(
    tmp_path: Path,
) -> None:
    """The tool's own docstring says to review exactly the sources it lists."""

    for name in ("trial-a", "trial-b"):
        trial_dir = tmp_path / "input" / name
        trial_dir.mkdir(parents=True)
        (trial_dir / "report.pdf").write_bytes(b"report text mentions randomization")

    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is not None

    review_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert review_work is not None
    assert review_work.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW

    projection = engine._projection(engine._bound_ledger(prepared.run_id), prepared.run_id)
    assert projection.run_state is RunState.AWAITING_CONFIRMATION

    context = engine.get_work_context(
        GetWorkContextRequest(run_id=prepared.run_id, work_token=review_work.work_token)
    ).context
    assert context is not None

    issued_source_ids = {
        candidate.source_id for candidate in prepared.proposal.source_role_candidates
    }
    assert issued_source_ids, "fixture must actually issue Source-role candidates"
    context_source_ids = {source.source_id for source in context.sources}
    assert context_source_ids == issued_source_ids
