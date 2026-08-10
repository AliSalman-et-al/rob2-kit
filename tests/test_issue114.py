"""Terminal evidence sufficiency regressions for issue #114."""

from rob2_kit.application.contracts import (
    ContinueRunRequest,
    RunStatusRequest,
    SubmitDomainAnswersRequest,
    SubmitDomainEvidenceRequest,
    WorkflowCondition,
)
from rob2_kit.domain.evidence import EvidenceBundle, EvidenceConsiderationManifest
from rob2_kit.domain.revisions import Dependency, RecordReference
from tests.test_input_reconciliation import (
    _active_answer_ids,
    _classify_current_sources,
    _complete_empty_receipts,
    _config,
    _low_answers,
    _prepare_confirm,
    _result,
    _synthetic_visual_ref,
)
from tests.test_mcp_tracer import DOMAINS


def test_unsupported_active_answers_are_rejected_before_answer_revisions(tmp_path) -> None:
    trial = tmp_path / "input" / "unsupported"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:unsupported", "trial:unsupported")),
    )
    _classify_current_sources(engine, run_id)
    evidence = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert evidence is not None
    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=run_id,
            work_token=evidence.work_token,
            idempotency_key="idempotency:issue114-evidence",
            result_id=evidence.result_id,
            domain_id=evidence.domain_id,
            coverage_state="incomplete",
            coverage_limitations=("Fixture intentionally skips evidence search.",),
        )
    )
    answer = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert answer is not None
    before = len(engine._bound_ledger(run_id).events())
    response = engine.submit_domain_answers(
        SubmitDomainAnswersRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=answer.work_token,
            idempotency_key="idempotency:issue114-answers",
            result_id=answer.result_id,
            domain_id=answer.domain_id,
            answers=tuple(
                {
                    "question_id": question_id,
                    "answer": _low_answers()[question_id],
                    "rationale": "Unsupported fixture answer.",
                }
                for question_id in DOMAINS[answer.domain_id]
            ),
        )
    )
    assert response.condition is WorkflowCondition.RUN_BLOCKED
    assert response.committed is False
    assert response.next_permitted_action.value == "submit_domain_evidence"
    assert response.error is not None
    assert response.error.code == "evidence_insufficient"
    assert {item.question_id for item in response.evidence_insufficiencies} == set(
        DOMAINS[answer.domain_id]
    )
    ledger = engine._bound_ledger(run_id)
    # No scientific work commits (no answer revision), but the block itself is
    # durably marked (ADR-0008) so a later continue_run reroutes back to
    # submit_domain_evidence instead of re-offering the same blocked item.
    assert len(ledger.events()) == before + 1
    new_events = ledger.events()[before:]
    assert all(event.operation == "operation:domain-evidence-insufficient" for event in new_events)
    assert not any(event.operation == "operation:sq-answer-revision" for event in ledger.events())
    rerouted = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert rerouted is not None
    assert rerouted.operation.value == "submit_domain_evidence"
    assert rerouted.domain_id == answer.domain_id


def test_complete_no_information_basis_remains_a_qualifying_answer_basis(tmp_path) -> None:
    trial = tmp_path / "input" / "no-information"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:no-information", "trial:no-information")),
    )
    _classify_current_sources(engine, run_id)
    evidence = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert evidence is not None
    question_ids = DOMAINS[evidence.domain_id]
    _complete_empty_receipts(
        engine,
        run_id,
        evidence,
        domain_id=evidence.domain_id,
        question_ids=question_ids,
    )
    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=run_id,
            work_token=evidence.work_token,
            idempotency_key="idempotency:issue114-no-information-evidence",
            result_id=evidence.result_id,
            domain_id=evidence.domain_id,
            coverage_state="complete",
            no_information_basis=True,
        )
    )
    assert (
        engine._evidence_insufficiencies(
            engine._bound_ledger(run_id),
            run_id,
            evidence.result_id,
            {question_id: "no_information" for question_id in question_ids},
            domain_id=evidence.domain_id,
        )
        == ()
    )


def test_complete_with_limitations_evidence_remains_qualifying(tmp_path) -> None:
    trial = tmp_path / "input" / "limited"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:limited", "trial:limited")),
    )
    _classify_current_sources(engine, run_id)
    evidence = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert evidence is not None
    visual_ref = _synthetic_visual_ref(engine, run_id, evidence.result_id)
    question_ids = DOMAINS[evidence.domain_id]
    _complete_empty_receipts(
        engine,
        run_id,
        evidence,
        domain_id=evidence.domain_id,
        question_ids=question_ids,
    )
    engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.2.0",
            run_id=run_id,
            work_token=evidence.work_token,
            idempotency_key="idempotency:issue114-limited-evidence",
            result_id=evidence.result_id,
            domain_id=evidence.domain_id,
            items=(visual_ref,),
            evidence_by_question={question_id: (visual_ref,) for question_id in question_ids},
            candidate_dispositions=(
                {"item_id": visual_ref.entity_id, "disposition": "supporting"},
            ),
            coverage_state="complete_with_limitations",
            coverage_limitations=("Synthetic retained limitation.",),
        )
    )
    assert (
        engine._evidence_insufficiencies(
            engine._bound_ledger(run_id),
            run_id,
            evidence.result_id,
            {question_id: _low_answers()[question_id] for question_id in question_ids},
            domain_id=evidence.domain_id,
        )
        == ()
    )


def test_wrong_scope_visual_transcription_is_unresolvable_evidence(tmp_path, monkeypatch) -> None:
    trial = tmp_path / "input" / "wrong-visual"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path, config=_config(_result("result:wrong-visual", "trial:wrong-visual"))
    )
    _classify_current_sources(engine, run_id)
    evidence = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert evidence is not None
    visual_ref = _synthetic_visual_ref(engine, run_id, evidence.result_id)
    ledger = engine._bound_ledger(run_id)
    wrong_ref = visual_ref.model_copy(update={"entity_id": "visual-transcription:wrong-scope"})
    # A persisted Bundle may point to an obsolete/wrong-scope transcription;
    # build that historical shape directly, then replay the terminal guard.
    manifest = EvidenceConsiderationManifest.model_validate(
        {
            "entity_id": "evidence-manifest:wrong-visual",
            "revision_id": "revision:wrong-visual-manifest",
            "dependencies": (
                Dependency(**wrong_ref.model_dump(), role="dependency:considered-item"),
            ),
            "actor": {"kind": "system", "actor_id": "actor:test", "display_name": "test"},
            "observed_at": engine._now(),
            "sq_id": DOMAINS[evidence.domain_id][0],
            "considered_items": (wrong_ref,),
            "dispositions": [{"item_id": wrong_ref.entity_id, "disposition": "supporting"}],
        }
    )
    manifest_artifact = ledger.artifacts.put(
        manifest.model_dump_json().encode(), "application/json"
    )
    manifest_ref = RecordReference(
        entity_id=manifest.entity_id,
        revision_id=manifest.revision_id,
        content_hash=manifest_artifact.content_hash,
    )
    result_spec_ref = engine._result_spec_reference(ledger, run_id, evidence.result_id)
    bundle = EvidenceBundle.model_validate(
        {
            "entity_id": "bundle:wrong-visual",
            "revision_id": "revision:wrong-visual",
            "dependencies": (
                Dependency(**result_spec_ref.model_dump(), role="dependency:result-spec"),
                Dependency(**result_spec_ref.model_dump(), role="dependency:evidence-disposition"),
                Dependency(**wrong_ref.model_dump(), role="dependency:evidence-item"),
                Dependency(**manifest_ref.model_dump(), role="dependency:evidence-consideration"),
            ),
            "actor": {"kind": "system", "actor_id": "actor:test", "display_name": "test"},
            "observed_at": engine._now(),
            "result_spec": result_spec_ref,
            "disposition": result_spec_ref,
            "items": (wrong_ref,),
            "frozen_content_hash": "sha256:" + "0" * 64,
            "sq_id": DOMAINS[evidence.domain_id][0],
            "domain_id": evidence.domain_id,
            "consideration_manifest": manifest_ref,
        }
    )
    bundle_artifact = ledger.artifacts.put(bundle.model_dump_json().encode(), "application/json")
    bundle_ref = RecordReference(
        entity_id=bundle.entity_id,
        revision_id=bundle.revision_id,
        content_hash=bundle_artifact.content_hash,
    )
    monkeypatch.setattr(
        engine,
        "_latest_domain_evidence_payload",
        lambda *_args, **_kwargs: {"evidence_bundles": (bundle_ref.model_dump(mode="json"),)},
    )
    insufficiencies = engine._evidence_insufficiencies(
        ledger,
        run_id,
        evidence.result_id,
        {DOMAINS[evidence.domain_id][0]: "no"},
        domain_id=evidence.domain_id,
    )
    assert insufficiencies[0].reason.value == "unresolvable_evidence"


def test_legacy_unsupported_answers_become_diagnostic_without_terminal_judgments(
    tmp_path, monkeypatch
) -> None:
    """Replay pre-fix public answer checkpoints against the authoritative terminal guard."""

    trial = tmp_path / "input" / "legacy-terminal"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:legacy-terminal", "trial:legacy-terminal")),
    )
    _classify_current_sources(engine, run_id)
    real_insufficiencies = engine._evidence_insufficiencies

    def legacy_submission_compatibility(*args, **kwargs):
        if kwargs.get("domain_id") is not None:
            return ()
        return real_insufficiencies(*args, **kwargs)

    monkeypatch.setattr(engine, "_evidence_insufficiencies", legacy_submission_compatibility)
    result_id = "result:legacy-terminal"
    active_question_ids: set[str] = set()
    for index, domain_id in enumerate(DOMAINS):
        evidence = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
        assert evidence is not None
        # Complete, unlimited coverage with no items and no_information_basis
        # reproduces the pre-#127/#128 "empty but accepted" evidence shape:
        # coverage_state="incomplete" would instead trip the coverage-unresolved
        # diagnostic before ever reaching the per-question missing-evidence
        # check this test exercises.
        _complete_empty_receipts(
            engine, run_id, evidence, domain_id=domain_id, question_ids=DOMAINS[domain_id]
        )
        engine.submit_domain_evidence(
            SubmitDomainEvidenceRequest(
                contract_version="1.2.0",
                run_id=run_id,
                work_token=evidence.work_token,
                idempotency_key=f"idempotency:issue114-legacy-terminal-evidence-{index}",
                result_id=result_id,
                domain_id=domain_id,
                coverage_state="complete",
                no_information_basis=True,
            )
        )
        answer = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
        assert answer is not None
        engine.submit_domain_answers(
            SubmitDomainAnswersRequest(
                contract_version="1.0.0",
                run_id=run_id,
                work_token=answer.work_token,
                idempotency_key=f"idempotency:issue114-legacy-terminal-answers-{index}",
                result_id=result_id,
                domain_id=domain_id,
                answers=tuple(
                    {
                        "question_id": question_id,
                        "answer": _low_answers()[question_id],
                        "rationale": "Pre-fix unsupported answer.",
                    }
                    for question_id in _active_answer_ids(domain_id)
                ),
            )
        )
        active_question_ids.update(_active_answer_ids(domain_id))
    status = engine.run_status(RunStatusRequest(run_id=run_id))
    assert status.result_states[0].state.value == "diagnostic_ready"
    ledger = engine._bound_ledger(run_id)
    diagnostic = next(
        engine._event_payload(ledger, event)
        for event in ledger.events()
        if event.operation == "operation:result-diagnostic-ready"
    )
    assert all(question_id in diagnostic["reason"] for question_id in active_question_ids)
    assert "missing_qualifying_evidence" in diagnostic["reason"]
    assert not any(
        event.operation
        in {
            "operation:decision-trace-derived",
            "operation:algorithmic-judgment-derived",
            "operation:final-judgment-revision",
            "operation:assessment-revision-frozen",
        }
        for event in ledger.events()
    )
