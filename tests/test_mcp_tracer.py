"""External stdio tracer for the typed RunEngine surface."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import anyio
import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    PrepareRunRequest,
    RunProposalSelection,
    RunStatusRequest,
    SearchEvidenceRequest,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
    SubmitRunProposalRequest,
    SubmitSourceClassificationRequest,
    WorkToken,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.evidence import VisualTranscription
from rob2_kit.domain.revisions import Actor, ActorKind, Dependency, RecordReference
from rob2_kit.evidence.search import SearchQuery
from rob2_kit.evidence.workflow import (
    SearchCoverageReceipt,
    SearchPassKind,
    SourceSearchCoverage,
    SourceSearchState,
)
from rob2_kit.interfaces.mcp.server import CANONICAL_TOOL_NAMES, registered_tool_names
from rob2_kit.reports.archives import verify_archive
from rob2_kit.storage import ArtifactStore, WorkflowLedger
from rob2_kit.storage.ledger import LeaseConflictError
from tests.test_host_interfaces import blank_pdf


def _result_declaration() -> dict[str, object]:
    return {
        "result": {
            "result_id": "result:trial-a-mortality",
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
        "provenance_note": "Synthetic tracer Result.",
    }


def _low_answers() -> dict[str, str]:
    return {
        "sq:randomization:sequence": "yes",
        "sq:randomization:concealment": "yes",
        "sq:randomization:baseline-imbalance": "no",
        "sq:deviations:participants-aware": "no",
        "sq:deviations:personnel-aware": "no",
        "sq:deviations:context-deviations": "no",
        "sq:deviations:affected-outcome": "no",
        "sq:deviations:balanced": "yes",
        "sq:deviations:appropriate-analysis": "yes",
        "sq:deviations:substantial-impact": "no",
        "sq:missing:data-available": "yes",
        "sq:missing:evidence-unbiased": "yes",
        "sq:missing:true-value-dependent": "no",
        "sq:missing:likely-dependent": "no",
        "sq:measurement:method-inappropriate": "no",
        "sq:measurement:differential": "no",
        "sq:measurement:assessor-aware": "no",
        "sq:measurement:influence-possible": "no",
        "sq:measurement:influence-likely": "no",
        "sq:selection:prespecified-analysis": "yes",
        "sq:selection:multiple-measurements": "no",
        "sq:selection:multiple-analyses": "no",
    }


DOMAINS = {
    "domain:randomization": (
        "sq:randomization:sequence",
        "sq:randomization:concealment",
        "sq:randomization:baseline-imbalance",
    ),
    "domain:deviations": (
        "sq:deviations:participants-aware",
        "sq:deviations:personnel-aware",
        "sq:deviations:context-deviations",
        "sq:deviations:affected-outcome",
        "sq:deviations:balanced",
        "sq:deviations:appropriate-analysis",
        "sq:deviations:substantial-impact",
    ),
    "domain:missing": (
        "sq:missing:data-available",
        "sq:missing:evidence-unbiased",
        "sq:missing:true-value-dependent",
        "sq:missing:likely-dependent",
    ),
    "domain:measurement": (
        "sq:measurement:method-inappropriate",
        "sq:measurement:differential",
        "sq:measurement:assessor-aware",
        "sq:measurement:influence-possible",
        "sq:measurement:influence-likely",
    ),
    "domain:selection": (
        "sq:selection:prespecified-analysis",
        "sq:selection:multiple-measurements",
        "sq:selection:multiple-analyses",
    ),
}

_FIXTURE_ACTOR = Actor(
    kind=ActorKind.HUMAN,
    actor_id="actor:mcp-tracer-fixture",
    display_name="MCP tracer fixture",
)


def _active_answer_ids(domain_id: str) -> tuple[str, ...]:
    """Return the fixture's active signaling questions under `_low_answers()`."""

    return {
        "domain:randomization": DOMAINS["domain:randomization"],
        "domain:deviations": (
            "sq:deviations:participants-aware",
            "sq:deviations:personnel-aware",
            "sq:deviations:appropriate-analysis",
        ),
        "domain:missing": ("sq:missing:data-available",),
        "domain:measurement": (
            "sq:measurement:method-inappropriate",
            "sq:measurement:differential",
            "sq:measurement:assessor-aware",
        ),
        "domain:selection": DOMAINS["domain:selection"],
    }[domain_id]


def _synthetic_visual_ref(engine: RunEngine, run_id: str, result_id: str) -> RecordReference:
    """Freeze one source-scoped visual citation for the synthetic tracer report."""

    ledger = engine._bound_ledger(run_id)
    proposal = engine._latest_proposal(ledger, run_id)
    result_spec = engine._result_spec_for(ledger, run_id, result_id)
    assert result_spec is not None
    trial = next(
        item
        for item in proposal.initialization.trials
        if item.trial_id == result_spec.result.trial_id
    )
    inventory = trial.inventory
    assert inventory is not None
    source = inventory.sources[0]
    suffix = engine._digest(f"{run_id}|{source.source_id}|{source.artifact_hash}")
    source_ref = engine._commit_frozen_artifact(
        ledger,
        scope=result_id,
        operation="operation:test-mcp-visual-source-frozen",
        operation_key=f"idempotency:test-mcp-visual-source:{source.source_id}",
        entity_id=source.source_id,
        revision_id=f"revision:mcp-evidence-source-{suffix}",
        artifact=source,
        actor=_FIXTURE_ACTOR,
    )
    transcription = VisualTranscription(
        entity_id=f"visual-transcription:{suffix}",
        revision_id=f"revision:mcp-visual-transcription-{suffix}",
        dependencies=(Dependency(**source_ref.model_dump(), role="dependency:source"),),
        actor=_FIXTURE_ACTOR,
        observed_at=engine._now(),
        source=source_ref,
        page=1,
        region=(1.0, 1.0, 20.0, 20.0),
        render_mode="crop",
        dpi=144,
        transcription="Synthetic visual evidence supports the scoped answer.",
    )
    return engine._commit_frozen_artifact(
        ledger,
        scope=result_id,
        operation="operation:test-mcp-visual-transcription-frozen",
        operation_key=f"idempotency:test-mcp-visual-transcription:{suffix}",
        entity_id=transcription.entity_id,
        revision_id=transcription.revision_id,
        artifact=transcription,
        actor=_FIXTURE_ACTOR,
        dependencies=transcription.dependencies,
    )


def _complete_empty_receipts(
    engine: RunEngine, run_id: str, work: object, question_ids: tuple[str, ...]
) -> tuple[SearchCoverageReceipt, ...]:
    """Create complete three-pass receipts for visual-only fixture evidence."""

    token = getattr(work, "work_token")
    result_id = getattr(work, "result_id")
    ledger = engine._bound_ledger(run_id)
    result_spec = engine._result_spec_for(ledger, run_id, result_id)
    assert result_spec is not None
    proposal = engine._latest_proposal(ledger, run_id)
    trial = next(item for item in proposal.initialization.trials if item.trial_id == token.trial_id)
    inventory = trial.inventory
    assert inventory is not None
    result_ref = RecordReference(
        entity_id=result_spec.entity_id,
        revision_id=result_spec.revision_id,
        content_hash=canonical_hash(result_spec),
    )
    inventory_suffix = engine._digest(
        f"{run_id}|{result_id}|{result_ref.content_hash}|source-inventory"
    )
    receipts: list[SearchCoverageReceipt] = []
    for question_id in question_ids:
        slug = question_id.removeprefix("sq:").replace(":", "-")
        queries = (
            (SearchQuery(terms=(f"absent-{slug}",)), SearchPassKind.GUIDANCE_SEED, f"seed:{slug}"),
            (SearchQuery(terms=(f"followup-{slug}",)), SearchPassKind.TRIAL_FOLLOW_UP, None),
            (SearchQuery(terms=(f"contradiction-{slug}",)), SearchPassKind.CONTRADICTION, None),
        )
        responses = tuple(
            engine.search_evidence(
                SearchEvidenceRequest(
                    run_id=run_id, work_token=token, result_id=result_id, sq_id=question_id,
                    query=query, pass_kind=pass_kind, seed_family=seed_family,
                )
            )
            for query, pass_kind, seed_family in queries
        )
        receipt = SearchCoverageReceipt(
            receipt_id=f"coverage:mcp-synthetic-{slug}", sq_id=question_id,
            snapshot_hash=responses[0].page.snapshot_hash, policy_id=responses[0].page.policy_id,
            policy_hash=responses[0].page.policy_hash, result_spec=result_ref,
            source_inventory=RecordReference(
                entity_id=f"source-inventory:{result_id.removeprefix('result:')}",
                revision_id=f"revision:source-inventory-{inventory_suffix}",
                content_hash=canonical_hash(inventory),
            ),
            parse_record_hashes=tuple(
                sorted(
                    {
                        parse.output_hash
                        for source in inventory.sources
                        for parse in source.parse_records
                    }
                )
            ),
            guidance_release_id="guidance:rob2-2019.1", required_seed_families=(f"seed:{slug}",),
            completed_seed_families=(f"seed:{slug}",),
            completed_passes=tuple(pass_kind for _query, pass_kind, _seed in queries),
            executed_queries=tuple(response.executed_query for response in responses),
            returned_unit_ids=(),
            result_dispositions=(),
            sources=tuple(
                SourceSearchCoverage(
                    source_id=source.source_id,
                    state=SourceSearchState.SEARCHED,
                    sufficiently_readable=True,
                    artifact_hash=source.artifact_hash,
                )
                for source in inventory.sources
            ),
            inventory_source_ids=tuple(source.source_id for source in inventory.sources),
            traversal_complete=True, interrupted=False,
        )
        proof = receipt.model_dump(mode="json")
        proof["recorder_proof"] = None
        receipts.append(
            SearchCoverageReceipt.model_validate(
                receipt.model_dump(mode="json")
                | {"recorder_proof": canonical_hash(proof)}
            )
        )
    return tuple(receipts)


async def _session(root: Path, wheel: Path):
    parameters = StdioServerParameters(
        command="uv",
        args=[
            "run",
            "--isolated",
            "--no-project",
            "--with",
            str(wheel),
            "rob2-mcp",
        ],
        cwd=Path.cwd(),
    )
    return stdio_client(parameters)


async def _prepare_and_confirm(session: ClientSession, root: Path) -> str:
    prepared = (
        await session.call_tool("prepare_run", {"project_root": str(root), "authorized": True})
    ).structured_content
    assert prepared is not None
    proposal = prepared["proposal"]
    submitted = (
        await session.call_tool(
            "submit_run_proposal",
            {
                "run_id": prepared["run_id"],
                "proposal_token": proposal["proposal_token"],
                "contract_version": "1.0.0",
                # The sole Result candidate is never auto-bound by cardinality
                # alone (#119); it still needs an explicit accepted selection.
                "selections": [
                    {
                        "trial_id": "trial:trial-a",
                        "outcome_target_id": "outcome-target:mortality",
                        "result_id": "result:trial-a-mortality",
                        "accepted": True,
                    }
                ],
            },
        )
    ).structured_content
    assert submitted is not None
    await session.call_tool(
        "confirm_run_definition",
        {
            "run_id": prepared["run_id"],
            "proposal_token": submitted["proposal"]["proposal_token"],
            "confirmed_by": {
                "kind": "human",
                "actor_id": "actor:tracer",
                "display_name": "Tracer",
            },
            "contract_version": "1.0.0",
        },
    )
    return prepared["run_id"]


async def _finish_domains(session: ClientSession, root: Path, run_id: str) -> None:
    answers = _low_answers()
    fixture_engine = RunEngine()
    fixture_engine._root = root
    with sqlite3.connect(root / ".rob2" / "ledger.sqlite3") as connection:
        owner_row = connection.execute(
            "SELECT owner_id FROM writer_lease WHERE singleton = 1"
        ).fetchone()
    assert owner_row is not None
    fixture_engine._owner_id = owner_row[0]
    visual_ref: RecordReference | None = None
    for index, (domain_id, question_ids) in enumerate(DOMAINS.items()):
        work = (await session.call_tool("continue_run", {"run_id": run_id})).structured_content
        assert work is not None
        fixture_work = SimpleNamespace(
            work_token=WorkToken.model_validate(work["work_item"]["work_token"]),
            result_id=work["work_item"]["result_id"],
        )
        if visual_ref is None:
            visual_ref = _synthetic_visual_ref(fixture_engine, run_id, fixture_work.result_id)
            fixture_engine._visual_citations = lambda *_args: ()
        evidence_payload = {
            "run_id": run_id,
            "work_token": work["work_item"]["work_token"],
            "contract_version": "1.0.0",
            "result_id": "result:trial-a-mortality",
            "domain_id": domain_id,
            "items": [visual_ref.model_dump(mode="json")],
            "evidence_by_question": {
                question_id: [visual_ref.model_dump(mode="json")] for question_id in question_ids
            },
            "candidate_dispositions": [
                {"item_id": visual_ref.entity_id, "disposition": "supporting"}
            ],
            "coverage_receipts": [
                receipt.model_dump(mode="json")
                for receipt in _complete_empty_receipts(
                    fixture_engine, run_id, fixture_work, question_ids
                )
            ],
        }
        if index == 0:
            evidence_payload.update(
                {
                    "coverage_state": "complete_with_limitations",
                    "coverage_limitations": ["Synthetic uncertainty retained in report."],
                }
            )
        evidence = await session.call_tool(
            "submit_domain_evidence",
            evidence_payload,
        )
        assert evidence.structured_content is not None
        assert evidence.structured_content["condition"] == "accepted"
        assert evidence.structured_content["committed"] is True
        work = (await session.call_tool("continue_run", {"run_id": run_id})).structured_content
        assert work is not None
        answer_payload = [
            {
                "question_id": question_id,
                "answer": answers[question_id],
                "rationale": "Supported by the frozen synthetic evidence.",
            }
            for question_id in _active_answer_ids(domain_id)
        ]
        submitted = await session.call_tool(
            "submit_domain_answers",
            {
                "run_id": run_id,
                "work_token": work["work_item"]["work_token"],
                "contract_version": "1.0.0",
                "result_id": "result:trial-a-mortality",
                "domain_id": domain_id,
                "answers": answer_payload,
            },
        )
        assert submitted.structured_content is not None
        assert submitted.structured_content["condition"] == "accepted"
        assert submitted.structured_content["committed"] is True


def test_five_domain_journey_survives_stdio_restart_and_publishes_report(
    tmp_path: Path,
) -> None:
    assert registered_tool_names() == CANONICAL_TOOL_NAMES
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(blank_pdf())
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "results": [_result_declaration()],
                "outcome_targets": [
                    {
                        "id": "mortality",
                        "label": "mortality",
                        "construct": "Mortality",
                        "timepoint": "30 days",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0
    wheel = next(wheel_dir.glob("rob2_kit-*.whl"))

    async def journey() -> None:
        async with await _session(tmp_path, wheel) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert tuple(tool.name for tool in tools.tools) == CANONICAL_TOOL_NAMES
                for tool in tools.tools:
                    if tool.name.startswith("submit_"):
                        assert "contract_version" in tool.input_schema["required"]
                        assert "mutation_context" not in tool.input_schema["properties"]
                run_id = await _prepare_and_confirm(session, tmp_path)
                work = (
                    await session.call_tool("continue_run", {"run_id": run_id})
                ).structured_content
                assert work is not None
                assert work["work_item"]["operation"] == "submit_source_classification"
                source = await session.call_tool(
                    "submit_source_classification",
                    {
                        "run_id": run_id,
                        "work_token": work["work_item"]["work_token"],
                        "contract_version": "1.0.0",
                        "classifications": [
                            {"source_id": "source:trial-a-1", "roles": ["primary_report"]}
                        ],
                    },
                )
                assert source.structured_content is not None
                assert source.structured_content["condition"] == "accepted"
                assert source.structured_content["committed"] is True

        # A new process has no conversation state; prepare_run must rebind to
        # the same durable Current run before the remaining work continues.
        async with await _session(tmp_path, wheel) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                rebound = (
                    await session.call_tool("prepare_run", {"project_root": str(tmp_path)})
                ).structured_content
                assert rebound is not None
                assert rebound["run_id"] == run_id
                await _finish_domains(session, tmp_path, run_id)
                # The first terminal continuation must leave the run index
                # synchronized with the committed readiness event and the
                # already-visible report bundle.  A status call must not be
                # required to repair a stale empty index.
                continued = (
                    await session.call_tool("continue_run", {"run_id": run_id})
                ).structured_content
                assert continued is not None
                assert continued["run_state"] == "complete"
                run_indexes = tuple(
                    (tmp_path / "output" / "report-bundle").rglob("run-index.json")
                )
                assert len(run_indexes) == 1
                first_index = json.loads(run_indexes[0].read_text(encoding="utf-8"))
                assert len(first_index["results"]) == 1
                assert first_index["results"][0]["state"] == "report_ready"
                assert first_index["results"][0]["report"].endswith("/assessment.html")
                assert first_index["results"][0]["result_id"] == "result:trial-a-mortality"
                assert first_index["results"][0]["trial_id"] == "trial:trial-a"
                assert first_index["ancillary_outputs"]
                repeated = (
                    await session.call_tool("continue_run", {"run_id": run_id})
                ).structured_content
                assert repeated is not None
                assert repeated["run_state"] == "complete"
                assert json.loads(run_indexes[0].read_text(encoding="utf-8")) == first_index
                assert "run_status" not in {tool.name for tool in tools.tools}

    anyio.run(journey)

    report_base = tmp_path / "output" / "report-bundle"
    report_root = next(
        path.parent
        for path in report_base.rglob("manifest.json")
        if "files" in json.loads(path.read_text(encoding="utf-8"))
    )
    run_root = report_root.parents[3]
    required_files = {
        "answers.json",
        "assessment.html",
        "assessment.json",
        "assessment.md",
        "assessment.summary.json",
        "manifest.json",
        "robvis.csv",
        "robvis.xlsx",
        "verification-archive.rob2.zip",
        "visual-citations.json",
    }
    assert required_files <= {path.name for path in report_root.iterdir()}
    assessment_html = (report_root / "assessment.html").read_text(encoding="utf-8")
    run_index_html = (run_root / "run-index.html").read_text(encoding="utf-8")
    assert 'aria-label="RoB 2 domains"' in assessment_html
    assert "Signaling question" in assessment_html
    assert "AI rationale" in assessment_html
    assert "@media print" in assessment_html
    assert ":focus-visible" in assessment_html
    assert "Execution contract" in assessment_html
    assert "Execution contract" in run_index_html
    assert "Terminal outcomes" in run_index_html
    assert "Text-labelled traffic-light judgment" in run_index_html
    manifest = json.loads((report_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["overall_judgment"] == "low"
    assert manifest["assessment_revision_id"].startswith("assessment:")
    assert {
        "answers.json",
        "assessment.html",
        "assessment.json",
        "assessment.md",
        "assessment.summary.json",
        "robvis.csv",
        "robvis.xlsx",
        "verification-archive.rob2.zip",
        "visual-citations.json",
    } <= set(manifest["files"])
    for name, digest in manifest["files"].items():
        content = (report_root / name).read_bytes()
        assert digest == "sha256:" + hashlib.sha256(content).hexdigest()
    receipt = verify_archive((report_root / "verification-archive.rob2.zip").read_bytes())
    assert receipt.assessment_revision_id == manifest["assessment_revision_id"]
    index = json.loads((run_root / "run-index.json").read_text(encoding="utf-8"))
    assert index["results"][0]["result_id"] == "result:trial-a-mortality"
    assert index["results"][0]["trial_id"] == "trial:trial-a"
    assert index["results"][0]["state"] == "report_ready"
    assert index["results"][0]["report"].endswith("/assessment.html")
    assert index["results"][0]["overall_judgment"] == "low"
    assert index["results"][0]["limitations"] == ["Synthetic uncertainty retained in report."]
    assert index["run_id"].startswith("run:")
    ledger = WorkflowLedger(
        tmp_path / ".rob2" / "ledger.sqlite3",
        ArtifactStore(tmp_path / ".rob2" / "artifacts"),
    )
    operations = [event.operation for event in ledger.events()]
    assert "operation:result-report-ready" in operations
    assert "operation:run-completed" in operations
    assert "operation:result-started" in operations
    report_event = next(
        event for event in ledger.events() if event.operation == "operation:result-report-ready"
    )
    assert report_event.output_revision_hashes
    report_artifact = ledger.artifacts.read(report_event.output_revision_hashes[0])
    assert b'"assessment.json"' in report_artifact
    assert b'"manifest.json"' in report_artifact


def test_live_run_engine_lease_cannot_be_stolen_by_another_engine(
    tmp_path: Path,
) -> None:
    from rob2_kit.application.contracts import PrepareRunRequest
    from rob2_kit.application.run_engine import RunEngine

    first = RunEngine()
    first.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    second = RunEngine()
    try:
        second.prepare_run(
            PrepareRunRequest(project_root=tmp_path, authorized=True, start_new=True)
        )
    except LeaseConflictError:
        pass
    else:
        raise AssertionError("a live RunEngine lease must not be stolen")


def test_report_history_preserves_an_earlier_immutable_bundle(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(blank_pdf())
    first = _result_declaration()
    second = json.loads(json.dumps(first))
    second["result"]["result_id"] = "result:trial-a-morbidity"
    second["result"]["outcome_construct"] = "Morbidity"
    second["result"]["source_locator"] = "source:trial-a-1#result-morbidity"
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "results": [first, second],
                "outcome_targets": [
                    {
                        "id": "mortality",
                        "label": "mortality",
                        "construct": "Mortality",
                        "timepoint": "30 days",
                    },
                    {
                        "id": "morbidity",
                        "label": "morbidity",
                        "construct": "Morbidity",
                        "timepoint": "30 days",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    engine = RunEngine()
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is not None
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:history-proposal",
            contract_version="1.0.0",
            # Neither sole Result candidate is auto-bound by cardinality
            # alone (#119); each pairing needs its own explicit selection.
            selections=(
                RunProposalSelection(
                    trial_id="trial:trial-a",
                    outcome_target_id="outcome-target:mortality",
                    result_id="result:trial-a-mortality",
                    accepted=True,
                ),
                RunProposalSelection(
                    trial_id="trial:trial-a",
                    outcome_target_id="outcome-target:morbidity",
                    result_id="result:trial-a-morbidity",
                    accepted=True,
                ),
            ),
        )
    )
    engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:history-confirm",
            confirmed_by=Actor(
                kind=ActorKind.HUMAN,
                actor_id="actor:history",
                display_name="History test",
            ),
            contract_version="1.0.0",
        )
    )
    source_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert source_work is not None
    engine.submit_source_classification(
        SubmitSourceClassificationRequest.model_validate(
            {
                "run_id": prepared.run_id,
                "work_token": source_work.work_token,
                "idempotency_key": "idempotency:history-source",
                "classifications": [{"source_id": "source:trial-a-1", "roles": ["primary_report"]}],
                "contract_version": "1.0.0",
            }
        )
    )

    def finish_result(result_id: str, suffix: str) -> None:
        answers = _low_answers()
        visual_ref: RecordReference | None = None
        for index, (domain_id, question_ids) in enumerate(DOMAINS.items()):
            evidence_work = engine.continue_run(
                ContinueRunRequest(run_id=prepared.run_id)
            ).work_item
            assert evidence_work is not None
            if visual_ref is None:
                visual_ref = _synthetic_visual_ref(engine, prepared.run_id, result_id)
                engine._visual_citations = lambda *_args: ()
            engine.submit_domain_evidence(
                SubmitDomainEvidenceRequest.model_validate(
                    {
                        "run_id": prepared.run_id,
                        "work_token": evidence_work.work_token,
                        "idempotency_key": f"idempotency:{suffix}-evidence-{index}",
                        "result_id": result_id,
                        "domain_id": domain_id,
                        "contract_version": "1.0.0",
                        "items": [visual_ref.model_dump(mode="json")],
                        "evidence_by_question": {
                            question_id: [visual_ref.model_dump(mode="json")]
                            for question_id in question_ids
                        },
                        "candidate_dispositions": [
                            {"item_id": visual_ref.entity_id, "disposition": "supporting"}
                        ],
                        "coverage_receipts": [
                            receipt.model_dump(mode="json")
                            for receipt in _complete_empty_receipts(
                                engine, prepared.run_id, evidence_work, question_ids
                            )
                        ],
                    }
                )
            )
            answer_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
            assert answer_work is not None
            engine.submit_domain_answers(
                SubmitDomainAnswersRequest.model_validate(
                    {
                        "run_id": prepared.run_id,
                        "work_token": answer_work.work_token,
                        "idempotency_key": f"idempotency:{suffix}-answers-{index}",
                        "result_id": result_id,
                        "domain_id": domain_id,
                        "answers": [
                            {
                                "question_id": question_id,
                                "answer": answers[question_id],
                                "rationale": "Frozen synthetic evidence.",
                            }
                            for question_id in _active_answer_ids(domain_id)
                        ],
                        "contract_version": "1.0.0",
                    }
                )
            )

    finish_result("result:trial-a-mortality", "history-first")
    report_base = tmp_path / "output" / "report-bundle"
    report_root = next(
        path.parent
        for path in report_base.rglob("manifest.json")
        if "files" in json.loads(path.read_text(encoding="utf-8"))
    )
    first_files = {path.name: path.read_bytes() for path in report_root.iterdir() if path.is_file()}
    assert set(first_files) == {
        "answers.json",
        "assessment.html",
        "assessment.json",
        "assessment.md",
        "assessment.summary.json",
        "manifest.json",
        "robvis.csv",
        "robvis.xlsx",
        "verification-archive.rob2.zip",
        "visual-citations.json",
    }
    finish_result("result:trial-a-morbidity", "history-second")
    assert all(
        path.read_bytes() == content
        for path, content in (
            (report_root / name, content) for name, content in first_files.items()
        )
    )
    result_dirs = [
        path.parent
        for path in report_base.rglob("manifest.json")
        if "files" in json.loads(path.read_text(encoding="utf-8"))
    ]
    assert len(result_dirs) == 2
    assert {path.name for path in result_dirs[0].iterdir()} >= set(first_files)
    status = engine.run_status(RunStatusRequest(run_id=prepared.run_id))
    assert {item.state.value for item in status.result_states} == {"report_ready"}
