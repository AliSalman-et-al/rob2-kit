"""Guard drift must fail before any model invocation, using one policy file."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError


@pytest.fixture
def controls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    return importlib.import_module("domain_probe_controls")


@pytest.mark.parametrize("bad_value", [True, 400000.0, "400000", 0, -1])
def test_guard_values_require_positive_json_integers(controls, bad_value) -> None:
    values = controls.approved_limits().model_dump()
    values["input_tokens"] = bad_value
    with pytest.raises(ValidationError):
        controls.ProbeLimits.model_validate(values)


def test_preparation_prompt_manifest_and_monitor_share_guard_values(
    controls, tmp_path: Path
) -> None:
    controls.write_controls(tmp_path, {"case": "trial"}, "Assess the approved Result.")
    manifest, limits, prompt = controls.load_controls(tmp_path)
    assert limits.input_tokens == 400000  # The approved bound, not the historical 500k error.
    assert manifest["guards"] == limits.model_dump() == controls.approved_limits().model_dump()
    assert prompt.endswith(limits.prompt_suffix())
    assert manifest["guard_identity"] == limits.identity()
    assert (
        controls.guard_stop(
            limits,
            {"input_tokens": 384822, "cached_input_tokens": 325888, "output_tokens": 2281},
            tools=11,
            rejections=0,
            wall_seconds=168,
            idle_seconds=1,
        )
        is None
    )
    assert (
        controls.guard_stop(
            limits,
            {"input_tokens": 441823, "cached_input_tokens": 381952, "output_tokens": 2415},
            tools=12,
            rejections=0,
            wall_seconds=169,
            idle_seconds=1,
        )
        == "total input threshold"
    )


@pytest.mark.parametrize("drift", ["guards", "guard_identity", "prompt"])
def test_control_drift_is_rejected_before_process_creation(
    controls, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, drift: str
) -> None:
    controls.write_controls(tmp_path, {}, "Assess the approved Result.")
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    if drift == "guards":
        manifest["guards"]["input_tokens"] = 500000
        manifest["guard_identity"] = controls.ProbeLimits.model_validate(
            manifest["guards"]
        ).identity()
    elif drift == "guard_identity":
        manifest["guard_identity"] = "sha256:" + "0" * 64
    else:
        prompt = (tmp_path / "prompt.txt").read_text().replace("400000", "500000")
        (tmp_path / "prompt.txt").write_text(prompt)
        manifest["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    launcher = importlib.import_module("run_domain_probe")

    def forbidden_process(*args, **kwargs):
        pytest.fail("invalid probe controls reached process creation")

    monkeypatch.setattr(launcher.subprocess, "Popen", forbidden_process)
    with pytest.raises(ValueError, match="guards|guard section"):
        launcher.run(tmp_path)


def test_preparation_does_not_overwrite_preserved_controls(controls, tmp_path: Path) -> None:
    controls.write_controls(tmp_path, {}, "Original task.")
    before = (tmp_path / "manifest.json").read_bytes(), (tmp_path / "prompt.txt").read_bytes()
    with pytest.raises(ValueError, match="preserve"):
        controls.write_controls(tmp_path, {}, "Replacement task.")
    assert before == (
        (tmp_path / "manifest.json").read_bytes(),
        (tmp_path / "prompt.txt").read_bytes(),
    )


@pytest.mark.parametrize(
    "guard", ["tool", "rejection", "input", "uncached", "output", "wall", "idle"]
)
def test_monitor_uses_each_validated_limit(controls, guard: str) -> None:
    limits = controls.approved_limits()
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    counters = {"tools": 0, "rejections": 0, "wall_seconds": 0, "idle_seconds": 0}
    expected = {
        "tool": "tool limit",
        "rejection": "rejected submission limit",
        "input": "total input threshold",
        "uncached": "uncached input threshold",
        "output": "output threshold",
        "wall": "wall threshold",
        "idle": "idle threshold",
    }
    if guard == "tool":
        counters["tools"] = limits.tool_calls
    elif guard == "rejection":
        counters["rejections"] = limits.rejected_submissions
    elif guard == "input":
        usage.update(input_tokens=limits.input_tokens, cached_input_tokens=limits.input_tokens)
    elif guard == "uncached":
        usage["input_tokens"] = limits.uncached_input_tokens
    elif guard == "output":
        usage["output_tokens"] = limits.output_tokens
    elif guard == "wall":
        counters["wall_seconds"] = limits.wall_seconds
    else:
        counters["idle_seconds"] = limits.idle_seconds
    assert controls.guard_stop(limits, usage, **counters) == expected[guard]


def test_probe_uses_direct_mcp_without_changing_model_or_access(controls, tmp_path: Path) -> None:
    launcher = importlib.import_module("run_domain_probe")
    command = launcher.probe_command(tmp_path)
    assert command[command.index("-m") + 1] == "gpt-6-luna"
    assert command[command.index("-s") + 1] == "read-only"
    assert 'model_reasoning_effort="medium"' in command
    assert 'features.code_mode={enabled=true,direct_only_tool_namespaces=["mcp__rob2"]}' in command


def test_recorded_context_replays_losslessly_with_bounded_pages(controls) -> None:
    from replay_domain_probe_delivery import replay

    path = (
        Path(__file__).parents[1]
        / "docs/evaluation/2026-10-02-deliver-d3-completion-17bad3d/events.jsonl"
    )
    result = replay(path)
    assert result["scientific_data_recovered_exactly"]
    assert len(result["default_pages"]) > 1
    assert result["all_recovery_cursors_preserved"]
