"""External stdio tracer for the typed RunEngine surface."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import anyio
import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    PrepareRunRequest,
    RunStatusRequest,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
    SubmitRunProposalRequest,
    SubmitSourceClassificationRequest,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.revisions import Actor, ActorKind
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
        "sq:deviations:appropriate-analysis": "yes",
        "sq:missing:data-available": "yes",
        "sq:measurement:method-inappropriate": "no",
        "sq:measurement:differential": "no",
        "sq:measurement:assessor-aware": "no",
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
        "sq:deviations:appropriate-analysis",
    ),
    "domain:missing": ("sq:missing:data-available",),
    "domain:measurement": (
        "sq:measurement:method-inappropriate",
        "sq:measurement:differential",
        "sq:measurement:assessor-aware",
    ),
    "domain:selection": (
        "sq:selection:prespecified-analysis",
        "sq:selection:multiple-measurements",
        "sq:selection:multiple-analyses",
    ),
}


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


async def _finish_domains(session: ClientSession, run_id: str) -> None:
    answers = _low_answers()
    for index, (domain_id, question_ids) in enumerate(DOMAINS.items()):
        work = (await session.call_tool("continue_run", {"run_id": run_id})).structured_content
        assert work is not None
        passages = []
        if index == 0:
            search = await session.call_tool(
                "search_evidence",
                {
                    "run_id": run_id,
                    "work_token": work["work_item"]["work_token"],
                    "sq_id": question_ids[0],
                    "result_id": "result:trial-a-mortality",
                    "query": {"terms": ["Trial"]},
                },
            )
            assert search.structured_content is not None
            hits = search.structured_content["page"]["hits"]
            if hits:
                hit = hits[0]
                unit = hit["unit"]
                passages = [
                    {
                        "unit_id": unit["unit_id"],
                        "span_start": hit["projection"]["start"],
                        "span_end": hit["projection"]["end"],
                        "claim_type": "claim-type:trial-report",
                        "question_ids": list(question_ids),
                    }
                ]
            else:
                assert search.structured_content["page"]["condition"] == "excluded_only"
                assert "retrieval_scope_excluded_matches" in search.structured_content[
                    "page"
                ]["scope_warnings"]
        evidence_payload = {
            "run_id": run_id,
            "work_token": work["work_item"]["work_token"],
            "contract_version": "1.0.0",
            "result_id": "result:trial-a-mortality",
            "domain_id": domain_id,
            "passages": passages,
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
            for question_id in question_ids
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
                await _finish_domains(session, run_id)
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
        for index, (domain_id, question_ids) in enumerate(DOMAINS.items()):
            evidence_work = engine.continue_run(
                ContinueRunRequest(run_id=prepared.run_id)
            ).work_item
            assert evidence_work is not None
            engine.submit_domain_evidence(
                SubmitDomainEvidenceRequest.model_validate(
                    {
                        "run_id": prepared.run_id,
                        "work_token": evidence_work.work_token,
                        "idempotency_key": f"idempotency:{suffix}-evidence-{index}",
                        "result_id": result_id,
                        "domain_id": domain_id,
                        "contract_version": "1.0.0",
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
                            for question_id in question_ids
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
