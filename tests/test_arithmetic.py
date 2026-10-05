"""Numeric correctness and the boundary of optional, source-independent scratch arithmetic."""

import asyncio
from decimal import ROUND_DOWN, DefaultContext, Inexact, localcontext

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from support.rob2 import _assessment_workspace

from rob2_kit.application._state import _state
from rob2_kit.application.arithmetic import calculate_arithmetic
from rob2_kit.interfaces.mcp.contracts import (
    ArithmeticData,
    normalize,
    output_schema,
    validate_output,
)
from rob2_kit.interfaces.mcp.server import mcp


@pytest.mark.parametrize(
    ("expression", "inputs", "result"),
    [
        ("82.4 - (81.1 * 42 + 100) / 43", {}, "0.86046511627906976744186047"),
        ("82.4 - (81.1 * 42 + 0) / 43", {}, "3.18604651162790697674418605"),
        ("(1.18*44+6*10)/50", {}, "2.2384"),
        ("(3.13*47)/50 - (1.18*44+6*10)/50", {}, "0.7038"),
        (
            "(mean * observed + added) / (observed + 1)",
            {"mean": "12.5", "observed": "7", "added": "-4"},
            "10.4375",
        ),
        ("(3 / 40) * 100", {}, "7.500"),
        ("-(-2) + .5 * (+4)", {}, "4.0"),
        ("0.1 + 0.2", {}, "0.3"),
        ("1 / 3", {}, "0.3333333333333333333333333333"),
        ("left - right", {"left": "-2.50", "right": "1.25"}, "-3.75"),
    ],
)
def test_arithmetic_and_conditional_examples(expression, inputs, result):
    data = calculate_arithmetic(expression, inputs, "declared units", ["Conditional values"])
    assert data["result"] == result
    assert data["expression"] == expression and data["inputs"] == inputs
    assert data["units"] == "declared units" and data["assumptions"] == ["Conditional values"]
    assert ArithmeticData.model_validate(data).model_dump(mode="json") == data
    assert normalize("calculate_arithmetic", data) == data
    assert validate_output("calculate_arithmetic", data) == data


@pytest.mark.parametrize(
    ("expression", "inputs"),
    [
        ("1 / 0", {}),
        ("0 / 0", {}),
        ("", {}),
        ("1 +", {}),
        ("unknown + 1", {}),
        ("NaN", {}),
        ("Infinity", {}),
        ("value", {"value": "NaN"}),
        ("value", {"value": "Infinity"}),
        ("value", {"value": "1e100"}),
        ("1e100", {}),
        ("1_000", {}),
        ("0x10", {}),
        ("True", {}),
        ("'1'", {}),
        ("__import__('os').system('id')", {}),
        ("open('file')", {}),
        ("value.real", {"value": "1"}),
        ("[1][0]", {}),
        ("2 ** 3", {}),
        ("8 // 2", {}),
        ("5 % 2", {}),
        ("1; 2", {}),
        ("1 # ignored syntax", {}),
        ("(x for x in [1])", {}),
        ("lambda: 1", {}),
        ("1" * 65, {}),
        ("1+" * 256 + "1", {}),
        ("+" * 65 + "1", {}),
        ("value", {"value": "1" * 65}),
        ("value", {"value": " 1"}),
        ("1", {"bad-name": "2"}),
        ("1", {f"v{i}": "1" for i in range(17)}),
        ("*".join(["9" * 64] * 5), {}),
        ("*".join(["0." + "0" * 61 + "1"] * 5), {}),
    ],
)
def test_invalid_or_executable_arithmetic_is_rejected(expression, inputs):
    with pytest.raises(ValueError):
        calculate_arithmetic(expression, inputs)


def test_precision_is_local_deterministic_and_reports_rounding():
    with localcontext() as outer:
        outer.prec, outer.rounding = 3, ROUND_DOWN
        outer.traps[Inexact] = True
        data = calculate_arithmetic("1 / 3", {})
        assert data["precision"] == 28 and data["rounding"] == "ROUND_HALF_EVEN"
        assert data["result"] == "0.3333333333333333333333333333"
        assert data["inexact"] and data["rounded"]
        assert not outer.flags[Inexact] and outer.prec == 3
    previous = DefaultContext.traps[Inexact]
    try:
        DefaultContext.traps[Inexact] = True
        assert calculate_arithmetic("1 / 3", {})["result"] == data["result"]
    finally:
        DefaultContext.traps[Inexact] = previous
    exact = calculate_arithmetic("1 / 8", {})
    assert not exact["inexact"] and not exact["rounded"]
    half_even = calculate_arithmetic("1.0000000000000000000000000005", {})
    assert half_even["result"] == "1.000000000000000000000000000"
    assert half_even["inexact"] and half_even["rounded"]
    upper = calculate_arithmetic("1.0000000000000000000000000015", {})
    assert upper["result"] == "1.000000000000000000000000002"


def test_native_calculator_has_no_workspace_dependency_and_preserves_state(tmp_path, monkeypatch):
    workspace, _, _ = _assessment_workspace(tmp_path)
    before = _state(workspace)
    monkeypatch.setenv("ROB2_WORKSPACE", str(workspace))
    import rob2_kit.interfaces.mcp.server as server

    monkeypatch.setattr(server, "_workspace", lambda: pytest.fail("calculator accessed workspace"))

    async def inspect():
        async with Client(mcp) as client:
            tool = next(
                tool for tool in await client.list_tools() if tool.name == "calculate_arithmetic"
            )
            assert set(tool.input_schema["properties"]) == {
                "expression",
                "inputs",
                "units",
                "assumptions",
            }
            assert tool.input_schema["required"] == ["expression"]
            assert tool.output_schema == output_schema("calculate_arithmetic")
            assert tool.annotations and tool.annotations.read_only_hint
            result = await client.call_tool(
                "calculate_arithmetic",
                {
                    "expression": " first - second ",
                    "inputs": {"first": "2", "second": "5"},
                    "units": "points",
                    "assumptions": ["Caller-selected values"],
                },
            )
            data = result.structured_content
            assert data and data["result"] == "-3"
            assert data["expression"] == " first - second " and "head" not in data
            assert ArithmeticData.model_validate(data).model_dump(mode="json") == data
            for arguments in [
                {"expression": "1/0"},
                {"expression": "open('x')"},
                {"expression": 2},
                {"expression": "1", "assumptions": ["x" * 201]},
            ]:
                with pytest.raises(ToolError):
                    await client.call_tool("calculate_arithmetic", arguments)

    asyncio.run(inspect())
    assert _state(workspace) == before
