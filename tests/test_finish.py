import asyncio
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Thread
from typing import Any

import pytest
from fastmcp import Client
from test_judgments import _save, approved_workspace

from rob2_kit.batch import ApprovedBatch, current_batch
from rob2_kit.finish import (
    FinishCondition,
    FinishConflict,
    FinishSaved,
    finish_trial,
    snapshot_content,
)
from rob2_kit.judgment_models import Override
from rob2_kit.judgments import JudgmentRevised
from rob2_kit.models import Judgment, canonical_json_bytes, sha256
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.server import mcp
from rob2_kit.sources import Source
from rob2_kit.storage import transaction

OBSERVED = datetime(2026, 8, 14, tzinfo=UTC)


def _finish(
    workspace: Path,
    *,
    trial_id: str = "t",
    final_judgment: Judgment | None = None,
    override: Override | None = None,
    combined_concerns: bool | None = None,
    limitations: tuple[str, ...] = (),
    actor: str = "finisher",
    observed_at: datetime = OBSERVED,
):
    return finish_trial(
        workspace,
        trial_id,
        final_judgment,
        override,
        combined_concerns,
        limitations,
        actor,
        observed_at,
    )


def _completed_workspace(tmp_path: Path) -> tuple[Path, Source]:
    workspace, source = approved_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        _save(workspace, source, domain.id)
    return workspace, source


def test_finish_requires_all_domains_and_never_writes_partial_snapshot(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    _save(workspace, source)
    result = _finish(workspace)
    assert isinstance(result, FinishCondition)
    assert result.code == "domains_incomplete"
    with transaction(workspace) as connection:
        assert (
            connection.execute(
                "SELECT name FROM records WHERE name LIKE 'assessment_snapshot:%'"
            ).fetchall()
            == []
        )
        assert (
            connection.execute(
                "SELECT name FROM records WHERE name LIKE 'terminal_trial:%'"
            ).fetchall()
            == []
        )


def test_finish_snapshot_is_canonical_atomic_idempotent_and_conflict_safe(tmp_path: Path) -> None:
    workspace, _ = _completed_workspace(tmp_path)
    first = _finish(workspace)
    assert isinstance(first, FinishSaved)
    assert first.next_action == "finalize_batch"
    assert first.snapshot.snapshot_hash == sha256(snapshot_content(first.snapshot))
    key = f"assessment_snapshot:{first.snapshot.approved_batch_hash}:t"
    with transaction(workspace) as connection:
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        terminal = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (f"terminal_trial:{first.snapshot.approved_batch_hash}:t",),
        ).fetchone()
    assert row is not None and bytes(row[0]) == canonical_json_bytes(first.snapshot)
    assert terminal is not None
    assert isinstance(_finish(workspace), FinishSaved)
    assert isinstance(_finish(workspace, limitations=("changed",)), FinishConflict)


def test_finish_freezes_latest_active_revision_and_rejects_post_terminal_save(
    tmp_path: Path,
) -> None:
    workspace, source = approved_workspace(tmp_path)
    first = _save(workspace, source, "domain:randomization")
    corrected = _save(
        workspace,
        source,
        "domain:randomization",
        limitations=("Clarified after reviewing the protocol.",),
        expected_previous_hash=first.judgment.checkpoint_hash,
    )
    for domain in SCIENTIFIC_PACK.domains[1:]:
        _save(workspace, source, domain.id)
    frozen = _finish(workspace)
    assert isinstance(frozen, FinishSaved)
    assert (
        next(
            item
            for item in frozen.snapshot.domain_judgments
            if item.domain_id == "domain:randomization"
        )
        == corrected.judgment
    )
    rejected = _save(
        workspace,
        source,
        "domain:randomization",
        expected_previous_hash=corrected.judgment.checkpoint_hash,
    )
    assert rejected.status == "condition" and rejected.code == "trial_terminal"


def test_correction_and_finish_are_serializable(tmp_path: Path) -> None:
    workspace, source = _completed_workspace(tmp_path)
    from rob2_kit.recovery import recovery_progress

    active = recovery_progress(workspace).trials[0].active_domain_checkpoints[0]
    start = Barrier(2)
    results: list[FinishSaved | object] = []

    def correct() -> None:
        start.wait()
        results.append(
            _save(
                workspace,
                source,
                "domain:randomization",
                limitations=("Concurrent correction.",),
                expected_previous_hash=active.active_hash,
            )
        )

    def finish() -> None:
        start.wait()
        results.append(_finish(workspace))

    threads = [Thread(target=correct), Thread(target=finish)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    finished = next(result for result in results if isinstance(result, FinishSaved))
    terminal_save = next(result for result in results if not isinstance(result, FinishSaved))
    assert hasattr(terminal_save, "status")
    assert terminal_save.status in {"revised", "condition"}
    randomization = next(
        item
        for item in finished.snapshot.domain_judgments
        if item.domain_id == "domain:randomization"
    )
    if terminal_save.status == "revised":
        assert isinstance(terminal_save, JudgmentRevised)
        assert randomization.checkpoint_hash == terminal_save.judgment.checkpoint_hash
    else:
        assert randomization.checkpoint_hash == active.active_hash


def test_finish_rejects_tampered_checkpoint_and_snapshot(tmp_path: Path) -> None:
    workspace, _ = _completed_workspace(tmp_path)
    with transaction(workspace) as connection:
        row = connection.execute(
            "SELECT name,payload FROM records WHERE name LIKE 'domain_judgment:%' LIMIT 1"
        ).fetchone()
        assert row is not None
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?",
            (bytes(row[1]).replace(b'"actor":"reviewer"', b'"actor":"attacker"'), row[0]),
        )
    with pytest.raises(ValueError, match="integrity"):
        _finish(workspace)


def test_finish_rejects_active_payloads_swapped_between_domain_keys(tmp_path: Path) -> None:
    workspace, source = _completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    randomization = f"domain_judgment:{approved.frozen_hash}:t:r:domain:randomization"
    deviations = f"domain_judgment:{approved.frozen_hash}:t:r:domain:deviations"
    with transaction(workspace) as connection:
        left = connection.execute(
            "SELECT payload FROM records WHERE name=?", (randomization,)
        ).fetchone()
        right = connection.execute(
            "SELECT payload FROM records WHERE name=?", (deviations,)
        ).fetchone()
        assert left is not None and right is not None
        connection.execute("UPDATE records SET payload=? WHERE name=?", (right[0], randomization))
        connection.execute("UPDATE records SET payload=? WHERE name=?", (left[0], deviations))
    from rob2_kit.recovery import recovery_progress

    assert recovery_progress(workspace).status == "stale"
    condition = _save(workspace, source, expected_previous_hash="sha256:" + "0" * 64)
    assert condition.status == "condition" and condition.code == "revision_history_corrupt"
    with pytest.raises(ValueError, match="revision|identity"):
        _finish(workspace)
    with transaction(workspace) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM records WHERE name=?", (f"terminal_trial:{approved.frozen_hash}:t",)
            ).fetchone()
            is None
        )


def test_finish_overall_override_and_combined_concerns_contract(tmp_path: Path) -> None:
    workspace, _ = _completed_workspace(tmp_path)
    with pytest.raises(ValueError, match="override"):
        _finish(workspace, final_judgment=Judgment.HIGH)
    result = _finish(
        workspace,
        final_judgment=Judgment.HIGH,
        override=Override(justification="review", actor="finisher", observed_at=OBSERVED),
    )
    assert isinstance(result, FinishSaved)
    assert result.snapshot.final_judgment is Judgment.HIGH


def test_finish_trial_mcp_schema_is_typed() -> None:
    async def schema() -> dict[str, Any]:
        async with Client(mcp) as client:
            tools = await client.list_tools()
        return dict(next(tool for tool in tools if tool.name == "finish_trial").inputSchema)

    value = asyncio.run(schema())
    assert value["required"] == ["request"]
    request = value["properties"]["request"]
    assert {variant["properties"]["mode"].get("const") for variant in request["oneOf"]} == {
        "assessment",
        "needs_input",
        "failed",
    }
