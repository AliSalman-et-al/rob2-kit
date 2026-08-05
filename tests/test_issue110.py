"""Installed-wheel replay qualification contract (#110)."""

from pathlib import Path

from rob2_kit.evaluation.installed_replay import (
    normalize_replay_trace,
    normalize_semantic_value,
    semantic_projection,
)

ROOT = Path(__file__).resolve().parents[1]


def test_installed_replay_normalizes_live_call_ids_and_projects_to_durable_semantics() -> None:
    trace = normalize_replay_trace(
        [
            {
                "name": "prepare_run",
                "arguments": {"project_root": "C:/temporary/a"},
                "response": {"run_id": "run:one", "run_state": "assessing"},
            },
            {
                "name": "continue_run",
                "arguments": {"run_id": "run:one", "work_token": "work-token:one"},
                "response": {"run_id": "run:one", "run_state": "complete"},
            },
        ],
        final={"run_id": "run:one", "run_state": "complete"},
    )

    assert trace["calls"][0]["arguments"]["project_root"] == "<path-1>"
    assert trace["calls"][1]["arguments"]["run_id"] == "<run-1>"
    assert trace["calls"][1]["arguments"]["work_token"] == "<work-token-1>"
    assert trace["final"]["run_id"] == "<run-1>"
    assert semantic_projection(
        {"run_state": "complete", "events": ["one"], "volatile": "ignore"}
    ) == {"run_state": "complete", "events": ["one"]}
    assert normalize_semantic_value({"run_id": "run:one"}) == {"run_id": "<run-1>"}


def test_installed_replay_qualification_has_the_required_contract_matrix() -> None:
    qualification = (ROOT / "scripts" / "release_qualification.py").read_text(encoding="utf-8")

    for scenario in (
        "malformed",
        "unknown",
        "invalid",
        "wrong-state",
        "stale",
        "cross-scope",
        "retry",
        "writer",
        "retrieval-condition",
        "interruption",
        "input-change",
        "report-failure",
        "integrity",
    ):
        assert scenario in qualification
    assert "installed-replay.golden.json" in qualification
    assert "accept_golden" in qualification


def test_ci_qualifies_an_installed_replay_without_a_model_or_private_corpus() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").casefold()
    qualification = (ROOT / "scripts" / "release_qualification.py").read_text(
        encoding="utf-8"
    ).casefold()

    assert "release_qualification.py" in workflow
    assert "model" not in workflow
    assert "private-release-evaluation.md" not in workflow
    assert "accept_golden(" in qualification
    assert "--accept-replay-golden" in qualification
