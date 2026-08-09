"""Regression coverage for evidence retry identity after an insufficiency block."""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import anyio

from rob2_kit.application.contracts import (
    ContinueRunRequest,
    PrepareRunRequest,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
    WorkflowCondition,
    WorkItem,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.evidence.search import EvidenceSearchIndex
from rob2_kit.ingestion.project import DocumentParser
from rob2_kit.interfaces.mcp.server import create_server
from tests.test_input_reconciliation import (
    StructuredPassageParser,
    _classify_current_sources,
    _config,
    _location_handle_for,
    _low_answers,
    _prepare_confirm,
    _result,
    _review_revision,
)
from tests.test_issue127 import _complete_real_search
from tests.test_mcp_tracer import DOMAINS


@dataclass(frozen=True)
class _EvidenceRun:
    engine: RunEngine
    run_id: str
    first: WorkItem
    result_id: str
    domain_id: str


async def _call_tool(server, name: str, arguments: dict[str, object]):
    return await server.call_tool(name, arguments)


def _prepare_evidence_run(tmp_path: Path, suffix: str) -> _EvidenceRun:
    trial = tmp_path / "input" / suffix
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result(f"result:{suffix}", f"trial:{suffix}")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    first = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert first is not None
    assert first.result_id is not None
    assert first.domain_id is not None
    _complete_real_search(engine, run_id, first, DOMAINS[first.domain_id])
    return _EvidenceRun(engine, run_id, first, first.result_id, first.domain_id)


def _block_domain_answers(run: _EvidenceRun, idempotency_key: str) -> None:
    answer = run.engine.continue_run(ContinueRunRequest(run_id=run.run_id)).work_item
    assert answer is not None
    blocked = run.engine.submit_domain_answers(
        SubmitDomainAnswersRequest(
            contract_version="1.0.0",
            run_id=run.run_id,
            work_token=answer.work_token,
            idempotency_key=idempotency_key,
            result_id=run.result_id,
            domain_id=run.domain_id,
            answers=tuple(
                {
                    "question_id": question_id,
                    "answer": _low_answers()[question_id],
                    "rationale": "Insufficient evidence forces a retry.",
                }
                for question_id in DOMAINS[run.domain_id]
            ),
        )
    )
    assert blocked.condition is WorkflowCondition.RUN_BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "evidence_insufficient"


def test_evidence_insufficiency_issues_a_fresh_stable_retry_work_item(
    tmp_path: Path,
) -> None:
    run = _prepare_evidence_run(tmp_path, "retry-identity-141")
    frozen = run.engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.1.0",
            run_id=run.run_id,
            work_token=run.first.work_token,
            idempotency_key="idempotency:issue141-first-evidence",
            result_id=run.result_id,
            domain_id=run.domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Intentionally incomplete for retry identity.",),
        )
    )
    assert frozen.condition is WorkflowCondition.ACCEPTED
    _block_domain_answers(run, "idempotency:issue141-blocked-answers")

    rerouted = run.engine.continue_run(ContinueRunRequest(run_id=run.run_id)).work_item
    repeated = run.engine.continue_run(ContinueRunRequest(run_id=run.run_id)).work_item
    assert rerouted is not None
    assert repeated is not None
    assert rerouted.operation.value == "submit_domain_evidence"
    assert rerouted.result_id == run.result_id
    assert rerouted.domain_id == run.domain_id
    assert rerouted.work_item_id != run.first.work_item_id
    assert rerouted.work_token != run.first.work_token
    assert rerouted.dependency_fingerprint != run.first.dependency_fingerprint
    assert repeated == rerouted

    resumed_engine = RunEngine(parser=cast(DocumentParser, StructuredPassageParser()))
    resumed = resumed_engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert resumed.run_id == run.run_id
    resumed_reroute = resumed_engine.continue_run(ContinueRunRequest(run_id=run.run_id)).work_item
    assert resumed_reroute == rerouted


def test_mcp_caller_can_commit_corrected_evidence_and_replay_it_exactly(
    tmp_path: Path,
) -> None:
    run = _prepare_evidence_run(tmp_path, "mcp-retry-141")
    server = create_server(engine=run.engine)
    first_submission = anyio.run(
        _call_tool,
        server,
        "submit_domain_evidence",
        {
            "run_id": run.run_id,
            "work_token": run.first.work_token.model_dump(mode="json"),
            "result_id": run.result_id,
            "domain_id": run.domain_id,
            "contract_version": "1.1.0",
            "coverage_state": "incomplete",
            "coverage_limitations": ["Intentionally incomplete for MCP retry."],
        },
    )
    assert first_submission.structured_content is not None
    assert first_submission.structured_content["condition"] == "accepted"
    _block_domain_answers(run, "idempotency:issue141-mcp-blocked-answers")

    rerouted = run.engine.continue_run(ContinueRunRequest(run_id=run.run_id)).work_item
    assert rerouted is not None
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit_id = next(iter(index.unit_ids()))
    unit = index.read_unit(unit_id)
    question_id = DOMAINS[run.domain_id][0]
    location_handle = _location_handle_for(run.engine, run.run_id, rerouted, question_id, unit_id)
    corrected_arguments = {
        "run_id": run.run_id,
        "work_token": rerouted.work_token.model_dump(mode="json"),
        "result_id": run.result_id,
        "domain_id": run.domain_id,
        "contract_version": "1.1.0",
        "passages": [
            {
                "unit_id": unit_id,
                "span_start": 0,
                "span_end": len(unit.text),
                "claim_type": "claim-type:randomization-method",
                "question_ids": [question_id],
            }
        ],
        "review_revisions": [
            _review_revision(
                candidate_id=unit_id,
                result_id=run.result_id,
                domain_id=run.domain_id,
                question_id=question_id,
                location_handle=location_handle,
                span_start=0,
                span_end=len(unit.text),
                entity_suffix="issue141-mcp-retry",
            )
        ],
    }
    corrected = anyio.run(_call_tool, server, "submit_domain_evidence", corrected_arguments)
    replayed = anyio.run(_call_tool, server, "submit_domain_evidence", corrected_arguments)
    assert corrected.structured_content is not None
    assert corrected.structured_content["condition"] == "accepted"
    assert corrected.structured_content["committed"] is True
    assert replayed.structured_content is not None
    assert replayed.structured_content["condition"] == "accepted"
    assert replayed.structured_content["committed"] is False
    assert (
        replayed.structured_content["operation_id"] == corrected.structured_content["operation_id"]
    )
