import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest
import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typer.testing import CliRunner

from rob2_kit.application.contracts import RUN_OPERATION_NAMES
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
from rob2_kit.review.workspace import project_workspace
from rob2_kit.storage.artifacts import ArtifactStore
from rob2_kit.storage.ledger import (
    DependencyInput,
    Transition,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)
from tests.test_ingestion import StubParser, page
from tests.test_review_service import case, reviewer
from tests.test_visual_inspection import candidate


def result_resolution_submission() -> dict[str, object]:
    return {
        "result": {
            "result_id": "result:trial-a",
            "trial_id": "trial:trial-a",
            "randomization_id": "randomization:trial-a",
            "comparison": {
                "experimental_arm_id": "arm:treatment",
                "comparator_arm_id": "arm:control",
            },
            "effect_of_interest": "assignment",
            "outcome_construct": "Mortality",
            "measurement_instrument": "Vital status",
            "time_point": "30 days",
            "analysis_population": "Intention to treat",
            "analysis_model": "Risk ratio",
            "effect_measure": "RR",
            "source_locator": "source:trial-a-1#result",
        },
        "estimate": {"value": "0.8"},
        "provenance_note": "Resolved from the primary report.",
    }


def low_risk_sq_answers() -> dict[str, object]:
    values = {
        "sq:randomization:sequence": "yes",
        "sq:randomization:concealment": "yes",
        "sq:randomization:baseline-imbalance": "no",
        "sq:deviations:participants-aware": "no",
        "sq:deviations:personnel-aware": "no",
        "sq:deviations:appropriate-analysis": "yes",
        "sq:missing:data-available": "yes",
        "sq:measurement:method-inappropriate": "no",
        "sq:measurement:differential": "no",
        "sq:measurement:assessor-aware": "no",
        "sq:selection:prespecified-analysis": "yes",
        "sq:selection:multiple-measurements": "no",
        "sq:selection:multiple-analyses": "no",
    }
    return {
        "answers": [
            {
                "question_id": question_id,
                "answer": answer,
                "rationale": "Supported by the frozen evidence bundle.",
            }
            for question_id, answer in values.items()
        ]
    }


def blank_pdf() -> bytes:
    stream = b"BT /F1 12 Tf 10 36 Td (Trial report) Tj ET"
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        (
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + content + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    return bytes(data)


def test_initialization_is_host_neutral_and_issues_bounded_identifiers(
    tmp_path: Path,
) -> None:
    with pytest.raises(PermissionError, match="authorization"):
        ApplicationGateway().initialize_project(tmp_path, authorized=False)
    assert not (tmp_path / ".rob2").exists()
    direct = ApplicationGateway().initialize_project(tmp_path, authorized=True)
    result = CliRunner().invoke(app, ["init", str(tmp_path), "--json"])

    assert result.exit_code == 0
    cli = json.loads(result.stdout)
    assert cli == direct.model_dump(mode="json")
    assert cli["status"] == "trial_problem"
    assert cli["committed"] is True
    assert cli["payload"]["project_id"].startswith("project:")
    assert cli["payload"]["work_item"] is None


def test_static_mcp_surface_matches_specification() -> None:
    assert registered_tool_names() == STATIC_TOOL_NAMES


def test_real_stdio_mcp_exercises_the_typed_run_engine_surface(tmp_path: Path) -> None:
    host_roots = {
        "codex": tmp_path / "codex",
        "claude": tmp_path / "claude",
    }
    for root in host_roots.values():
        (root / "input" / "trial-a").mkdir(parents=True)
        (root / "input" / "trial-a" / "report.pdf").write_bytes(blank_pdf())

    async def invoke(host: str) -> tuple[dict[str, object], dict[str, object]]:
        descriptor = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "adapters"
                / host
                / "adapter.json"
            ).read_text()
        )
        assert descriptor["integration"] == "mcp"
        assert descriptor["launcher"].endswith("rob2-mcp")
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "rob2_kit.interfaces.mcp.server"],
            cwd=Path.cwd(),
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = tuple(item.name for item in tools.tools)
                assert names == RUN_OPERATION_NAMES
                assert "initialize_project" not in names
                mutation = next(
                    item
                    for item in tools.tools
                    if item.name == "submit_source_classification"
                )
                assert "contract_version" in mutation.input_schema["required"]
                assert "mutation_context" not in mutation.input_schema["properties"]
                result = await session.call_tool(
                    "prepare_run",
                    {"project_root": str(host_roots[host]), "authorized": True},
                )
                assert result.structured_content is not None
                prepared = result.structured_content
                proposal = prepared["proposal"]
                submitted = await session.call_tool(
                    "submit_run_proposal",
                    {
                        "run_id": prepared["run_id"],
                        "proposal_token": proposal["proposal_token"],
                        "idempotency_key": "idempotency:typed-proposal",
                        "contract_version": "1.0.0",
                    },
                )
                assert submitted.structured_content is not None
                confirmed = await session.call_tool(
                    "confirm_run_definition",
                    {
                        "run_id": prepared["run_id"],
                        "proposal_token": submitted.structured_content["proposal"][
                            "proposal_token"
                        ],
                        "idempotency_key": "idempotency:typed-confirm",
                        "confirmed_by": {
                            "kind": "human",
                            "actor_id": f"actor:{host}",
                            "display_name": host,
                        },
                        "contract_version": "1.0.0",
                    },
                )
                assert confirmed.structured_content is not None
                work = await session.call_tool(
                    "continue_run", {"run_id": prepared["run_id"]}
                )
                assert work.structured_content is not None
                mutation_result = await session.call_tool(
                    "submit_source_classification",
                    {
                        "run_id": prepared["run_id"],
                        "work_token": work.structured_content["work_item"]["work_token"],
                        "idempotency_key": "idempotency:typed-source",
                        "classifications": [
                            {"source_id": "source:trial-a-1", "roles": ["primary_report"]}
                        ],
                        "contract_version": "1.0.0",
                    },
                )
                assert mutation_result.structured_content is not None
                return prepared, mutation_result.structured_content

    codex_init, codex_mutation = anyio.run(invoke, "codex")
    claude_init, claude_mutation = anyio.run(invoke, "claude")

    for initialization, mutation in (
        (codex_init, codex_mutation),
        (claude_init, claude_mutation),
    ):
        assert initialization["condition"] == "confirmation_required"
        assert initialization["committed"] is True
        assert mutation["condition"] == "accepted"
        assert mutation["committed"] is True


def test_fresh_process_can_resume_and_status_is_ledger_derived(tmp_path: Path) -> None:
    initialized = ApplicationGateway().initialize_project(tmp_path, authorized=True)
    fresh = ApplicationGateway()
    project_id = fresh.resume_project(tmp_path)

    status = fresh.call("project_status", project_id)

    assert project_id == initialized.payload["project_id"]
    assert status.status == "trial_problem"
    assert status.payload == {"event_count": 1}


def test_restarted_mcp_gateway_resolves_engine_issued_project_id(tmp_path: Path) -> None:
    initialized = ApplicationGateway().initialize_project(tmp_path, authorized=True)

    status = ApplicationGateway().call(
        "project_status", initialized.payload["project_id"]
    )

    assert status.status == "trial_problem"


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
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    gateway = ApplicationGateway(
        parser=StubParser({"report": (page(1, "Trial report"),)})
    )
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
            "classifications": [
                {
                    "source_id": "source:trial-a-1",
                    "roles": ["primary_report"],
                }
            ],
        },
        mutation_context=context,
    )
    repeated = gateway.call(
        "submit_source_classification",
        initialized.payload["project_id"],
        arguments={
            "classifications": [
                {
                    "source_id": "source:trial-a-1",
                    "roles": ["primary_report"],
                }
            ],
        },
        mutation_context=context,
    )
    with pytest.raises(ValueError, match="different payload"):
        gateway.call(
            "submit_source_classification",
            initialized.payload["project_id"],
            arguments={
                "classifications": [
                    {
                        "source_id": "source:trial-a-1",
                        "roles": ["secondary_report"],
                    }
                ],
            },
            mutation_context=context,
        )

    assert repeated == first
    assert first.committed is True
    assert first.ledger_cursor == "ledger:2"


def test_preparation_work_items_enforce_order_and_reach_review(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    gateway = ApplicationGateway(
        parser=StubParser({"report": (page(1, "Trial report"),)})
    )
    initialized = gateway.initialize_project(tmp_path, authorized=True)
    project_id = initialized.payload["project_id"]
    search = gateway.call(
        "search_evidence",
        project_id,
        arguments={"query": {"terms": ["trial"]}},
    )
    unit_id = search.payload["hits"][0]["unit"]["unit_id"]
    candidate_id = search.payload["hits"][0]["candidate_id"]
    context = gateway.call(
        "read_evidence_context",
        project_id,
        arguments={"unit_id": unit_id},
    )
    visual = candidate("analysis-population")
    visual_data = visual.model_dump(mode="json")
    visual_data.pop("candidate_id")
    visual_data["source_id"] = search.payload["hits"][0]["unit"]["source_id"]
    visual_data["source_artifact_hash"] = search.payload["hits"][0]["unit"][
        "source_artifact_hash"
    ]
    submissions = (
        (
            "submit_source_classification",
            {
                "classifications": [
                    {
                        "source_id": "source:trial-a-1",
                        "roles": ["primary_report"],
                    }
                ]
            },
        ),
        ("submit_result_resolution", result_resolution_submission()),
        (
            "submit_evidence_dispositions",
            {
                "dispositions": [
                    {"candidate_id": candidate_id, "kind": "immaterial"}
                ],
                "visual_candidates": [visual_data],
            },
        ),
        (
            "submit_visual_transcription",
            {"transcription": {"text": "42 participants"}},
        ),
        (
            "freeze_evidence_bundle",
            {"items": [], "frozen_content_hash": "sha256:" + ("a" * 64)},
        ),
        ("submit_sq_answers", low_risk_sq_answers()),
    )

    for index, (tool_name, arguments) in enumerate(submissions):
        next_work = gateway.call("get_next_work", project_id)
        work_item = next_work.payload["work_item"]
        assert work_item["permitted_tool"] == tool_name
        if tool_name == "submit_sq_answers":
            assert work_item["sq_context"][0]["sq_id"].startswith("sq:")
            assert work_item["sq_context"][0]["guidance"]
            invalid_answers = low_risk_sq_answers()
            invalid_answers["answers"].append(
                {
                    "question_id": "sq:deviations:affected-outcome",
                    "answer": "yes",
                    "rationale": "This question is inactive for the preceding answers.",
                }
            )
            with pytest.raises(
                ValueError,
                match="answers supplied for not_applicable questions",
            ):
                gateway.call(
                    tool_name,
                    project_id,
                    arguments=invalid_answers,
                    mutation_context={
                        "idempotency_key": "idempotency:invalid-sq-answers",
                        "work_item_id": work_item["work_item_id"],
                        "contract_version": "1.0.0",
                        "expected_dependency_fingerprint": work_item[
                            "dependency_fingerprint"
                        ],
                    },
                )
            assert gateway.call(
                "get_next_work", project_id
            ).payload["work_item"] == work_item
        if tool_name == "submit_visual_transcription":
            visual_page = gateway.call("inspect_visual_candidate", project_id)
            arguments["transcription"]["candidate_id"] = visual_page.payload[
                "candidates"
            ][0]["candidate_id"]
        if index == 0:
            with pytest.raises(ValueError, match="not permitted"):
                gateway.call(
                    "submit_result_resolution",
                    project_id,
                    arguments=result_resolution_submission(),
                    mutation_context={
                        "idempotency_key": "idempotency:wrong-order",
                        "work_item_id": work_item["work_item_id"],
                        "contract_version": "1.0.0",
                        "expected_dependency_fingerprint": work_item[
                            "dependency_fingerprint"
                        ],
                    },
                )
        gateway.call(
            tool_name,
            project_id,
            arguments=arguments,
            mutation_context={
                "idempotency_key": f"idempotency:step-{index}",
                "work_item_id": work_item["work_item_id"],
                "contract_version": "1.0.0",
                "expected_dependency_fingerprint": work_item[
                    "dependency_fingerprint"
                ],
            },
        )

    completed = gateway.call("continue_preparation", project_id)
    queue = ApplicationGateway().call("review_queue", project_id)
    pending = ApplicationGateway().call(
        "wait_for_review",
        project_id,
        arguments={"inactivity_timeout_seconds": 0},
    )
    resumed_pending = ApplicationGateway().call(
        "wait_for_review",
        project_id,
        arguments={"inactivity_timeout_seconds": 0},
    )
    visual_page = ApplicationGateway().call(
        "inspect_visual_candidate", project_id
    )
    durable_status = ApplicationGateway().call("project_status", project_id)
    assessment_event = next(
        event
        for event in ledger_for(tmp_path).events()
        if event.operation == "operation:derive-assessment-record"
    )
    assessment = AssessmentRevision.model_validate_json(
        ledger_for(tmp_path).artifacts.read(
            assessment_event.output_revision_hashes[0]
        )
    )

    assert context.payload["unit"]["text"] == "Trial report"
    assert completed.status == "preparation_outcome_reached"
    assert completed.payload["batch_status"] == {"preparation:trial-a": "draft_ready"}
    assert len(queue.payload["queue"]) == 5
    assert pending.status == resumed_pending.status == "review_pending"
    assert durable_status.status == "review_pending"
    assert pending.ledger_cursor == resumed_pending.ledger_cursor == "ledger:21"
    assert len(assessment.judgments) == 5
    workspace = project_workspace(
        ledger_for(tmp_path),
        connection_state="not connected—review saved",
    )
    assert workspace is not None
    assert workspace.results[0].judgment == "Overall judgment: Low"
    assert visual_page.payload["candidates"][0]["candidate_id"].startswith("visual:")
    assert visual_page.payload["render_requests"][0]["dpi"] == 144


def test_declared_result_skips_resolution_and_uses_result_scoped_preparation(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    declared = result_resolution_submission()
    declared["result"]["result_id"] = "result:trial-a-mortality-30d"
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "results": [declared],
            }
        ),
        encoding="utf-8",
    )
    gateway = ApplicationGateway(
        parser=StubParser({"report": (page(1, "Trial report"),)})
    )
    initialized = gateway.initialize_project(tmp_path, authorized=True)
    project_id = initialized.payload["project_id"]
    first_work = initialized.payload["work_item"]

    assert first_work["result_id"] == "result:trial-a-mortality-30d"
    assert first_work["scope"] == "preparation:trial-a-mortality-30d"
    assert first_work["permitted_tool"] == "submit_source_classification"

    gateway.call(
        "submit_source_classification",
        project_id,
        arguments={
            "classifications": [
                {"source_id": "source:trial-a-1", "roles": ["primary_report"]}
            ]
        },
        mutation_context={
            "idempotency_key": "idempotency:declared-classification",
            "work_item_id": first_work["work_item_id"],
            "contract_version": "1.0.0",
            "expected_dependency_fingerprint": first_work["dependency_fingerprint"],
        },
    )
    next_work = gateway.call("continue_preparation", project_id).payload["work_item"]

    assert next_work["permitted_tool"] == "submit_evidence_dispositions"
    assert next_work["issued_identifiers"] == {}


def test_declared_result_for_failed_trial_remains_terminal_without_a_plan(
    tmp_path: Path,
) -> None:
    (tmp_path / "input" / "trial-a").mkdir(parents=True)
    declared = result_resolution_submission()
    declared["result"]["result_id"] = "result:trial-a-mortality-30d"
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "results": [declared]}),
        encoding="utf-8",
    )

    initialized = ApplicationGateway().initialize_project(tmp_path, authorized=True)

    assert initialized.status == "trial_problem"
    assert initialized.payload["work_item"] is None


def ledger_for(root: Path) -> WorkflowLedger:
    return WorkflowLedger(
        root / ".rob2" / "ledger.sqlite3",
        ArtifactStore(root / ".rob2" / "artifacts"),
    )


def test_source_classification_accounts_for_every_issued_source(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    (trial / "protocol.pdf").write_bytes(b"protocol")
    gateway = ApplicationGateway(
        parser=StubParser(
            {
                "report": (page(1, "Trial report"),),
                "protocol": (page(1, "Trial protocol"),),
            }
        )
    )
    initialized = gateway.initialize_project(tmp_path, authorized=True)
    work_item = initialized.payload["work_item"]
    mutation_context = {
        "idempotency_key": "idempotency:all-sources",
        "work_item_id": work_item["work_item_id"],
        "contract_version": "1.0.0",
        "expected_dependency_fingerprint": work_item[
            "dependency_fingerprint"
        ],
    }

    with pytest.raises(ValueError, match="every issued trial source"):
        gateway.call(
            "submit_source_classification",
            initialized.payload["project_id"],
            arguments={
                "classifications": [
                    {
                        "source_id": "source:trial-a-1",
                        "roles": ["primary_report"],
                    }
                ]
            },
            mutation_context=mutation_context,
        )


def test_visual_step_is_deterministically_skipped_without_candidates(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report")
    gateway = ApplicationGateway(
        parser=StubParser({"report": (page(1, "Trial report"),)})
    )
    initialized = gateway.initialize_project(tmp_path, authorized=True)
    project_id = initialized.payload["project_id"]
    candidate_id = gateway.call(
        "search_evidence",
        project_id,
        arguments={"query": {"terms": ["trial"]}},
    ).payload["hits"][0]["candidate_id"]
    submissions = (
        (
            "submit_source_classification",
            {
                "classifications": [
                    {
                        "source_id": "source:trial-a-1",
                        "roles": ["primary_report"],
                    }
                ]
            },
        ),
        ("submit_result_resolution", result_resolution_submission()),
        (
            "submit_evidence_dispositions",
            {
                "dispositions": [
                    {"candidate_id": candidate_id, "kind": "immaterial"}
                ]
            },
        ),
    )
    for index, (tool_name, arguments) in enumerate(submissions):
        work_item = gateway.call("get_next_work", project_id).payload["work_item"]
        gateway.call(
            tool_name,
            project_id,
            arguments=arguments,
            mutation_context={
                "idempotency_key": f"idempotency:no-visual-{index}",
                "work_item_id": work_item["work_item_id"],
                "contract_version": "1.0.0",
                "expected_dependency_fingerprint": work_item[
                    "dependency_fingerprint"
                ],
            },
        )

    next_work = gateway.call("get_next_work", project_id)

    assert next_work.payload["work_item"]["permitted_tool"] == "freeze_evidence_bundle"
    assert any(
        event.operation == "operation:submit-visual-transcription"
        and json.loads(ledger_for(tmp_path).artifacts.read(
            event.output_revision_hashes[0]
        ))["status"] == "not_required"
        for event in ledger_for(tmp_path).events()
    )


def test_generated_adapters_share_canonical_skill_and_exact_launcher(
    tmp_path: Path,
) -> None:
    skills = {
        "rob2-init": "Initialize the exact run.\n",
        "rob2-assess": "Assess bounded evidence.\n",
    }
    for skill_name, body in skills.items():
        canonical = tmp_path / "skills" / skill_name / "SKILL.md"
        canonical.parent.mkdir(parents=True)
        canonical.write_text(
            f"---\nname: {skill_name}\n---\n{body}",
            encoding="utf-8",
        )
        (canonical.parent / "activation-fixtures.json").write_text(
            '{"activates":["Use this skill"],"does_not_activate":["Human sign-off"]}\n',
            encoding="utf-8",
        )
    logic = tmp_path / "packs" / "logic" / "rob2-parallel-assignment-2019.1.yaml"
    guidance = (
        tmp_path
        / "packs"
        / "guidance"
        / "rob2-parallel-assignment-en-2019.1.yaml"
    )
    logic.parent.mkdir(parents=True)
    guidance.parent.mkdir(parents=True)
    logic.write_text("pack: logic\n", encoding="utf-8")
    guidance.write_text("pack: guidance\n", encoding="utf-8")
    shutil.copy(Path(__file__).resolve().parents[1] / "uv.lock", tmp_path / "uv.lock")

    manifest = build_host_adapters(tmp_path, package_version="0.1.0")

    assert set(manifest.skills) == set(skills)
    assert manifest.launcher == "uvx --python 3.13 --from rob2-kit==0.1.0 rob2-mcp"
    assert manifest.release_status == "draft_only_preview"
    assert manifest.sign_off_authority == "human_only"
    assert manifest.launcher_working_directory == "project_root"
    for host in ("codex", "claude"):
        for skill_name in skills:
            generated = tmp_path / "adapters" / host / "skills" / skill_name
            assert (generated / "SKILL.md").read_text() == (
                tmp_path / "skills" / skill_name / "SKILL.md"
            ).read_text()
    codex = json.loads((tmp_path / "adapters" / "codex" / "adapter.json").read_text())
    claude = json.loads((tmp_path / "adapters" / "claude" / "adapter.json").read_text())
    assert codex["skill_hashes"] == claude["skill_hashes"]
    assert codex["trigger_description"] == claude["trigger_description"]
    assert codex["launcher_working_directory"] == "project_root"
    assert claude["launcher_working_directory"] == "project_root"
    verify_host_adapters(tmp_path)
    codex["host"] = "hand-edited"
    (tmp_path / "adapters" / "codex" / "adapter.json").write_text(
        json.dumps(codex),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="generation template"):
        verify_host_adapters(tmp_path)


def test_checked_in_host_adapters_match_canonical_generation() -> None:
    verify_host_adapters(Path(__file__).resolve().parents[1])


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
