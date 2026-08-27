from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from fastmcp import Client
from support.rob2 import (
    _call,
    _proposal_args,
    _result,
    _review,
    _unavailable_result,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.intake import approve_review
from rob2_kit.application.status import presentation
from rob2_kit.interfaces.mcp.server import mcp


def _raw_call(workspace: Path, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async def invoke() -> dict[str, Any]:
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            result = await client.call_tool(tool, arguments, raise_on_error=False)
            return dict(result.structured_content or {})

    return asyncio.run(invoke())


def _trial_request(outcome: str = "requested outcome") -> dict[str, Any]:
    return {
        "requested_outcome": outcome,
        "expected_revision": 0,
    }


def test_prepare_batch_exact_stale_retry_and_mismatches(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    request = _trial_request()
    first = _call(workspace, "prepare_batch", request)
    assert first["outcome"] == "success"
    identity = _state(workspace)["batch"]["identity"]

    retry = _call(workspace, "prepare_batch", request)
    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True
    assert _state(workspace)["batch"]["identity"] == identity

    stale_different = _raw_call(workspace, "prepare_batch", _trial_request("different"))
    assert stale_different["outcome"] == "conflict"
    assert _state(workspace)["batch"]["identity"] == identity

    current_different = _raw_call(
        workspace,
        "prepare_batch",
        {**_trial_request("different"), "expected_revision": first["head"]["state_revision"]},
    )
    assert current_different["outcome"] == "condition"
    assert _state(workspace)["batch"]["identity"] == identity


def test_save_proposal_exact_stale_retry(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    from support.rob2 import _prepared_evidence

    evidence = _prepared_evidence(workspace)
    request = _proposal_args(workspace, [_result(evidence)])
    first = _call(workspace, "save_proposal", request)
    assert first["outcome"] == "review_required"
    retry = _call(workspace, "save_proposal", request)
    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True


def test_pending_proposal_can_be_replaced_but_approved_proposal_is_locked(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    from support.rob2 import _prepared_evidence

    evidence = _prepared_evidence(workspace)
    first_request = _proposal_args(workspace, [_result(evidence)])
    first = _call(workspace, "save_proposal", first_request)
    assert first["outcome"] == "review_required"
    first_review = _state(workspace)["review"]["identity"]
    first_proposal = _state(workspace)["proposal"]["identity"]

    revised_result = _result(evidence)
    revised_result["relation"] = "related"
    revised_result["relation_rationale"] = (
        "The source-reported candidate overlaps the requested construct but is not identical."
    )
    second = _call(workspace, "save_proposal", _proposal_args(workspace, [revised_result]))
    assert second["outcome"] == "review_required"
    state = _state(workspace)
    second_review = state["review"]["identity"]
    assert state["proposal"]["identity"] != first_proposal
    assert second_review != first_review

    stale_result = _result(evidence)
    stale_result["relation"] = "component"
    stale_result["relation_rationale"] = (
        "The source-reported candidate is one component of the requested construct."
    )
    stale_request = _proposal_args(workspace, [stale_result])
    stale_request["expected_revision"] = first["head"]["state_revision"]
    stale = _raw_call(workspace, "save_proposal", stale_request)
    assert stale["outcome"] == "conflict"

    with pytest.raises(ValueError, match="exact displayed Review"):
        approve_review(workspace, first_review)

    approved = approve_review(workspace, second_review)
    assert approved["outcome"] == "success"
    assert _state(workspace)["phase"] == "assessment"

    locked = _raw_call(workspace, "save_proposal", _proposal_args(workspace, [revised_result]))
    assert locked["outcome"] == "condition"
    assert "proposal is not the current operation" in locked["condition"]["detail"]

    with sqlite3.connect(workspace / ".rob2-kit" / "canonical.sqlite3") as connection:
        proposal_count = connection.execute(
            "SELECT COUNT(*) FROM canonical_records WHERE kind='proposal'"
        ).fetchone()[0]
        review_count = connection.execute(
            "SELECT COUNT(*) FROM canonical_records WHERE kind='review'"
        ).fetchone()[0]
    assert proposal_count == 2
    assert review_count == 2


def test_status_distinguishes_proposal_preparation_from_displayed_review(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    from support.rob2 import _prepared_evidence

    evidence = _prepared_evidence(workspace)
    preparing = presentation(_state(workspace))
    assert "being prepared or submitted" in preparing["wording"]

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert saved["outcome"] == "review_required"
    reviewing = presentation(_state(workspace))
    assert "Proposal Review pending" in reviewing["wording"]


def test_domain_and_finalization_tools_stop_at_pending_proposal_review(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    from support.rob2 import _prepared_evidence

    evidence = _prepared_evidence(workspace)
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert saved["outcome"] == "review_required"
    revision = int(saved["head"]["state_revision"])

    context = _raw_call(workspace, "get_domain_context", {})
    assert context["outcome"] == "condition"
    detail = context["condition"]["detail"]
    assert "Stop: Proposal Review is pending" in detail
    assert "Do not perform or report Domain judgments" in detail
    assert "call get_status and follow next_action" in detail

    finalized = _raw_call(workspace, "finalize_batch", {"expected_revision": revision})
    assert finalized["outcome"] == "condition"
    assert finalized["condition"]["detail"] == detail


def test_terminal_exact_stale_retry(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    from support.rob2 import _prepared_evidence

    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    revision = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    request = cast(
        dict[str, object],
        {
            "request": {
                "disposition": "needs_input",
                "trial_id": "trial",
                "reason": "A required fact is not reported.",
                "missing_facts": ["The required fact."],
            },
            "expected_revision": revision,
        },
    )
    first = _call(workspace, "request_trial_terminal", request)
    assert first["outcome"] == "success"
    retry = _call(workspace, "request_trial_terminal", request)
    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True


def test_finalize_exact_stale_retry(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    from support.rob2 import _prepared_evidence

    evidence = _prepared_evidence(workspace)
    _call(
        workspace,
        "save_proposal",
        _proposal_args(
            workspace,
            [_unavailable_result(evidence, "The intended endpoint is not reported.")],
        ),
    )
    _review(workspace)
    revision = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    first = _call(workspace, "finalize_batch", {"expected_revision": revision})
    retry = _call(workspace, "finalize_batch", {"expected_revision": revision})
    assert first["outcome"] == "success"
    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True
    stale_finalized = _call(workspace, "finalize_batch", {"expected_revision": revision})
    assert stale_finalized["outcome"] == "success"
    assert stale_finalized["data"]["retry"] is True
    assert stale_finalized["data"]["artifact"] == first["data"]["artifact"]
