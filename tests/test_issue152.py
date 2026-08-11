"""Regression coverage for structure-only parser evidence (#152)."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from rob2_kit.application.contracts import (
    ContinueRunRequest,
    EvidencePassageInput,
    ReadEvidenceResponse,
    SearchEvidenceRequest,
    SearchEvidenceResponse,
    SQAnswerInput,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
)
from rob2_kit.domain.canonical import sha256_digest
from rob2_kit.evidence.errors import ReprocessingRequired
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceSearchIndex,
    SearchQuery,
)
from rob2_kit.evidence.workflow import SearchPassKind, V2QueryAttemptKind
from rob2_kit.ingestion.project import PageRender, PageTextItem
from tests.test_input_reconciliation import (
    DOMAINS,
    StructuredPassageParser,
    _classify_current_sources,
    _complete_empty_receipts,
    _complete_passage_receipts,
    _config,
    _location_handle_for,
    _prepare_confirm,
    _result,
    _review_revision,
)
from tests.test_issue151 import _freeze
from tests.test_mcp_tracer import _active_answer_ids, _low_answers

HASH = "sha256:" + "a" * 64


def _unit(*, text: str = "allocation was concealed") -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id="unit:source-report",
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report",
        page=1,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=text,
        section_path=("Methods",),
        hierarchy_path=("1",),
        reading_order=1,
        fragment_ids=("fragment:report-1",),
    )


@pytest.mark.parametrize(
    "field",
    (
        "trial_id",
        "result_id",
        "domain_id",
        "question_ids",
        "applicability",
        "applicable_result_ids",
    ),
)
def test_parser_and_canonical_units_reject_scientific_semantic_fields(field: str) -> None:
    payload = {
        "text": "source text",
        "x": 1,
        "y": 1,
        "width": 10,
        "height": 10,
        field: "result:forbidden",
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PageTextItem.model_validate(payload)

    canonical = _unit().model_dump()
    canonical[field] = "result:forbidden"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CanonicalEvidenceUnit.model_validate(canonical)


@pytest.mark.parametrize(
    "field",
    (
        "trial_id",
        "result_id",
        "domain_id",
        "question_id",
        "trial_ids",
        "result_ids",
        "domain_ids",
        "question_ids",
        "source_roles",
        "document_zones",
        "kinds",
    ),
)
def test_removed_search_refinements_are_closed_schema_fields(field: str) -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SearchQuery.model_validate({"terms": ["allocation"], field: "forbidden"})


def test_outer_retrieval_schema_identity_is_closed_and_serialized() -> None:
    for response_type in (SearchEvidenceResponse, ReadEvidenceResponse):
        schema = response_type.model_json_schema()
        assert "retrieval_schema_version" not in schema["properties"]
    with pytest.raises(ValidationError):
        SearchEvidenceResponse.model_validate(
            {
                "operation_id": "operation:search",
                "ledger_cursor": "ledger:1",
                "affected_scope": ("result:one",),
                "condition": "accepted",
                "committed": True,
                "run_id": "run:one",
                "page": {"hits": (), "next_cursor": None},
                "retrieval_schema_version": "retrieval-schema:old",
            }
        )


def test_structure_only_parser_freezes_and_qualifies_answers(tmp_path) -> None:
    # Freeze through public operations with independently reviewed exact spans
    # for all active Randomization signaling questions.
    trial = tmp_path / "input" / "issue152"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:issue152", "trial:issue152")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit = index.read_unit(next(iter(index.unit_ids())))
    question_ids = DOMAINS["domain:randomization"]
    _complete_passage_receipts(engine, run_id, work, unit_id=unit.unit_id)
    reviews = tuple(
        _review_revision(
            candidate_id=unit.unit_id,
            result_id="result:issue152",
            domain_id="domain:randomization",
            question_id=question_id,
            location_handle=_location_handle_for(engine, run_id, work, question_id, unit.unit_id),
            span_start=0,
            span_end=len(unit.text),
            entity_suffix=f"issue152-{index}",
        )
        for index, question_id in enumerate(question_ids)
    )
    evidence = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue152-full-freeze",
            result_id="result:issue152",
            domain_id="domain:randomization",
            passages=(
                EvidencePassageInput(
                    unit_id=unit.unit_id,
                    span_start=0,
                    span_end=len(unit.text),
                    claim_type="claim-type:randomization",
                    candidate_id=unit.unit_id,
                    question_ids=question_ids,
                ),
            ),
            review_revisions=reviews,
        )
    )
    assert evidence.condition.value == "accepted"
    answer_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert answer_work is not None
    answer = engine.submit_domain_answers(
        SubmitDomainAnswersRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=answer_work.work_token,
            idempotency_key="idempotency:issue152-answer",
            result_id="result:issue152",
            domain_id="domain:randomization",
            answers=tuple(
                SQAnswerInput(
                    question_id=question_id,
                    answer="yes",
                    rationale="reviewed exact span",
                )
                for question_id in question_ids
            ),
        )
    )
    assert answer.condition.value == "accepted"


@pytest.mark.parametrize("tamper", ("trial", "source", "artifact", "parse"))
def test_terminal_qualification_requires_current_trial_source_parse_custody(
    tmp_path, monkeypatch, tamper: str
) -> None:
    engine, run_id, _, question_id = _freeze(tmp_path)
    ledger = engine._bound_ledger(run_id)
    proposal = engine._latest_proposal(ledger, run_id)
    trial = next(
        item for item in proposal.initialization.trials if item.trial_id == "trial:issue151"
    )
    assert trial.inventory is not None
    source = trial.inventory.sources[0]
    if tamper == "trial":
        replacement = trial.model_copy(update={"trial_id": "trial:wrong"})
    else:
        if tamper == "source":
            replacement_source = source.model_copy(update={"source_id": "source:wrong"})
        elif tamper == "artifact":
            replacement_source = source.model_copy(update={"artifact_hash": "sha256:" + "0" * 64})
        else:
            replacement_source = source.model_copy(
                update={
                    "parse_records": (
                        source.parse_records[0].model_copy(update={"parse_id": "parse:wrong"}),
                    )
                }
            )
        replacement = trial.model_copy(
            update={
                "inventory": trial.inventory.model_copy(update={"sources": (replacement_source,)})
            }
        )
    changed = proposal.model_copy(
        update={
            "initialization": proposal.initialization.model_copy(
                update={
                    "trials": tuple(
                        replacement if item.trial_id == trial.trial_id else item
                        for item in proposal.initialization.trials
                    )
                }
            )
        }
    )
    monkeypatch.setattr(engine, "_latest_proposal", lambda _ledger, _run_id: changed)
    failures = engine._evidence_insufficiencies(
        ledger, run_id, "result:issue151", {question_id: "yes"}
    )
    assert any(
        item.question_id == question_id and item.reason.value == "unresolvable_evidence"
        for item in failures
    )


def test_failed_physical_replacement_preserves_last_usable_index(tmp_path, monkeypatch) -> None:
    path = tmp_path / "crash-safe.sqlite3"
    index = EvidenceSearchIndex(path)
    original = _unit(text="original allocation")
    index.replace_units((original,))
    before = path.read_bytes()

    def fail_replace(_source, _destination):
        raise PermissionError("simulated Windows sharing violation")

    monkeypatch.setattr("rob2_kit.evidence.search.os.replace", fail_replace)
    with pytest.raises(PermissionError, match="sharing violation"):
        index.replace_units((_unit(text="replacement allocation"),))

    assert path.read_bytes() == before
    assert index.read_unit(original.unit_id) == original
    assert not tuple(tmp_path.glob("crash-safe.sqlite3.*.next"))


def test_assessing_run_resume_surfaces_reprocessing_required_for_legacy_index(tmp_path) -> None:
    trial = tmp_path / "input" / "upgrade"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:upgrade", "trial:upgrade")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    ledger = engine._bound_ledger(run_id)
    historical_event_bytes = ledger.artifacts.read(ledger.events()[0].output_revision_hashes[0])
    path = tmp_path / ".rob2" / "evidence.sqlite3"
    path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE evidence_units (unit_id TEXT PRIMARY KEY, text TEXT NOT NULL);
            INSERT INTO evidence_units VALUES ('unit:legacy', 'legacy text');
            CREATE TABLE evidence_snapshot (
                singleton INTEGER PRIMARY KEY, content_hash TEXT NOT NULL
            );
            INSERT INTO evidence_snapshot VALUES (1, 'sha256:legacy');
            """
        )
        connection.commit()
    finally:
        connection.close()

    resumed = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert resumed is not None
    with pytest.raises(ReprocessingRequired) as failure:
        engine.search_evidence(
            SearchEvidenceRequest(
                contract_version="2.0.0",
                run_id=run_id,
                work_token=resumed.work_token,
                result_id="result:upgrade",
                sq_id=DOMAINS["domain:randomization"][0],
                query=SearchQuery(terms=("legacy",)),
                pass_kind=SearchPassKind.GUIDANCE_SEED,
                seed_family="seed:upgrade",
                attempt_id="attempt:upgrade:legacy",
                attempt_kind=V2QueryAttemptKind.SELECTED,
            )
        )
    assert failure.value.code.value == "reprocessing_required"
    assert (
        ledger.artifacts.read(ledger.events()[0].output_revision_hashes[0])
        == historical_event_bytes
    )


def test_same_source_span_independently_freezes_and_qualifies_two_results(tmp_path) -> None:
    class ScreenshotParser(StructuredPassageParser):
        def screenshot(self, _data: bytes, *, page_numbers: tuple[int, ...], dpi: int):
            image = b"\x89PNG\r\n\x1a\n" + b"fixture"
            return tuple(
                PageRender(
                    page_number=page,
                    dpi=dpi,
                    pixel_width=1,
                    pixel_height=1,
                    image_hash=sha256_digest(image),
                    image_bytes=image,
                )
                for page in page_numbers
            )

    trial = tmp_path / "input" / "shared"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    first = _result("result:shared-first", "trial:shared")
    second = _result("result:shared-second", "trial:shared")
    second["result"]["outcome_construct"] = "adverse"
    second["result"]["measurement_instrument"] = "events"
    config = _config(first, second)
    config["outcome_targets"] = (
        {"id": "mortality", "label": "mortality", "construct": "mortality", "timepoint": "30 days"},
        {"id": "adverse", "label": "adverse", "construct": "adverse", "timepoint": "30 days"},
    )
    engine, run_id = _prepare_confirm(tmp_path, config=config, parser=ScreenshotParser())
    _classify_current_sources(engine, run_id)
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit = index.read_unit(next(iter(index.unit_ids())))
    question_ids = DOMAINS["domain:randomization"]
    frozen = []
    for result_id in ("result:shared-first", "result:shared-second"):
        work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
        assert work is not None and work.result_id == result_id
        _complete_passage_receipts(engine, run_id, work, unit_id=unit.unit_id)
        reviews = tuple(
            _review_revision(
                candidate_id=unit.unit_id,
                result_id=result_id,
                domain_id="domain:randomization",
                question_id=question_id,
                location_handle=_location_handle_for(
                    engine, run_id, work, question_id, unit.unit_id
                ),
                span_start=0,
                span_end=len(unit.text),
                entity_suffix=f"{result_id}-{number}",
            )
            for number, question_id in enumerate(question_ids)
        )
        evidence = engine.submit_domain_evidence(
            SubmitDomainEvidenceRequest(
                contract_version="2.0.0",
                run_id=run_id,
                work_token=work.work_token,
                idempotency_key=f"idempotency:{result_id}:evidence",
                result_id=result_id,
                domain_id="domain:randomization",
                passages=(
                    EvidencePassageInput(
                        unit_id=unit.unit_id,
                        span_start=0,
                        span_end=len(unit.text),
                        claim_type="claim-type:randomization",
                        candidate_id=unit.unit_id,
                        question_ids=question_ids,
                    ),
                ),
                review_revisions=reviews,
            )
        )
        assert evidence.condition.value == "accepted"
        answer_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
        assert answer_work is not None and answer_work.result_id == result_id
        answers = engine.submit_domain_answers(
            SubmitDomainAnswersRequest(
                contract_version="1.0.0",
                run_id=run_id,
                work_token=answer_work.work_token,
                idempotency_key=f"idempotency:{result_id}:answers",
                result_id=result_id,
                domain_id="domain:randomization",
                answers=tuple(
                    SQAnswerInput(
                        question_id=q, answer="yes", rationale="same reviewed source span"
                    )
                    for q in question_ids
                ),
            )
        )
        assert answers.condition.value == "accepted"
        frozen.append((evidence, reviews))
        if result_id == "result:shared-first":
            while True:
                remaining_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
                assert remaining_work is not None
                if remaining_work.result_id == "result:shared-second":
                    break
                domain_id = remaining_work.domain_id
                assert domain_id is not None
                active = _active_answer_ids(domain_id)
                _complete_empty_receipts(
                    engine,
                    run_id,
                    remaining_work,
                    domain_id=domain_id,
                    question_ids=DOMAINS[domain_id],
                )
                reviews = tuple(
                    _review_revision(
                        candidate_id=unit.unit_id,
                        result_id=result_id,
                        domain_id=domain_id,
                        question_id=q,
                        location_handle=_location_handle_for(
                            engine, run_id, remaining_work, q, unit.unit_id
                        ),
                        span_start=0,
                        span_end=len(unit.text),
                        entity_suffix=f"{result_id}-{domain_id}-{n}",
                    )
                    for n, q in enumerate(active)
                )
                empty = engine.submit_domain_evidence(
                    SubmitDomainEvidenceRequest(
                        contract_version="2.0.0",
                        run_id=run_id,
                        work_token=remaining_work.work_token,
                        idempotency_key=f"idempotency:{result_id}:{domain_id}:empty",
                        result_id=result_id,
                        domain_id=domain_id,
                        passages=(
                            EvidencePassageInput(
                                unit_id=unit.unit_id,
                                span_start=0,
                                span_end=len(unit.text),
                                claim_type="claim-type:shared",
                                candidate_id=unit.unit_id,
                                question_ids=active,
                            ),
                        ),
                        review_revisions=reviews,
                    )
                )
                assert empty.condition.value == "accepted"
                answer_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
                assert answer_work is not None
                response = engine.submit_domain_answers(
                    SubmitDomainAnswersRequest(
                        contract_version="1.0.0",
                        run_id=run_id,
                        work_token=answer_work.work_token,
                        idempotency_key=f"idempotency:{result_id}:{domain_id}:answers",
                        result_id=result_id,
                        domain_id=domain_id,
                        answers=tuple(
                            SQAnswerInput(
                                question_id=q,
                                answer=_low_answers()[q],
                                rationale="reviewed shared source span",
                            )
                            for q in active
                        ),
                    )
                )
                assert response.condition.value == "accepted"
    assert frozen[0][0].evidence_bundles != frozen[1][0].evidence_bundles
    assert frozen[0][1][0]["result_id"] != frozen[1][1][0]["result_id"]
