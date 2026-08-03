"""Failure-injection coverage for issue #61 report publication ordering."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.storage import (
    CommitResult,
    LeaseToken,
    Transition,
    WorkflowEventOutcome,
    dependency_fingerprint,
)

NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)
LEASE = LeaseToken(
    owner_id="owner:test",
    fencing_token=1,
    expires_at=datetime(2026, 8, 4, 13, tzinfo=UTC),
)


class _FakeLedger:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def commit_batch(self, transitions, lease, *, now):
        self.calls += 1
        if self.fail:
            raise RuntimeError("injected ledger failure")
        return tuple(
            CommitResult(
                operation_id=transition.operation_key,
                sequence=index,
                event_id=f"event:{index}",
                artifact_hash="sha256:" + "0" * 64,
                dependency_fingerprint=dependency_fingerprint(()),
            )
            for index, transition in enumerate(transitions, start=1)
        )


def _transition(root: Path) -> tuple[Transition, Path, Path]:
    staging = root / "output" / "report-bundle" / ".report-staging"
    visible = root / "output" / "report-bundle" / "runs" / "run-1"
    staging.mkdir(parents=True)
    (staging / "assessment.html").write_text("verified", encoding="utf-8")
    payload = json.dumps(
        {
            "run_id": "run:1",
            "result_id": "result:1",
            "assessment_revision_id": "assessment:1",
            "overall_judgment": "low",
            "domain_judgments": {},
            "report_root": visible.relative_to(root).as_posix(),
            "staging_root": staging.relative_to(root).as_posix(),
            "artifact_names": ["assessment.html"],
        }
    ).encode()
    transition = Transition(
        scope="result:1",
        operation="operation:result-report-ready",
        operation_key="idempotency:report-ready-1",
        actor=Actor(kind=ActorKind.SYSTEM, actor_id="actor:test", display_name="test"),
        observed_at=NOW,
        entity_id="report:1",
        revision_id="revision:report-1",
        artifact=payload,
        artifact_media_type="application/json",
        expected_dependency_fingerprint=dependency_fingerprint(()),
        outcome=WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED,
    )
    return transition, staging, visible


def test_ledger_failure_rolls_visible_bundle_back_to_hidden_stage(tmp_path: Path) -> None:
    engine = RunEngine()
    engine._root = tmp_path
    ledger = _FakeLedger(fail=True)
    transition, staging, visible = _transition(tmp_path)

    with pytest.raises(RuntimeError, match="injected ledger failure"):
        engine._commit_transitions(ledger, (transition,), LEASE, now=NOW)

    assert ledger.calls == 1
    assert staging.is_dir()
    assert not visible.exists()


def test_publication_failure_does_not_commit_and_retry_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = RunEngine()
    engine._root = tmp_path
    ledger = _FakeLedger()
    transition, staging, visible = _transition(tmp_path)

    def fail_replace(_source: str | Path, _target: str | Path) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr("rob2_kit.application.run_engine.os.replace", fail_replace)
    with pytest.raises(OSError, match="injected publication failure"):
        engine._commit_transitions(ledger, (transition,), LEASE, now=NOW)
    assert ledger.calls == 0
    assert staging.is_dir()
    assert not visible.exists()

    monkeypatch.undo()
    ledger.fail = False
    engine._commit_transitions(ledger, (transition,), LEASE, now=NOW)
    assert ledger.calls == 1
    assert visible.is_dir()
    assert not staging.exists()
