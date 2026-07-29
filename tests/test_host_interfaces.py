import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typer.testing import CliRunner

from rob2_kit.application.gateway import STATIC_TOOL_NAMES, ApplicationGateway
from rob2_kit.interfaces.cli.app import app
from rob2_kit.interfaces.mcp.server import registered_tool_names
from rob2_kit.release import build_host_adapters, verify_host_adapters
from rob2_kit.storage.artifacts import ArtifactStore
from rob2_kit.storage.ledger import (
    Transition,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)
from tests.test_review_service import case, reviewer


def test_initialization_is_host_neutral_and_issues_bounded_identifiers(
    tmp_path: Path,
) -> None:
    direct = ApplicationGateway().initialize_project(tmp_path, authorized=True)
    result = CliRunner().invoke(app, ["init", str(tmp_path), "--authorize", "--json"])

    assert result.exit_code == 0
    cli = json.loads(result.stdout)
    assert cli == direct.model_dump(mode="json")
    assert cli["status"] == "work_required"
    assert cli["committed"] is True
    assert cli["payload"]["project_id"].startswith("project:")
    assert cli["payload"]["work_item"]["work_item_id"].startswith("work-item:")


def test_static_mcp_surface_matches_specification() -> None:
    assert registered_tool_names() == STATIC_TOOL_NAMES


def test_real_stdio_mcp_matches_application_initialization(tmp_path: Path) -> None:
    direct_root = tmp_path / "direct"
    mcp_root = tmp_path / "mcp"
    direct = ApplicationGateway().initialize_project(direct_root, authorized=True)

    async def invoke() -> dict[str, object]:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "rob2_kit.interfaces.mcp.server"],
            cwd=Path.cwd(),
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "initialize_project",
                    {"project_root": str(mcp_root), "authorized": True},
                )
                assert result.structured_content is not None
                return result.structured_content

    through_mcp = anyio.run(invoke)

    assert through_mcp["status"] == direct.status
    assert through_mcp["ledger_cursor"] == direct.ledger_cursor
    assert through_mcp["committed"] == direct.committed
    assert len(ApplicationGateway().resume_project(mcp_root)) > 0


def test_fresh_process_can_resume_and_status_is_ledger_derived(tmp_path: Path) -> None:
    initialized = ApplicationGateway().initialize_project(tmp_path, authorized=True)
    fresh = ApplicationGateway()
    project_id = fresh.resume_project(tmp_path)

    status = fresh.call("project_status", project_id)

    assert project_id == initialized.payload["project_id"]
    assert status.status == "work_required"
    assert status.payload == {"event_count": 1}


def test_restarted_mcp_gateway_resolves_engine_issued_project_id(tmp_path: Path) -> None:
    initialized = ApplicationGateway().initialize_project(tmp_path, authorized=True)

    status = ApplicationGateway().call(
        "project_status", initialized.payload["project_id"]
    )

    assert status.status == "work_required"


def test_source_reads_use_persisted_ingestion_output(tmp_path: Path) -> None:
    (tmp_path / "input" / "Trial A").mkdir(parents=True)
    gateway = ApplicationGateway()
    initialized = gateway.initialize_project(tmp_path, authorized=True)

    sources = gateway.call(
        "list_sources",
        initialized.payload["project_id"],
        arguments={"trial_id": "trial:trial-a"},
    )

    assert sources.status == "completed"
    assert sources.payload["sources"][0]["availability"] == "unavailable"


def test_review_queue_reconstructs_the_durable_review_service(tmp_path: Path) -> None:
    gateway = ApplicationGateway()
    initialized = gateway.initialize_project(tmp_path, authorized=True)
    ledger = WorkflowLedger(
        tmp_path / ".rob2" / "ledger.sqlite3",
        ArtifactStore(tmp_path / ".rob2" / "artifacts"),
    )
    now = datetime.now(UTC)
    lease = ledger.acquire_lease(
        "owner:preparation",
        now,
        timedelta(minutes=1),
        owner_is_dead=lambda _owner: True,
    )
    ledger.commit(
        Transition(
            scope="preparation:trial-1",
            operation="preparation:complete",
            operation_key="idempotency:preparation-complete",
            actor=reviewer(),
            observed_at=now,
            entity_id="preparation-attempt:trial-1",
            revision_id="revision:preparation-trial-1",
            artifact=b'{"outcome":"draft_ready"}',
            artifact_media_type="application/json",
            expected_dependency_fingerprint=dependency_fingerprint(()),
            checkpoint="checkpoint:preparation-outcome",
            outcome=WorkflowEventOutcome.PREPARATION_OUTCOME_REACHED,
        ),
        lease,
        now=now,
    )
    gateway.register_review_case(tmp_path, case())

    result = ApplicationGateway().call(
        "review_queue", initialized.payload["project_id"]
    )

    assert result.status == "completed"
    assert any(item["action_id"] == "review-action:finding-1" for item in result.payload["queue"])


def test_mutation_rejects_non_engine_work_item_and_is_idempotent(tmp_path: Path) -> None:
    gateway = ApplicationGateway()
    initialized = gateway.initialize_project(tmp_path, authorized=True)
    work_item = initialized.payload["work_item"]
    context = {
        "idempotency_key": "idempotency:one",
        "work_item_id": work_item["work_item_id"],
        "contract_version": initialized.payload["contract_version"],
        "expected_dependency_fingerprint": work_item["dependency_fingerprint"],
    }

    first = gateway.call(
        "submit_source_classification",
        initialized.payload["project_id"],
        arguments={
            "source_id": "source:primary",
            "roles": ["source-role:primary-report"],
        },
        mutation_context=context,
    )
    repeated = gateway.call(
        "submit_source_classification",
        initialized.payload["project_id"],
        arguments={
            "source_id": "source:primary",
            "roles": ["source-role:primary-report"],
        },
        mutation_context=context,
    )

    assert repeated == first
    assert first.committed is True
    assert first.ledger_cursor == "ledger:2"


def test_generated_adapters_share_canonical_skill_and_exact_launcher(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "skills" / "rob2-assess" / "SKILL.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("---\nname: rob2-assess\n---\nUse bounded tools.\n", encoding="utf-8")

    manifest = build_host_adapters(tmp_path, package_version="0.1.0")

    expected_hash = "sha256:" + hashlib.sha256(canonical.read_bytes()).hexdigest()
    assert manifest.canonical_skill_hash == expected_hash
    assert manifest.launcher == "uvx --python 3.13 --from rob2-kit==0.1.0 rob2-mcp"
    assert (tmp_path / "adapters" / "codex" / "SKILL.md").read_bytes() == canonical.read_bytes()
    assert (tmp_path / "adapters" / "claude" / "SKILL.md").read_bytes() == canonical.read_bytes()
    codex = json.loads((tmp_path / "adapters" / "codex" / "adapter.json").read_text())
    claude = json.loads((tmp_path / "adapters" / "claude" / "adapter.json").read_text())
    assert codex["skill_hash"] == claude["skill_hash"] == expected_hash
    assert codex["trigger_description"] == claude["trigger_description"]
    assert (tmp_path / "adapters" / "codex" / "activation-fixtures.json").read_bytes() == (
        tmp_path / "adapters" / "claude" / "activation-fixtures.json"
    ).read_bytes()
    verify_host_adapters(tmp_path)
