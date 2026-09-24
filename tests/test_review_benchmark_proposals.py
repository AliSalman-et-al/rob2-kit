from __future__ import annotations

import json
import runpy
import subprocess
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def reviewer(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    scripts = Path(__file__).parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return runpy.run_path(str(scripts / "review_benchmark_proposals.py"))


def _review(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": "review-1",
        "candidate": {"proposal": {"results": [result]}},
    }


def _result() -> dict[str, Any]:
    return {
        "trial_id": "TRIAL-A",
        "requested_outcome": "Overall Survival",
        "target": {
            "comparison_groups": [{"id": "control"}, {"id": "treatment"}],
            "outcome_definition": "death from any cause",
            "intended_analysis_population": "all randomized participants",
            "time_point_or_window": "36 months",
        },
        "reported": {
            "form": "comparative_effect",
            "analysis_population": "all randomized participants",
            "endpoint": {"definition": "death from any cause"},
            "effect_measure": "hazard_ratio",
            "estimate": "HR 0.75",
            "precision": "95% CI 0.60 to 0.90",
            "group_values": [],
        },
    }


def _expected(reviewer: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    dimensions = reviewer["_result_dimensions"](result, "TRIAL-A")
    return {
        "trial": dimensions["trial"],
        "comparison": dimensions["comparison"],
        "endpoint_definition": dimensions["endpoint_definition"],
        "population": dimensions["population"],
        "window_or_cutoff": dimensions["window_or_cutoff"],
        "estimate": dimensions["estimate"],
        "precision": dimensions["precision"],
        "reported_scope": dimensions["reported_scope"],
    }

def test_portable_cli_lookup_uses_venv_bin_when_present(
    reviewer: dict[str, Any], tmp_path: Path
) -> None:
    executable = tmp_path / ".venv" / "bin" / "rob2"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")

    assert reviewer["_rob2_executable"](tmp_path) == str(executable)


def test_yes_inspects_exact_scope_before_acknowledging(
    reviewer: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _result()
    response = json.dumps(_review(result)).encode()
    approval = (
        response
        + b"\n"
        + json.dumps(
            {"acknowledgment_record": {"review_identity": "review-1"}}
        ).encode()
        + b"\n"
    )
    calls: list[tuple[list[str], bytes]] = []

    def run(command, **kwargs):
        calls.append((command, kwargs["input"]))
        return subprocess.CompletedProcess(
            command,
            0 if kwargs["input"] == b"yes\n" else 1,
            approval if kwargs["input"] == b"yes\n" else response,
            b"",
        )

    monkeypatch.setitem(reviewer["_one"].__globals__, "_rob2_executable", lambda repo: "rob2")
    monkeypatch.setattr(subprocess, "run", run)
    item = {
        "outcome": "Overall Survival",
        "trial": "TRIAL-A",
        "run_dir": str(tmp_path / "run"),
        "expected_result": _expected(reviewer, result),
    }

    recorded = reviewer["_one"](tmp_path, item, "yes", tmp_path / "reviews")

    assert [call[1] for call in calls] == [b"no\n", b"yes\n"]
    assert calls[1][0][-2:] == ["--review-reference", "review-1"]
    assert recorded["approved"] is True
    assert recorded["approval_reference_matches"] is True
    assert recorded["scope_mismatches"] == []


def test_yes_refuses_scope_mismatch_without_acknowledging(
    reviewer: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _result()
    expected = _expected(reviewer, result)
    expected["estimate"] = "HR 0.80"
    expected["reported_scope"]["estimate"] = "HR 0.80"
    response = json.dumps(_review(result)).encode()
    calls: list[bytes] = []

    def run(command, **kwargs):
        calls.append(kwargs["input"])
        return subprocess.CompletedProcess(command, 1, response, b"")

    monkeypatch.setitem(reviewer["_one"].__globals__, "_rob2_executable", lambda repo: "rob2")
    monkeypatch.setattr(subprocess, "run", run)
    item = {
        "outcome": "Overall Survival",
        "trial": "TRIAL-A",
        "run_dir": str(tmp_path / "run"),
        "expected_result": expected,
    }

    recorded = reviewer["_one"](tmp_path, item, "yes", tmp_path / "reviews")

    assert calls == [b"no\n"]
    assert recorded["approved"] is False
    assert recorded["scope_mismatches"][0]["field"] == "estimate"


def test_cli_rejects_approval_after_inspected_review_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = runpy.run_path(
        str(Path(__file__).parents[1] / "src" / "rob2_kit" / "interfaces" / "cli" / "app.py")
    )
    namespace = cli["main"].__globals__
    monkeypatch.setitem(
        namespace,
        "get_status",
        lambda _workspace: {"continuation": {"operation": "researcher_review"}},
    )
    monkeypatch.setitem(namespace, "_root", lambda workspace: workspace)
    monkeypatch.setitem(namespace, "_state", lambda _root: {"review": {"identity": "review-2"}})
    monkeypatch.setitem(namespace, "_read_review_acknowledgment", lambda _prompt: "yes")
    approved: list[str] = []
    monkeypatch.setitem(
        namespace,
        "approve_review",
        lambda _workspace, reference: approved.append(reference),
    )

    with pytest.raises(SystemExit, match="2"):
        cli["main"](["review", "--review-reference", "review-1"])

    assert approved == []
