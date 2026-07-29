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
from rob2_kit.domain.assessment import (
    AlgorithmicJudgmentRevision,
    AssessmentRevision,
    AssessmentSignOff,
    DecisionTrace,
    JudgmentOverride,
    ReviewerProfileRevision,
)
from rob2_kit.domain.releases import PolicyRelease
from rob2_kit.domain.results import Comparison, Estimate, Result, ResultSpecRevision
from rob2_kit.domain.revisions import Dependency, RecordReference
from rob2_kit.domain.sources import SourceInventoryRevision
from rob2_kit.interfaces.cli.app import app
from rob2_kit.interfaces.mcp.server import registered_tool_names
from rob2_kit.release import build_host_adapters, verify_host_adapters
from rob2_kit.storage.artifacts import ArtifactStore
from rob2_kit.storage.ledger import (
    DependencyInput,
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


def test_cli_report_export_archive_and_offline_verify(tmp_path: Path) -> None:
    gateway = ApplicationGateway()
    gateway.initialize_project(tmp_path, authorized=True)
    ledger = WorkflowLedger(
        tmp_path / ".rob2" / "ledger.sqlite3",
        ArtifactStore(tmp_path / ".rob2" / "artifacts"),
    )
    now = datetime.now(UTC)
    lease = ledger.acquire_lease(
        "owner:report-test",
        now,
        timedelta(minutes=1),
        owner_is_dead=lambda _owner: True,
    )
    def commit(record: object, dependencies: tuple[DependencyInput, ...] = ()) -> str:
        revision_id = getattr(record, "revision_id")
        committed = ledger.commit(
            Transition(
                scope="assessment:cli",
                operation="operation:freeze-record",
                operation_key=f"idempotency:{revision_id.removeprefix('revision:')}",
                actor=reviewer(),
                observed_at=now,
                entity_id=getattr(record, "entity_id"),
                revision_id=revision_id,
                artifact=getattr(record, "model_dump_json")().encode(),
                artifact_media_type="application/json",
                dependencies=dependencies,
                expected_dependency_fingerprint=dependency_fingerprint(dependencies),
                checkpoint="checkpoint:assessment",
                outcome=WorkflowEventOutcome.REVIEW_PENDING,
            ),
            lease,
            now=now,
        )
        return committed.artifact_hash

    common = {"actor": reviewer(), "observed_at": now}
    result_spec = ResultSpecRevision(
        entity_id="result-spec:cli",
        revision_id="revision:result-spec-cli",
        result=Result(
            result_id="result:cli",
            trial_id="trial:cli",
            randomization_id="randomization:cli",
            comparison=Comparison(
                experimental_arm_id="arm:treatment",
                comparator_arm_id="arm:control",
            ),
            effect_of_interest="assignment",
            outcome_construct="Mortality",
            measurement_instrument="Vital status",
            time_point="30 days",
            analysis_population="Intention to treat",
            analysis_model="Risk ratio",
            effect_measure="RR",
            source_locator="source:cli#result",
        ),
        estimate=Estimate(value="0.8"),
        provenance_note="Test fixture",
        **common,
    )
    result_hash = commit(result_spec)
    result_reference = RecordReference(
        entity_id=result_spec.entity_id,
        revision_id=result_spec.revision_id,
        content_hash=result_hash,
    )
    source_dependency = Dependency(
        **result_reference.model_dump(),
        role="dependency:result-spec",
    )
    source_inventory = SourceInventoryRevision(
        entity_id="source-inventory:cli",
        revision_id="revision:source-inventory-cli",
        dependencies=(source_dependency,),
        result_spec=result_reference,
        sources=(),
        **common,
    )
    source_hash = commit(
        source_inventory,
        (DependencyInput.model_validate(source_dependency.model_dump()),),
    )
    trace = DecisionTrace(
        entity_id="decision-trace:cli",
        revision_id="revision:decision-trace-cli",
        active_question_ids=("sq:1.1",),
        inactive_question_ids=(),
        matched_rule_ids=("rule:low",),
        resulting_judgment="low",
        **common,
    )
    trace_hash = commit(trace)
    trace_reference = RecordReference(
        entity_id=trace.entity_id,
        revision_id=trace.revision_id,
        content_hash=trace_hash,
    )
    trace_dependency = Dependency(
        **trace_reference.model_dump(),
        role="dependency:decision-trace",
    )
    judgment = AlgorithmicJudgmentRevision(
        entity_id="judgment:cli-domain-1",
        revision_id="revision:judgment-cli-domain-1",
        dependencies=(trace_dependency,),
        domain_id="domain:1",
        judgment="low",
        answer_revisions=(),
        decision_trace=trace_reference,
        **common,
    )
    judgment_hash = commit(
        judgment,
        (DependencyInput.model_validate(trace_dependency.model_dump()),),
    )
    policy = PolicyRelease(
        entity_id="policy-release:cli",
        revision_id="revision:policy-cli",
        kind="review_policy",
        family_id="policy:review",
        release_id="1.0.0",
        canonical_content_hash="sha256:" + ("b" * 64),
        required_schema_version="1.0.0",
        inventory=(),
        **common,
    )
    policy_hash = commit(policy)
    policy_reference = RecordReference(
        entity_id=policy.entity_id,
        revision_id=policy.revision_id,
        content_hash=policy_hash,
    )
    judgment_reference = RecordReference(
        entity_id=judgment.entity_id,
        revision_id=judgment.revision_id,
        content_hash=judgment_hash,
    )
    override_dependencies = (
        Dependency(
            **judgment_reference.model_dump(),
            role="dependency:algorithmic-judgment",
        ),
        Dependency(
            **policy_reference.model_dump(), role="dependency:review-policy"
        ),
    )
    override = JudgmentOverride(
        entity_id="judgment-override:cli",
        revision_id="revision:judgment-override-cli",
        dependencies=override_dependencies,
        judgment_revision=judgment_reference,
        replacement="high",
        rationale="Reviewer identified a material concern.",
        policy_authority=policy_reference,
        **common,
    )
    override_hash = commit(
        override,
        tuple(
            DependencyInput.model_validate(dependency.model_dump())
            for dependency in override_dependencies
        ),
    )
    source_reference = RecordReference(
        entity_id=source_inventory.entity_id,
        revision_id=source_inventory.revision_id,
        content_hash=source_hash,
    )
    override_reference = RecordReference(
        entity_id=override.entity_id,
        revision_id=override.revision_id,
        content_hash=override_hash,
    )
    assessment_dependencies = (
        Dependency(
            **result_reference.model_dump(), role="dependency:result-spec"
        ),
        Dependency(
            **source_reference.model_dump(), role="dependency:source-inventory"
        ),
        Dependency(
            **judgment_reference.model_dump(),
            role="dependency:algorithmic-judgment",
        ),
        Dependency(
            **override_reference.model_dump(),
            role="dependency:judgment-override",
        ),
    )
    assessment = AssessmentRevision(
        entity_id="assessment:cli",
        revision_id="revision:assessment-cli",
        dependencies=assessment_dependencies,
        result_spec=result_reference,
        source_inventory=source_reference,
        evidence_bundles=(),
        answers=(),
        judgments=(judgment_reference,),
        judgment_overrides=(override_reference,),
        review_findings=(),
        **common,
    )
    assessment_hash = commit(
        assessment,
        tuple(
            DependencyInput.model_validate(dependency.model_dump())
            for dependency in assessment_dependencies
        ),
    )
    reviewer_profile = ReviewerProfileRevision(
        entity_id="reviewer-profile:cli",
        revision_id="revision:reviewer-profile-cli",
        display_name="Test reviewer",
        **common,
    )
    reviewer_hash = commit(reviewer_profile)
    reviewer_reference = RecordReference(
        entity_id=reviewer_profile.entity_id,
        revision_id=reviewer_profile.revision_id,
        content_hash=reviewer_hash,
    )
    assessment_reference = RecordReference(
        entity_id=assessment.entity_id,
        revision_id=assessment.revision_id,
        content_hash=assessment_hash,
    )
    sign_off_dependencies = (
        Dependency(
            **assessment_reference.model_dump(),
            role="dependency:assessment",
        ),
        Dependency(
            **reviewer_reference.model_dump(),
            role="dependency:reviewer-profile",
        ),
    )
    sign_off = AssessmentSignOff(
        entity_id="assessment-sign-off:cli",
        revision_id="revision:assessment-sign-off-cli",
        dependencies=sign_off_dependencies,
        assessment=assessment_reference,
        reviewer_profile=reviewer_reference,
        **common,
    )
    commit(
        sign_off,
        tuple(
            DependencyInput.model_validate(dependency.model_dump())
            for dependency in sign_off_dependencies
        ),
    )

    report = CliRunner().invoke(app, ["report", str(tmp_path)])
    export = CliRunner().invoke(app, ["export", str(tmp_path)])
    archive = CliRunner().invoke(
        app,
        ["archive", str(tmp_path), "--kind", "reference"],
    )
    archive_path = tmp_path / "output" / "revision_assessment-cli.reference.rob2.zip"
    verified = CliRunner().invoke(app, ["verify", str(archive_path)])

    assert report.exit_code == export.exit_code == archive.exit_code == verified.exit_code == 0
    assert (tmp_path / "output" / "revision_assessment-cli.html").exists()
    assert (tmp_path / "output" / "revision_assessment-cli.md").exists()
    assert (tmp_path / "output" / "revision_assessment-cli.json").exists()
    assert (tmp_path / "output" / "revision_assessment-cli.robvis.csv").exists()
    assert (tmp_path / "output" / "revision_assessment-cli.xlsx").exists()
    assert archive_path.exists()
    assert "High" in (
        tmp_path / "output" / "revision_assessment-cli.robvis.csv"
    ).read_text(encoding="utf-8-sig")
    assert "Signed off" in (
        tmp_path / "output" / "revision_assessment-cli.html"
    ).read_text()
    assert json.loads(verified.stdout)["message"] == (
        "source integrity not independently verifiable"
    )
