from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastmcp import Client
from support.rob2 import _call, _prepared_evidence, _proposal_args, _result, _workspace

from rob2_kit.interfaces.mcp.contracts import validate_output
from rob2_kit.interfaces.mcp.server import mcp


def test_fastmcp_aggregates_duplicate_result_and_group_repairs(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    first = _result(evidence)
    second = _result(evidence)
    first["target"]["comparison_groups"] = [
        {"id": "a", "assignment": "assigned to intervention"},
        {"id": "a", "assignment": "assigned to intervention duplicate"},
    ]
    first["reported"]["values"] = [
        {"group_id": "a", "statistic": "risk", "value": "1", "unit": "events"},
        {"group_id": "a", "statistic": "risk", "value": "2", "unit": "events"},
    ]
    proposal_args = _proposal_args(workspace, [first, second])

    async def invoke() -> dict[str, Any]:
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        async with Client(mcp) as client:
            result = await client.call_tool(
                "save_proposal",
                proposal_args,
            )
        return dict(result.structured_content or {})

    receipt = asyncio.run(invoke())
    assert receipt["outcome"] == "repair"
    assert validate_output("save_proposal", receipt) == receipt
    assert all(repair["detail"] for repair in receipt["repairs"])
    codes = {repair["code"] for repair in receipt["repairs"]}
    assert {
        "duplicate_trial_result",
        "duplicate_target_group",
        "duplicate_reported_group",
    } <= codes


def test_fastmcp_aggregates_reported_group_set_mismatch(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["values"][1]["group_id"] = "unexpected"
    receipt = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert receipt["outcome"] == "repair"
    mismatch = next(
        item for item in receipt["repairs"] if item["code"] == "reported_group_set_mismatch"
    )
    assert mismatch["path"] == "/results/0/reported/values"
    assert "missing IDs: b" in mismatch["detail"]
    assert "unexpected IDs: unexpected" in mismatch["detail"]
