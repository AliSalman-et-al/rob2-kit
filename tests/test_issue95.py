"""Run-control envelope and MCP composition contracts for issue #95."""

from __future__ import annotations

import anyio

from rob2_kit.application.contracts import (
    GetRunStatusRequest,
    GetRunStatusResponse,
    NextAction,
    RunOperation,
    RunState,
    WorkflowCondition,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.interfaces.mcp.server import (
    canonical_status_route_group,
    canonical_tool_names,
    create_server,
    register_route_groups,
)


def _response(**overrides: object) -> GetRunStatusResponse:
    fields: dict[str, object] = {
        "operation_id": "operation:status-test",
        "ledger_cursor": "ledger:1",
        "affected_scope": ("run:test",),
        "condition": WorkflowCondition.COMPLETED,
        "committed": False,
        "run_id": "run:test",
        "run_state": RunState.ASSESSING,
    }
    fields.update(overrides)
    return GetRunStatusResponse.model_validate(fields)


def test_expand_response_accepts_legacy_name_but_emits_one_typed_next_action() -> None:
    response = _response(next_permitted_action=RunOperation.CONTINUE_RUN)

    assert isinstance(response.next_action, NextAction)
    assert response.next_action.operation is RunOperation.CONTINUE_RUN
    assert response.next_action.arguments.run_id == "run:test"
    dumped = response.model_dump(mode="json")
    assert "next_action" in dumped
    assert "next_permitted_action" not in dumped


def test_terminal_response_omits_next_action() -> None:
    response = _response(run_state=RunState.COMPLETE)

    assert response.next_action is None
    assert "next_action" not in response.model_dump(mode="json", exclude_none=True)


def test_canonical_status_alias_resolves_to_the_same_engine_operation() -> None:
    engine = RunEngine()

    assert engine.get_run_status.__self__ is engine
    assert GetRunStatusRequest(run_id="run:test").run_id == "run:test"


def test_route_groups_are_additive_and_deterministic() -> None:
    async def list_names() -> tuple[str, ...]:
        server = create_server(route_groups=(canonical_status_route_group(),))
        return tuple(tool.name for tool in await server.list_tools())

    names = anyio.run(list_names)
    assert names[-1] == "get_run_status"
    assert canonical_tool_names()[1] == "get_run_status"


def test_route_group_names_must_be_unique() -> None:
    server = create_server()
    group = canonical_status_route_group()

    try:
        register_route_groups(server, RunEngine(), (group, group))
    except ValueError as error:
        assert "unique" in str(error)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("duplicate route groups must be rejected")
