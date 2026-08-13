import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from test_judgments import _save, approved_workspace

from rob2_kit.finish import (
    FinishCondition,
    FinishConflict,
    FinishSaved,
    finish_trial,
    snapshot_content,
)
from rob2_kit.judgment_models import Override
from rob2_kit.models import Judgment, canonical_json_bytes, sha256
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.server import mcp
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


def _completed_workspace(tmp_path: Path) -> tuple[Path, object]:
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
