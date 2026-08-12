"""Public MCP surface tracer regressions after removal of domain-wide evidence tools."""

import anyio

from rob2_kit.application.contracts import RunOperation
from rob2_kit.interfaces.mcp.server import (
    CANONICAL_TOOL_NAMES,
    create_server,
    registered_tool_names,
)


def test_public_tool_inventory_exposes_the_v3_question_checkpoint_flow() -> None:
    names = set(CANONICAL_TOOL_NAMES)

    assert {
        "get_work_context",
        "search_evidence",
        "read_evidence",
        "submit_evidence_review",
        "submit_evidence_stage_outcome",
        "materialize_question_evidence_bundle",
        "submit_question_step",
        "correct_question_step",
    } <= names
    assert (
        not {
            "submit_domain_evidence",
            "submit_domain_answers",
            "correct_domain_answers",
        }
        & names
    )
    assert registered_tool_names() == CANONICAL_TOOL_NAMES


async def _tool_names_from_server() -> tuple[str, ...]:
    server = create_server()
    tools = await server.list_tools()
    return tuple(tool.name for tool in tools)


def test_live_server_registration_matches_the_canonical_tracer_inventory() -> None:
    assert anyio.run(_tool_names_from_server) == CANONICAL_TOOL_NAMES


def test_question_scoped_operations_remain_first_class_run_operations() -> None:
    assert (
        RunOperation.MATERIALIZE_QUESTION_EVIDENCE_BUNDLE.value
        == "materialize_question_evidence_bundle"
    )
    assert RunOperation.SUBMIT_QUESTION_STEP.value == "submit_question_step"
    assert RunOperation.CORRECT_QUESTION_STEP.value == "correct_question_step"
