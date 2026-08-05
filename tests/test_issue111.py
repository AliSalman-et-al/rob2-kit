"""Explicit local commercial-host smoke orchestration (#111)."""

from pathlib import Path

import pytest

from rob2_kit.evaluation.local_host_smoke import (
    CommercialHostOptInRequired,
    HostSmokeOptions,
    build_smoke_plan,
    cleanup_smoke_workspace,
    compare_semantic_outcomes,
    redact_diagnostic,
)


def test_real_hosts_require_two_explicit_local_opt_ins(tmp_path: Path) -> None:
    options = HostSmokeOptions(wheel=tmp_path / "rob2_kit.whl", workspace=tmp_path / "smoke")

    with pytest.raises(CommercialHostOptInRequired):
        build_smoke_plan(options, environ={})
    with pytest.raises(CommercialHostOptInRequired):
        build_smoke_plan(options, environ={"ROB2_LOCAL_COMMERCIAL_HOST_SMOKE": "1"})
    with pytest.raises(CommercialHostOptInRequired, match="CI"):
        build_smoke_plan(
            options,
            environ={"ROB2_LOCAL_COMMERCIAL_HOST_SMOKE": "1", "CI": "true"},
        )


def test_plan_uses_exact_wheel_clean_projects_and_both_resume_directions(tmp_path: Path) -> None:
    wheel = tmp_path / "rob2_kit-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    options = HostSmokeOptions(
        wheel=wheel,
        workspace=tmp_path / "smoke",
        execute=True,
        codex_model="codex-smoke-model",
        claude_model="claude-smoke-model",
    )
    plan = build_smoke_plan(
        options,
        environ={"ROB2_LOCAL_COMMERCIAL_HOST_SMOKE": "1"},
    )

    assert [scenario.first_host for scenario in plan.scenarios] == ["codex", "claude"]
    assert [scenario.resume_host for scenario in plan.scenarios] == ["claude", "codex"]
    assert all(str(wheel.resolve()) in command for command in plan.install_commands)
    assert all(command[-1] == str(wheel.resolve()) for command in plan.install_commands)
    assert all("rob2-kit==" not in " ".join(command) for command in plan.install_commands)
    assert all("doctor" in command for command in plan.doctor_commands)
    assert all("bootstrap" in command for command in plan.adapter_commands)
    assert all("rob2-mcp" in command[0] for command in plan.mcp_commands)
    assert all("--json" in command for command in plan.host_commands if command[0] == "codex")
    assert all("stream-json" in command for command in plan.host_commands if command[0] == "claude")
    assert all(
        "natural language" in scenario.checkpoint_prompt.casefold() for scenario in plan.scenarios
    )
    assert all(
        "durable run state" in scenario.resume_prompt.casefold() for scenario in plan.scenarios
    )


def test_diagnostics_are_bounded_and_secret_shaped_values_are_redacted() -> None:
    text = "OPENAI_API_KEY=sk-secret ANTHROPIC_API_KEY=anthropic-secret\n" + ("x" * 9000)
    diagnostic = redact_diagnostic(text, limit=512)

    assert "sk-secret" not in diagnostic
    assert "anthropic-secret" not in diagnostic
    assert len(diagnostic.encode()) <= 512
    assert "<redacted>" in diagnostic


def test_cross_host_comparison_ignores_wording_but_checks_durable_semantics() -> None:
    left = {
        "run_state": "complete",
        "durable_state": {"operations": ["operation:complete"]},
        "next_actions": [],
        "reports": ["assessment.html"],
        "repair_count": 0,
        "message": "Codex phrasing",
    }
    right = left | {"message": "Claude phrasing"}
    assert compare_semantic_outcomes(left, right) == {}
    assert compare_semantic_outcomes(left, right | {"repair_count": 1}) == {
        "repair_count": {"left": 0, "right": 1}
    }


def test_ci_has_no_commercial_host_smoke_trigger() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow_root = root / ".github" / "workflows"
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for pattern in ("*.yml", "*.yaml")
        for path in workflow_root.glob(pattern)
    ).casefold()
    assert "local_host_smoke" not in workflows
    assert "rob2_local_commercial_host_smoke" not in workflows


def test_cleanup_rejects_non_owned_or_mismatched_targets(tmp_path: Path) -> None:
    workspace = tmp_path / "smoke"
    workspace.mkdir()
    project = workspace / "project"
    project.mkdir()
    marker = project / ".rob2-local-host-smoke"
    marker.write_text(str(project.resolve()), encoding="utf-8")

    with pytest.raises(ValueError, match="outside"):
        cleanup_smoke_workspace(tmp_path, workspace=workspace)
    marker.write_text(str(tmp_path.resolve()), encoding="utf-8")
    with pytest.raises(ValueError, match="marker"):
        cleanup_smoke_workspace(project, workspace=workspace)
