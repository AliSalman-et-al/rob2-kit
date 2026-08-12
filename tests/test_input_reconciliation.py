from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import yaml

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    GetWorkContextRequest,
    PrepareRunRequest,
    RunOperation,
    RunProposalSelection,
    RunStatusRequest,
    SubmitResultResolutionRequest,
    SubmitRunProposalRequest,
    SubmitSourceRoleReviewRequest,
)
from rob2_kit.application.lifecycle import RunState
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.results import Estimate, Result
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.evidence.search import (
    EvidenceScope,
    EvidenceSearchIndex,
)
from rob2_kit.ingestion.project import PageExtraction, PageTextItem, ParserResult
from tests.test_run_proposal import StubParser, _first_proposal

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


def _low_answers() -> dict[str, str]:
    return {question_id: "no" for question_ids in DOMAINS.values() for question_id in question_ids}


def _active_answer_ids(domain_id: str) -> tuple[str, ...]:
    return DOMAINS[domain_id]


OPERATOR = Actor(
    kind=ActorKind.HUMAN,
    actor_id="actor:reconciliation-test",
    display_name="Reconciliation test operator",
)


def _result(result_id: str, trial_id: str) -> dict[str, object]:
    return {
        "result": {
            "result_id": result_id,
            "trial_id": trial_id,
            "randomization_id": f"randomization:{trial_id}",
            "comparison": {
                "experimental_arm_id": "arm:experimental",
                "comparator_arm_id": "arm:control",
            },
            "effect_of_interest": "assignment",
            "outcome_construct": "mortality",
            "measurement_instrument": "all-cause",
            "time_point": "30 days",
            "analysis_population": "intention-to-treat",
            "analysis_model": "risk ratio",
            "effect_measure": "risk_ratio",
            "source_locator": "report:primary/table:1",
        },
        "estimate": {"value": 0.8},
        "provenance_note": "reconciliation fixture",
    }


def _config(*results: dict[str, object], with_target: bool | None = None) -> dict[str, object]:
    # Declared Result fixtures represent an explicit requested Outcome target
    # unless a test intentionally builds an empty project.  This keeps legacy
    # reconciliation journeys aligned with the strict Trial × Outcome
    # confirmation contract instead of relying on implicit result-ID fallback.
    if with_target is None:
        with_target = bool(results)
    payload: dict[str, object] = {
        "schema_version": 1,
        "acquisition": {"clinicaltrials_gov": False},
        "results": list(results),
    }
    if with_target:
        payload["outcome_targets"] = [
            {
                "id": "mortality",
                "label": "mortality",
                "construct": "mortality",
                "timepoint": "30 days",
            }
        ]
    return payload


class StructuredPassageParser:
    name = "structured-passage-fixture"
    version = "1"

    def parse(self, data: bytes, *, ocr_enabled: bool, target_pages=None) -> ParserResult:
        text = data.decode()
        return ParserResult(
            pages=(
                PageExtraction(
                    page_number=1,
                    width=612,
                    height=792,
                    text=text,
                    markdown=text,
                    text_items=(
                        PageTextItem(
                            text=text,
                            x=10,
                            y=20,
                            width=200,
                            height=12,
                            unit_kind="paragraph",
                            document_zone="main",
                        ),
                    ),
                ),
            ),
            raw_output=data,
        )


def _prepare_confirm(
    root: Path,
    *,
    config: dict[str, object],
    parser: object | None = None,
) -> tuple[RunEngine, str]:
    config_payload = dict(config)
    (root / "rob2.yaml").write_text(yaml.safe_dump(config_payload), encoding="utf-8")
    engine = RunEngine(parser=parser or StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=root, authorized=True))
    prepared = _first_proposal(engine, prepared)
    assert prepared.proposal is not None
    # A Result candidate is never auto-bound by cardinality alone (#119): even
    # a sole "resolved" candidate needs an explicit accepted selection, so
    # this helper always emits one rather than relying on any implicit
    # single-candidate fallback.
    selections = tuple(
        RunProposalSelection(
            trial_id=candidate.trial_id,
            outcome_target_id=candidate.outcome_target_id,
            result_id=candidate.result_id,
            result_candidate_id=candidate.candidate_id,
            accepted=True,
        )
        for candidate in prepared.proposal.result_candidates
        if candidate.status in ("needs_input", "resolved") and candidate.result_id is not None
    )
    if not selections:
        # Empty declared inventories still need an explicit Trial × Outcome
        # disposition before confirmation.  Keeping the Trial in scope
        # deliberately exercises the later structured Result-resolution path.
        selections = tuple(
            RunProposalSelection(
                trial_id=trial.trial_id,
                outcome_target_id=target.target_id,
                accepted=False,
                exclusion_reason="No exact Result is available at proposal time.",
            )
            for trial in prepared.proposal.initialization.trials
            for target in prepared.proposal.outcome_targets
        )
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:reconciliation-proposal",
            selections=selections,
        )
    )
    engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:reconciliation-confirmation",
            confirmed_by=OPERATOR,
        )
    )
    return engine, prepared.run_id


def _classify_current_sources(engine: RunEngine, run_id: str) -> None:
    """Complete a pending Source-role review work item, if one remains.

    Most callers' sources are already reviewed pre-confirmation inside
    ``_prepare_confirm`` (#119), so this is a no-op then. A source that
    only appears (or changes) after confirmation, via reconciliation,
    still surfaces its own post-confirmation review work item here.
    """

    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    if work is None or work.operation is not RunOperation.SUBMIT_SOURCE_ROLE_REVIEW:
        return
    context = engine.get_work_context(
        GetWorkContextRequest(run_id=run_id, work_token=work.work_token)
    ).context
    assert context is not None
    assert context.detailed_sources == ()
    assert all(source.page_count >= 0 for source in context.sources)
    proposal = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    context_source_ids = {source.source_id for source in context.sources}
    response = engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key=(
                "idempotency:reconciliation-sources:"
                f"{work.work_token.token.removeprefix('work-token:')}"
            ),
            selections=tuple(
                RunProposalSelection(
                    trial_id=candidate.trial_id, source_id=candidate.source_id, accepted=True
                )
                for candidate in proposal.initialization.source_role_candidates
                if candidate.source_id in context_source_ids
            ),
        )
    )
    assert response.committed is True, response


def test_unstructured_units_remain_visible_for_attributable_review(tmp_path: Path) -> None:
    from rob2_kit.evidence.search import CanonicalEvidenceUnit, CanonicalUnitKind, DocumentZone

    index = EvidenceSearchIndex(tmp_path / "evidence.sqlite3")
    unit = CanonicalEvidenceUnit(
        unit_id="unit:unstructured",
        source_id="source:report",
        source_artifact_hash="sha256:" + "a" * 64,
        parse_id="parse:report",
        page=1,
        kind=CanonicalUnitKind.UNCLASSIFIED,
        text="unstructured prose",
        document_zone=DocumentZone.UNKNOWN,
    )
    index.replace_units((unit,))
    assert (
        index.read_unit(
            unit.unit_id,
            scope=EvidenceScope(trial_id="trial:active", result_id="result:active"),
        )
        == unit
    )


def test_execution_contract_change_records_attempt_and_invalidates_declared_results(
    tmp_path: Path, monkeypatch
) -> None:
    trial = tmp_path / "input" / "contract"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:contract", "trial:contract")),
    )
    _classify_current_sources(engine, run_id)
    baseline = engine._installed_execution_contract()
    initialization_only = baseline.model_copy(
        update={
            "identity": "sha256:" + ("b" * 64),
            "components": {
                **baseline.components,
                "initialization-skill": "sha256:" + ("c" * 64),
            },
        }
    )
    monkeypatch.setattr(engine, "_installed_execution_contract", lambda: initialization_only)

    preserved = engine.continue_run(ContinueRunRequest(run_id=run_id))

    assert preserved.work_item is not None
    assert not any(
        event.operation == "operation:result-invalidated"
        for event in engine._bound_ledger(run_id).events()
    )
    logic_changed = initialization_only.model_copy(
        update={
            "identity": "sha256:" + ("d" * 64),
            "components": {
                **initialization_only.components,
                "logic-pack": "sha256:" + ("e" * 64),
            },
        }
    )
    monkeypatch.setattr(engine, "_installed_execution_contract", lambda: logic_changed)

    resumed = engine.continue_run(ContinueRunRequest(run_id=run_id))
    events = engine._bound_ledger(run_id).events()

    assert resumed.work_item is not None
    assert resumed.work_item.result_id == "result:contract"
    attempts = tuple(
        event for event in events if event.operation == "operation:preparation-attempt-superseded"
    )
    prepared_event = next(event for event in events if event.operation == "operation:run-prepared")
    assert len(attempts) == 2
    assert attempts[0].supersedes_revision_id == prepared_event.revision_id
    assert attempts[1].supersedes_revision_id == attempts[0].revision_id
    assert [
        event.scope for event in events if event.operation == "operation:result-invalidated"
    ] == ["result:contract"]


def test_prepare_run_reports_integrity_failure_when_project_ownership_identity_drifts(
    tmp_path: Path,
) -> None:
    """A project's recorded ownership manifest that no longer matches the
    installed release stops new Run mutations for that project rather than
    silently proceeding."""

    (tmp_path / "rob2.lock").write_text(
        json.dumps({"identities": {"engine": {"version": "not-the-installed-version"}}}),
        encoding="utf-8",
    )
    engine = RunEngine(parser=StubParser())

    response = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))

    assert response.run_state == RunState.INTEGRITY_FAILED


def test_prepare_run_ignores_ownership_verification_without_a_recorded_manifest(
    tmp_path: Path,
) -> None:
    """A dev/source checkout with no bootstrapped ownership manifest has
    nothing recorded to verify the installed release against, so preparation
    proceeds normally."""

    trial = tmp_path / "input" / "no-manifest"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:no-manifest", "trial:no-manifest")),
    )

    assert engine._ownership_verified is True
    resumed = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert resumed.run_state != RunState.INTEGRITY_FAILED


def test_resolved_outcome_candidate_survives_unrelated_source_change(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    support = trial / "supplements" / "support.pdf"
    support.parent.mkdir()
    support.write_bytes(b"support")
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(_config(with_target=True)), encoding="utf-8")
    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    prepared = _first_proposal(engine, prepared)
    assert prepared.proposal is not None
    # Source text is no longer allowed to synthesize an Outcome/Result identity
    # at initialization.  The new discovery operation records observations
    # first; a human promotion and mapping review produce later candidates.
    assert prepared.proposal.result_candidates == ()


def test_post_confirmation_result_resolution_keeps_source_dependency_on_change(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    support = trial / "supplements" / "support.pdf"
    support.parent.mkdir()
    support.write_bytes(b"support")
    engine, run_id = _prepare_confirm(tmp_path, config=_config())
    _classify_current_sources(engine, run_id)
    resolution_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert resolution_work is not None
    assert resolution_work.result_id is not None
    resolved_result = Result.model_validate(
        _result(resolution_work.result_id, "trial:trial-a")["result"]
    ).model_copy(update={"source_locator": "supplements/support.pdf"})
    engine.submit_result_resolution(
        SubmitResultResolutionRequest(
            contract_version="1.0.0",
            run_id=run_id,
            work_token=resolution_work.work_token,
            idempotency_key="idempotency:reconciliation-resolution",
            result=resolved_result,
            estimate=Estimate(value=Decimal("0.8")),
            provenance_note="resolved in reconciliation fixture",
        )
    )
    support.write_bytes(b"changed support")

    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.run_state is RunState.ASSESSING
    assert continued.work_item is not None
    assert continued.work_item.result_id == resolution_work.result_id
    assert continued.work_item.operation.value == "submit_question_step"
    assert any(
        event.operation == "operation:result-invalidated"
        and event.scope == resolution_work.result_id
        for event in engine._bound_ledger(run_id).events()
    )


def test_identical_scan_is_noop_and_content_preserving_move_keeps_source_id(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    (trial / "supplements" / "support.pdf").write_bytes(b"support")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    proposal = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    support = next(
        source
        for source in proposal.initialization.trials[0].inventory.sources
        if source.relative_path != "report.pdf"
    )
    _classify_current_sources(engine, run_id)
    before = len(engine._bound_ledger(run_id).events())
    (trial / "other").mkdir()
    shutil.move(
        str(trial / "supplements" / "support.pdf"),
        str(trial / "other" / "moved.pdf"),
    )
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.work_item is not None
    assert continued.work_item.operation.value == "submit_question_step"
    refreshed = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    moved = next(
        source
        for source in refreshed.initialization.trials[0].inventory.sources
        if source.relative_path == "other/moved.pdf"
    )
    assert moved.source_id == support.source_id
    after_move = len(engine._bound_ledger(run_id).events())
    assert after_move > before
    repeated = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert repeated.committed is False
    assert len(engine._bound_ledger(run_id).events()) == after_move


def test_content_preserving_trial_folder_move_keeps_trial_and_source_ids(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    before = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    before_trial = before.initialization.trials[0]
    before_source = before_trial.inventory.sources[0]

    shutil.move(str(trial), str(tmp_path / "input" / "trial-renamed"))
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.work_item is not None
    refreshed = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    current_trial = refreshed.initialization.trials[0]
    current_source = current_trial.inventory.sources[0]

    assert current_trial.trial_id == before_trial.trial_id
    assert current_source.source_id == before_source.source_id
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None
    assert definition.trial_ids == (before_trial.trial_id,)


def test_trial_folder_move_with_changed_bytes_blocks_identity_guess(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    report = trial / "report.pdf"
    report.write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None
    renamed = tmp_path / "input" / "trial-renamed"
    shutil.move(str(trial), str(renamed))
    (renamed / "report.pdf").write_bytes(b"changed primary")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    assert engine._confirmed_definition(engine._bound_ledger(run_id), run_id) == definition


def test_trial_path_replacement_conflict_blocks_hash_identity_guess(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"old primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    renamed = tmp_path / "input" / "trial-z"
    shutil.move(str(trial), str(renamed))
    replacement = tmp_path / "input" / "trial-a"
    replacement.mkdir()
    (replacement / "report.pdf").write_bytes(b"new primary")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"


def test_renamed_trial_with_same_content_copy_blocks_duplicate_identity_mapping(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None
    renamed = tmp_path / "input" / "trial-z"
    shutil.move(str(trial), str(renamed))
    copied = tmp_path / "input" / "trial-a-new"
    copied.mkdir()
    shutil.copy2(renamed / "report.pdf", copied / "report.pdf")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    assert engine._confirmed_definition(engine._bound_ledger(run_id), run_id) == definition


def test_source_path_replacement_conflict_blocks_hash_identity_guess(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    support = trial / "supplements" / "a.pdf"
    support.write_bytes(b"old support")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    moved = trial / "moved" / "a.pdf"
    moved.parent.mkdir()
    shutil.move(str(support), str(moved))
    support.write_bytes(b"new support")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"


def test_compatible_added_trial_gets_only_new_result_work(tmp_path: Path) -> None:
    first = tmp_path / "input" / "trial-a"
    first.mkdir(parents=True)
    (first / "report.pdf").write_bytes(b"primary a")
    config = _config(_result("result:a", "trial:trial-a"), with_target=True)
    engine, run_id = _prepare_confirm(tmp_path, config=config)
    added = tmp_path / "input" / "trial-b"
    added.mkdir()
    (added / "report.pdf").write_bytes(b"primary b")
    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.work_item is not None
    _classify_current_sources(engine, run_id)
    resolution = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert resolution is not None
    assert resolution.operation.value == "submit_result_resolution"
    assert resolution.trial_id == "trial:trial-b"
    assert resolution.result_id is not None


def test_added_failed_trial_gets_terminal_diagnostic_without_resolution_work(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    (tmp_path / "input" / "trial-b").mkdir()

    first = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert first.work_item is not None
    events = engine._bound_ledger(run_id).events()
    assert any(event.operation == "operation:run-register-diagnostic-result" for event in events)
    assert any(event.operation == "operation:result-diagnostic-ready" for event in events)
    run_index_path = next((tmp_path / "output" / "report-bundle").rglob("run-index.json"))
    run_index = json.loads(run_index_path.read_text(encoding="utf-8"))
    diagnostic_row = next(
        item for item in run_index["results"] if item["result_id"].startswith("result:diagnostic-")
    )
    assert diagnostic_row["trial_id"] == "trial:trial-b"
    assert diagnostic_row["outcome"] == ""
    diagnostic_root = run_index_path.parent / diagnostic_row["report"].replace(
        "diagnostic.html", ""
    )
    diagnostic = json.loads((diagnostic_root / "diagnostic.json").read_text(encoding="utf-8"))
    assert diagnostic["preparation_outcome"] == "trial_failed"
    assert diagnostic["recovery"] == [
        "Restore the required readable Trial Source and continue the Run."
    ]
    _classify_current_sources(engine, run_id)
    next_work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert next_work is not None
    assert next_work.result_id == "result:a"


def test_initial_failed_trial_publishes_a_recoverable_diagnostic(tmp_path: Path) -> None:
    (tmp_path / "input" / "trial-failed").mkdir(parents=True)
    (tmp_path / "rob2.yaml").write_text(
        yaml.safe_dump(_config(with_target=False)), encoding="utf-8"
    )

    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))

    events = engine._bound_ledger(prepared.run_id).events()
    diagnostic_event = next(
        event for event in events if event.operation == "operation:result-diagnostic-ready"
    )
    diagnostic_record = json.loads(
        engine._bound_ledger(prepared.run_id).artifacts.read(
            diagnostic_event.output_revision_hashes[0]
        )
    )
    assert diagnostic_record["preparation_outcome"] == "trial_failed"
    assert diagnostic_record["recovery"] == [
        "Provide the required readable Trial Source and continue the Run."
    ]


def test_recovering_failed_trial_with_primary_addition_reopens_assessment(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    assert engine.continue_run(ContinueRunRequest(run_id=run_id)).run_state is RunState.COMPLETE
    (trial / "report.pdf").write_bytes(b"primary")

    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.run_state is RunState.ASSESSING
    assert continued.work_item is not None
    assert continued.work_item.operation.value == "submit_source_role_review"
    assert not any(
        event.operation == "operation:run-blocked"
        for event in engine._bound_ledger(run_id).events()
    )


def test_material_reconciliation_blocks_diagnostic_only_run_without_integrity_failure(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    assert engine.continue_run(ContinueRunRequest(run_id=run_id)).run_state is RunState.COMPLETE
    (trial / "first.pdf").write_bytes(b"first")
    (trial / "second.pdf").write_bytes(b"second")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    assert not any(
        event.operation == "operation:run-completed"
        and event.sequence
        > max(
            item.sequence
            for item in engine._bound_ledger(run_id).events()
            if item.operation == "operation:run-blocked"
        )
        for event in engine._bound_ledger(run_id).events()
    )


def test_changed_support_only_invalidates_results_that_cite_it(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    support = trial / "supplements" / "supplement.pdf"
    support.write_bytes(b"support")
    (trial / "trial.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "documents": [
                    {
                        "path": "supplements/supplement.pdf",
                        "roles": ["clinical_study_report"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    first = _result("result:a", "trial:trial-a")
    first["result"]["source_locator"] = "report.pdf p. 1"
    second = _result("result:b", "trial:trial-a")
    second["result"]["outcome_construct"] = "morbidity"
    second["result"]["source_locator"] = "supplements/supplement.pdf p. 1"
    config = _config(first, second)
    config["outcome_targets"].append(
        {"id": "morbidity", "label": "morbidity", "construct": "morbidity", "timepoint": "30 days"}
    )
    engine, run_id = _prepare_confirm(tmp_path, config=config)
    _classify_current_sources(engine, run_id)
    support.write_bytes(b"changed support")

    engine.continue_run(ContinueRunRequest(run_id=run_id))
    invalidated = {
        event.scope
        for event in engine._bound_ledger(run_id).events()
        if event.operation == "operation:result-invalidated"
    }
    assert invalidated == {"result:b"}


def test_result_declaration_edits_block_without_rewriting_confirmed_definition(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    original = _config(_result("result:a", "trial:trial-a"))
    engine, run_id = _prepare_confirm(tmp_path, config=original)
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None

    changed = _config(_result("result:a", "trial:trial-a"))
    changed["results"][0]["estimate"]["value"] = 0.9
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(changed), encoding="utf-8")
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert engine._confirmed_definition(engine._bound_ledger(run_id), run_id) == definition

    added = _config(
        _result("result:a", "trial:trial-a"),
        _result("result:b", "trial:trial-a"),
    )
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(added), encoding="utf-8")
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert "added to an existing confirmed Trial" in blocked.error.detail

    removed = _config(with_target=True)
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(removed), encoding="utf-8")
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None

    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(original), encoding="utf-8")
    resumed = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert resumed.run_state is RunState.ASSESSING


def test_material_semantic_drift_blocks_then_unblocks_after_correction(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    config = _config(_result("result:a", "trial:trial-a"))
    engine, run_id = _prepare_confirm(tmp_path, config=config)
    changed = _config(_result("result:a", "trial:trial-a"))
    changed["rob2"] = {"effect_of_interest": "hypothetical"}
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(changed), encoding="utf-8")
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    resumed = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert resumed.run_state is RunState.ASSESSING


def test_deleted_trial_is_retired_from_active_status_but_history_remains(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    shutil.rmtree(trial)
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    status = engine.run_status(RunStatusRequest(run_id=run_id))
    assert status.result_states == ()
    assert any(
        event.operation == "operation:run-register-result" and event.scope == "result:a"
        for event in engine._bound_ledger(run_id).events()
    )


def test_retired_run_does_not_reconcile_later_input_changes(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    report = trial / "report.pdf"
    report.write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    replacement = engine.prepare_run(
        PrepareRunRequest(project_root=tmp_path, authorized=True, start_new=True)
    )
    assert replacement.run_id != run_id
    before = len(engine._bound_ledger(run_id).events())
    report.write_bytes(b"changed primary")

    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.run_state is RunState.RETIRED
    assert len(engine._bound_ledger(run_id).events()) == before


def test_unreadable_input_snapshot_is_a_durable_material_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )

    def fail_snapshot(_: Path) -> str:
        raise ValueError("project input symlinks are not permitted")

    monkeypatch.setattr(RunEngine, "_input_snapshot_hash", staticmethod(fail_snapshot))
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    assert any(
        event.operation == "operation:run-blocked"
        for event in engine._bound_ledger(run_id).events()
    )


def test_ambiguous_source_move_blocks_without_rewriting_confirmed_definition(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    (trial / "supplements" / "first.pdf").write_bytes(b"duplicate")
    (trial / "supplements" / "second.pdf").write_bytes(b"duplicate")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None
    (trial / "moved").mkdir()
    shutil.move(str(trial / "supplements" / "first.pdf"), str(trial / "moved" / "one.pdf"))
    shutil.move(str(trial / "supplements" / "second.pdf"), str(trial / "moved" / "two.pdf"))
    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    current = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert current == definition


def test_source_move_with_same_content_copy_blocks_duplicate_identity_mapping(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    source = trial / "supplements" / "z.pdf"
    source.write_bytes(b"same content")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    definition = engine._confirmed_definition(engine._bound_ledger(run_id), run_id)
    assert definition is not None
    (trial / "moved").mkdir()
    shutil.move(str(source), str(trial / "moved" / "z.pdf"))
    copied = trial / "aaa" / "copy.pdf"
    copied.parent.mkdir()
    copied.write_bytes(b"same content")

    blocked = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert blocked.run_state is RunState.BLOCKED
    assert blocked.error is not None
    assert blocked.error.code == "material_ambiguity"
    assert engine._confirmed_definition(engine._bound_ledger(run_id), run_id) == definition


def test_added_same_content_source_does_not_steal_existing_path_identity(
    tmp_path: Path,
) -> None:
    trial = tmp_path / "input" / "trial-a"
    (trial / "supplements").mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    source = trial / "supplements" / "z.pdf"
    source.write_bytes(b"same content")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:a", "trial:trial-a")),
    )
    before = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    before_source = next(
        item
        for item in before.initialization.trials[0].inventory.sources
        if item.relative_path == "supplements/z.pdf"
    )
    copied = trial / "aaa" / "copy.pdf"
    copied.parent.mkdir()
    copied.write_bytes(b"same content")

    continued = engine.continue_run(ContinueRunRequest(run_id=run_id))
    assert continued.work_item is not None
    refreshed = engine._latest_proposal(engine._bound_ledger(run_id), run_id)
    current_sources = {
        item.relative_path: item for item in refreshed.initialization.trials[0].inventory.sources
    }
    assert current_sources["supplements/z.pdf"].source_id == before_source.source_id
    assert current_sources["aaa/copy.pdf"].source_id != before_source.source_id
