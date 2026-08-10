"""Installed-wheel replay qualification contract (#110)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

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
    durable = normalize_semantic_value(
        {
            "ledger_cursor": "ledger:42",
            "trial_id": "trial:alpha",
            "result_id": "result:alpha-mortality",
        }
    )
    assert durable == {
        "ledger_cursor": "<ledger-cursor-1>",
        "trial_id": "trial:alpha",
        "result_id": "result:alpha-mortality",
    }
    assert semantic_projection(
        {"run_state": "complete", "events": ["one"], "volatile": "ignore"}
    ) == {"run_state": "complete", "events": ["one"]}
    assert normalize_semantic_value({"run_id": "run:one"}) == {"run_id": "<run-1>"}


def test_installed_replay_normalizes_ephemeral_location_handles_but_preserves_reuse() -> None:
    """Navigation-token bytes may change, but their call structure may not."""

    def trace(handles: tuple[str, str]) -> dict[str, object]:
        return normalize_replay_trace(
            [
                {
                    "name": "search_evidence",
                    "arguments": {},
                    "response": {
                        "page": {
                            "hits": [
                                {"location_handle": handles[0]},
                                {"location_handle": handles[1]},
                            ]
                        }
                    },
                }
            ],
            final={"run_state": "complete"},
        )

    assert trace(("loc:first", "loc:second")) == trace(("loc:renamed-a", "loc:renamed-b"))
    assert trace(("loc:reused", "loc:reused")) != trace(("loc:distinct-a", "loc:distinct-b"))


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
    assert "qualification_capabilities" not in qualification
    assert 'issued_token = evidence["work_item"]["work_token"]' in qualification
    assert '"sq_id": "sq:qualification-invalid"' in qualification
    assert '"result_id": "result:other"' in qualification
    assert '"location_handle": "loc:qualification-unknown"' in qualification
    assert '"read_view_receipt": read_receipts[question]' in qualification
    assert '"contract_version": "1.2.0"' in qualification
    assert '"get_work_context"' in qualification
    assert '"active_question_ids"' in qualification
    assert '"sq:measurement:assessor-aware"' in qualification
    assert "protocol validation recovery" not in qualification


def test_ci_qualifies_an_installed_replay_without_a_model_or_private_corpus() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").casefold()
    qualification = (
        (ROOT / "scripts" / "release_qualification.py").read_text(encoding="utf-8").casefold()
    )

    assert "release_qualification.py" in workflow
    assert "model" not in workflow
    assert "private-release-evaluation.md" not in workflow
    assert "accept_golden(" in qualification
    assert "--accept-replay-golden" in qualification


def test_qualification_composition_uses_real_engine_dependencies() -> None:
    """The installed stdio composition root injects dependencies, not responses."""

    from rob2_kit.evaluation.qualification import qualification_engine_from_environment
    from rob2_kit.storage import LeaseConflictError

    absent_registry = qualification_engine_from_environment(
        None, {"ROB2_QUALIFICATION_ABSENT_FIXTURES": "registry_history"}
    )
    assert absent_registry._registry_adapter is not None
    acquisition = absent_registry._registry_adapter.acquire(declared_nct_id="NCT00000001")
    assert acquisition.resolution.explicit is True
    assert acquisition.history is not None and acquisition.history.available is False
    assert absent_registry._registry_client is None
    with pytest.raises(ValueError, match="unknown qualification fixture"):
        qualification_engine_from_environment(
            None, {"ROB2_QUALIFICATION_ABSENT_FIXTURES": "visual_rendering"}
        )

    writer_conflict = qualification_engine_from_environment(
        None, {"ROB2_QUALIFICATION_INJECTED_FAULT": "writer"}
    )
    with pytest.raises(LeaseConflictError, match="writer lease"):
        writer_conflict._lease_acquirer(  # type: ignore[misc]
            SimpleNamespace(events=lambda: (SimpleNamespace(operation="operation:run-prepared"),)),
            None,
        )


def test_release_fixture_exposes_reusable_structure_only_canonical_lineage() -> None:
    """The public journey reviews one source fragment in each Domain/SQ scope."""

    from rob2_kit.evaluation.qualification import _ReleaseFixtureParser
    from scripts.release_qualification import _blank_pdf

    parsed = _ReleaseFixtureParser().parse(_blank_pdf(), ocr_enabled=False)
    items = parsed.pages[0].text_items
    assert len({item.fragment_id for item in items}) == len(items)
    assert all(item.fragment_id is not None for item in items)
    assert all(
        not {"trial_id", "result_id", "domain_id", "question_ids", "applicability"}.intersection(
            item.model_dump()
        )
        for item in items
    )

    qualification = (ROOT / "scripts" / "release_qualification.py").read_text(encoding="utf-8")
    assert 'unit["domain_id"] == domain' not in qualification


def test_qualification_receipt_records_stable_stage_timing_metadata() -> None:
    qualification = (ROOT / "scripts" / "release_qualification.py").read_text(encoding="utf-8")

    assert '"schema_version": 1' in qualification
    assert '"stages": STAGE_TIMINGS' in qualification
    assert '"total_duration_seconds"' in qualification
    assert "timeout_seconds: int = 600" in qualification
    assert "_terminate_process_tree(process)" in qualification
    assert '"taskkill", "/PID"' in qualification


def test_ci_runs_replay_without_repeating_the_release_lifecycle_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "--replay-only" in workflow
    assert "--skip-full-suite" in workflow
    script = (ROOT / "scripts" / "release_qualification.py").read_text(encoding="utf-8")
    assert '"qualification_mode": "replay_only" if replay_only else "full"' in script
    assert '"skipped_stages": ["lifecycle"] if replay_only else []' in script
    assert '"lifecycle": None if lifecycle is None else lifecycle.receipt' in script
    assert (
        "lifecycle = (\n            None\n            if replay_only\n"
        "            else _qualify_lifecycle" in script
    )
    assert script.count('"idempotency_key": "qualification:proposal"') == 2
    assert script.count('"idempotency_key": "qualification:confirm"') == 2


def test_optional_fixture_resume_checks_post_confirmation_work_without_repeating_source_review() -> (
    None
):
    qualification = (ROOT / "scripts" / "release_qualification.py").read_text(encoding="utf-8")

    assert 'event["operation"] == "operation:submit-source-role-review"' in qualification
    assert "resume repeated the committed source-role review" in qualification
    assert "resume did not continue with post-confirmation domain evidence work" in qualification
    assert "resume did not retain its post-confirmation work-token identity" in qualification
    assert "resume did not reissue the committed active work-token identity" not in qualification


def test_timeout_cleanup_remains_bounded_when_tree_termination_fails(monkeypatch) -> None:
    """A broken taskkill path cannot cause an unbounded final communicate."""

    import importlib.util
    import subprocess
    import sys

    path = ROOT / "scripts" / "release_qualification.py"
    spec = importlib.util.spec_from_file_location("release_qualification", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class Process:
        returncode = None
        pid = 123

        def __init__(self) -> None:
            self.timeouts: list[int] = []
            self.killed = False

        def communicate(self, *, timeout: int):
            self.timeouts.append(timeout)
            raise subprocess.TimeoutExpired(["qualification-child"], timeout)

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    process = Process()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(module, "_terminate_process_tree", lambda ignored: None)

    with pytest.raises(RuntimeError, match="could not be reaped"):
        module._run(["qualification-child"], cwd=ROOT, timeout_seconds=1)
    assert process.timeouts == [1, 5, 5]
    assert process.killed is True
