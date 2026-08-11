from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
import yaml

from rob2_kit.application.contracts import (
    ConfirmRunDefinitionRequest,
    ContinueRunRequest,
    GetWorkContextRequest,
    PrepareRunRequest,
    RunOperation,
    RunProposalSelection,
    SubmitProposalDiscoveryReviewRequest,
    SubmitRunProposalRequest,
    SubmitSourceRoleReviewRequest,
)
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.results import ProposalDiscoveryCoverageReceipt
from rob2_kit.domain.revisions import Actor, ActorKind
from rob2_kit.domain.sources import SourceAvailability, SourceProcessing, SourceRole
from rob2_kit.ingestion.project import PageExtraction, ParserResult
from rob2_kit.interfaces.mcp.server import create_server
from tests.test_input_reconciliation import _config, _result
from tests.test_run_proposal import StubParser

OPERATOR = Actor(
    kind=ActorKind.HUMAN,
    actor_id="actor:issue101",
    display_name="Issue 101 operator",
)


class OnePageParser:
    name = "one-page"
    version = "1"

    def parse(
        self,
        data: bytes,
        *,
        ocr_enabled: bool,
        target_pages: tuple[int, ...] | None = None,
    ) -> ParserResult:
        return ParserResult(
            pages=(PageExtraction(page_number=1, width=612, height=792, text=data.decode()),),
            raw_output=data,
        )


class TwoPageParser(OnePageParser):
    name = "two-page"

    def parse(
        self,
        data: bytes,
        *,
        ocr_enabled: bool,
        target_pages: tuple[int, ...] | None = None,
    ) -> ParserResult:
        page_text = data.decode()
        return ParserResult(
            pages=(
                PageExtraction(page_number=1, width=612, height=792, text=page_text),
                PageExtraction(page_number=2, width=612, height=792, text="table 1"),
            ),
            raw_output=data,
        )


def _prepare(
    root: Path,
    *,
    config: dict[str, object],
    parser: object | None = None,
    with_protocol: bool = False,
):
    trial = root / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"Result bearing primary report")
    if with_protocol:
        supplements = trial / "supplements"
        supplements.mkdir()
        (supplements / "protocol.pdf").write_bytes(b"Protocol-defined primary analysis")
    (root / "rob2.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    engine = RunEngine(parser=parser or StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=root, authorized=True))
    assert prepared.proposal is None
    # Source-role review resolves before the proposal (#119), independently
    # of whatever Result-candidate selections each test submits afterward.
    review_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    if review_work is not None and review_work.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW:
        engine.submit_source_role_review(
            SubmitSourceRoleReviewRequest(
                contract_version="1.0.0",
                run_id=prepared.run_id,
                work_token=review_work.work_token,
                idempotency_key="idempotency:issue101-source-review",
                selections=tuple(
                    RunProposalSelection(
                        trial_id=candidate.trial_id, source_id=candidate.source_id, accepted=True
                    )
                    for candidate in prepared.initialization.source_role_candidates
                ),
            )
        )
    while True:
        work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
        if work is None or work.operation is not RunOperation.SUBMIT_PROPOSAL_DISCOVERY_REVIEW:
            break
        assert prepared.initialization is not None
        source = next(
            source
            for trial_item in prepared.initialization.trials
            if trial_item.trial_id == work.trial_id
            for source in trial_item.inventory.sources
            if source.source_id == work.source_id
        )
        context = engine.get_work_context(
            GetWorkContextRequest(run_id=prepared.run_id, work_token=work.work_token)
        )
        assert context.context is not None and context.context.proposal_discovery_policy is not None
        policy = context.context.proposal_discovery_policy
        reviewed_unit_ids: list[str] = []
        for query in policy.pass_queries:
            page = engine.get_work_context(
                GetWorkContextRequest(
                    run_id=prepared.run_id,
                    work_token=work.work_token,
                    proposal_discovery_query=query.canonical_query,
                    proposal_discovery_pass=query.pass_id,
                )
            )
            if page.context and page.context.proposal_discovery_page:
                reviewed_unit_ids.extend(
                    item.canonical_unit_id
                    for item in page.context.proposal_discovery_page.candidates
                )
        for unit_id in dict.fromkeys(reviewed_unit_ids):
            engine.get_work_context(
                GetWorkContextRequest(
                    run_id=prepared.run_id,
                    work_token=work.work_token,
                    proposal_discovery_unit_ids=(unit_id,),
                )
            )
        receipt = ProposalDiscoveryCoverageReceipt(
            receipt_id=f"proposal-discovery-receipt:{work.source_id.removeprefix('source:')}",
            trial_id=work.trial_id,
            source_id=source.source_id,
            parse_id=source.parse_records[0].parse_id,
            source_artifact_hash=source.artifact_hash,
            mode=(
                "target_guided"
                if prepared.initialization.manifest.outcome_target_specs
                else "structure_first"
            ),
            state="no_candidates",
            reviewed_by=OPERATOR,
            reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
            discovery_policy_revision="discovery-policy:1",
            required_passes=policy.required_passes,
            query_passes=policy.required_passes,
            completed_passes=policy.required_passes,
            reviewed_unit_ids=tuple(dict.fromkeys(reviewed_unit_ids)),
            terminal_stopping_reason="Required discovery pass exhausted.",
        )
        reviewed = engine.submit_proposal_discovery_review(
            SubmitProposalDiscoveryReviewRequest(
                contract_version="1.0.0",
                run_id=prepared.run_id,
                work_token=work.work_token,
                idempotency_key=f"idempotency:issue101-discovery:{work.source_id}",
                coverage_receipt=receipt,
            )
        )
        if reviewed.proposal is not None:
            prepared = prepared.model_copy(update={"proposal": reviewed.proposal})
    assert prepared.proposal is not None
    return engine, prepared


def test_exclusion_requires_human_readable_reason() -> None:
    with pytest.raises(ValueError, match="exclusion_reason"):
        RunProposalSelection(
            trial_id="trial:a",
            outcome_target_id="outcome-target:mortality",
            accepted=False,
        )


def test_competing_results_require_explicit_choice_and_emit_successor_diff(
    tmp_path: Path,
) -> None:
    config = _config(
        _result("result:30d", "trial:trial-a"),
        _result("result:90d", "trial:trial-a"),
        with_target=True,
    )
    config["outcome_targets"][0]["timepoint"] = None  # type: ignore[index]
    config["results"][0]["analysis_priority"] = "protocol_primary"  # type: ignore[index]
    config["results"][0]["preference_source_locator"] = "supplements/protocol.pdf"  # type: ignore[index]
    engine, prepared = _prepare(
        tmp_path,
        config=config,
        with_protocol=True,
    )
    assert prepared.proposal is not None
    ambiguity = next(
        item
        for item in prepared.proposal.ambiguities
        if "Multiple Trial-specific Result analyses" in item.detail
    )
    candidates = tuple(
        item
        for item in prepared.proposal.result_candidates
        if item.outcome_target_id == "outcome-target:mortality"
    )
    assert len(candidates) == 2
    pairing = prepared.proposal.pairings()[0]
    assert pairing.preferred_result_id in {item.result_id for item in candidates}
    assert pairing.selection_policy is not None
    assert "prespecified cutoff" in pairing.selection_policy
    with pytest.raises(ValueError, match="select, exclude, or remove"):
        engine.submit_run_proposal(
            SubmitRunProposalRequest(
                contract_version="2.0.0",
                run_id=prepared.run_id,
                proposal_token=prepared.proposal.proposal_token,
                idempotency_key="idempotency:issue101-missing-choice",
            )
        )

    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:issue101-choice",
            selections=(
                RunProposalSelection(
                    trial_id="trial:trial-a",
                    result_id="result:30d",
                    result_candidate_id=candidates[0].candidate_id,
                    outcome_target_id="outcome-target:mortality",
                ),
            ),
            ambiguities=(
                ambiguity.model_copy(
                    update={"resolved": True, "resolution": "Selected the prespecified cutoff."}
                ),
            ),
        )
    )
    assert submitted.proposal is not None
    assert submitted.proposal.supersedes_proposal_id == prepared.proposal.proposal_id
    assert any("disposition changed" in item for item in submitted.proposal.semantic_diff)
    compact = submitted.proposal.compact_payload()
    assert "initialization" not in compact
    assert compact["pairings"][0]["disposition"] == "selected"

    confirmed = engine.confirm_run_definition(
        ConfirmRunDefinitionRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            proposal_token=submitted.proposal.proposal_token,
            idempotency_key="idempotency:issue101-confirm",
            confirmed_by=OPERATOR,
        )
    )
    assert confirmed.run_definition is not None
    assert confirmed.run_definition.result_ids == ("result:30d",)


def test_unreadable_protocol_placeholder_cannot_drive_result_preference(
    tmp_path: Path,
) -> None:
    config = _config(
        _result("result:30d", "trial:trial-a"),
        _result("result:90d", "trial:trial-a"),
        with_target=True,
    )
    config["outcome_targets"][0]["timepoint"] = None  # type: ignore[index]
    config["results"][0]["analysis_priority"] = "protocol_primary"  # type: ignore[index]
    config["results"][0]["preference_source_locator"] = "supplements/protocol.pdf"  # type: ignore[index]
    _, prepared = _prepare(tmp_path, config=config, with_protocol=True)
    assert prepared.proposal is not None
    trial = prepared.proposal.initialization.trials[0]
    sources = tuple(
        source.model_copy(
            update={
                "availability": SourceAvailability.UNAVAILABLE,
                "processing": SourceProcessing.NOT_ATTEMPTED,
                "artifact_hash": None,
                "parse_records": (),
                "coverage": (),
            }
        )
        if SourceRole.PROTOCOL in source.roles
        else source
        for source in trial.inventory.sources
    )
    initialization = prepared.proposal.initialization.model_copy(
        update={
            "trials": (
                trial.model_copy(
                    update={"inventory": trial.inventory.model_copy(update={"sources": sources})}
                ),
            )
        }
    )
    proposal = prepared.proposal.model_copy(update={"initialization": initialization})

    pairing = proposal.pairings()[0]
    assert pairing.preferred_result_id is None
    assert pairing.selection_policy is None


def test_unresolved_outcome_target_cannot_be_silently_dropped(tmp_path: Path) -> None:
    engine, prepared = _prepare(tmp_path, config=_config(with_target=True))
    assert prepared.proposal is not None
    with pytest.raises(ValueError, match="select, exclude, or remove"):
        engine.submit_run_proposal(
            SubmitRunProposalRequest(
                contract_version="2.0.0",
                run_id=prepared.run_id,
                proposal_token=prepared.proposal.proposal_token,
                idempotency_key="idempotency:issue101-drop",
            )
        )


def test_explicit_exclusion_is_bound_to_the_latest_proposal(tmp_path: Path) -> None:
    engine, prepared = _prepare(
        tmp_path, config=_config(_result("result:declared", "trial:trial-a"), with_target=True)
    )
    assert prepared.proposal is not None
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:issue101-explicit-exclusion",
            selections=(
                RunProposalSelection(
                    trial_id="trial:trial-a",
                    outcome_target_id="outcome-target:mortality",
                    accepted=False,
                    exclusion_reason="outside scope",
                ),
            ),
        )
    )
    assert submitted.proposal is not None
    assert submitted.proposal.pairings()[0].disposition == "excluded"


def test_natural_language_correction_creates_complete_successor_and_rejects_unknown_ids(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        SubmitRunProposalRequest.model_validate(
            {
                "contract_version": "2.0.0",
                "run_id": "run:a",
                "proposal_token": "proposal-token:a",
                "idempotency_key": "idempotency:a",
                "correction": "exclude",
            }
        )


def test_successive_natural_language_corrections_preserve_unaffected_dispositions(
    tmp_path: Path,
) -> None:
    selection = RunProposalSelection(
        trial_id="trial:trial-a",
        outcome_target_id="outcome-target:mortality",
        accepted=False,
        exclusion_reason="outside scope",
    )
    assert selection.accepted is False


def test_bounded_natural_correction_accepts_pairing_first_phrasing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        SubmitRunProposalRequest.model_validate(
            {
                "contract_version": "2.0.0",
                "run_id": "run:a",
                "proposal_token": "proposal-token:a",
                "idempotency_key": "idempotency:a",
                "correction": "select",
            }
        )


def test_natural_language_removal_is_a_null_result_disposition(tmp_path: Path) -> None:
    selection = RunProposalSelection(
        trial_id="trial:trial-a",
        outcome_target_id="outcome-target:mortality",
        accepted=False,
        removed=True,
        exclusion_reason="removed",
    )
    assert selection.removed


def test_natural_language_exclusion_resolves_a_competing_pairing(tmp_path: Path) -> None:
    selection = RunProposalSelection(
        trial_id="trial:trial-a",
        outcome_target_id="outcome-target:mortality",
        accepted=False,
        exclusion_reason="outside scope",
    )
    assert selection.exclusion_reason == "outside scope"


def test_natural_language_candidate_selection_resolves_without_regex_crash(tmp_path: Path) -> None:
    selection = RunProposalSelection(
        trial_id="trial:trial-a",
        outcome_target_id="outcome-target:mortality",
        result_id="result:selected",
        result_candidate_id="result-candidate:selected",
        accepted=True,
    )
    assert selection.result_candidate_id == "result-candidate:selected"


def test_production_one_page_report_can_bind_an_exact_result_locator(tmp_path: Path) -> None:
    engine, prepared = _prepare(
        tmp_path,
        config=_config(_result("result:one-page", "trial:trial-a"), with_target=True),
        parser=OnePageParser(),
    )
    assert prepared.proposal is not None
    submitted = engine.submit_run_proposal(
        SubmitRunProposalRequest(
            contract_version="2.0.0",
            run_id=prepared.run_id,
            proposal_token=prepared.proposal.proposal_token,
            idempotency_key="idempotency:issue101-one-page",
            selections=(
                RunProposalSelection(
                    trial_id="trial:trial-a",
                    outcome_target_id="outcome-target:mortality",
                    result_id="result:one-page",
                    accepted=True,
                ),
            ),
        )
    )
    assert submitted.proposal is not None
    assert submitted.proposal.pairings()[0].result_id == "result:one-page"


def test_production_multi_page_report_requires_page_bound_locator(tmp_path: Path) -> None:
    result = _result("result:unbound-provenance", "trial:trial-a")
    result["result"]["source_locator"] = "report.pdf"  # type: ignore[index]
    engine, prepared = _prepare(
        tmp_path,
        config=_config(result, with_target=True),
        parser=TwoPageParser(),
    )
    assert prepared.proposal is not None
    with pytest.raises(ValueError, match="sufficiently readable"):
        engine.submit_run_proposal(
            SubmitRunProposalRequest(
                contract_version="2.0.0",
                run_id=prepared.run_id,
                proposal_token=prepared.proposal.proposal_token,
                idempotency_key="idempotency:issue101-unbound-provenance",
                selections=(
                    RunProposalSelection(
                        trial_id="trial:trial-a",
                        outcome_target_id="outcome-target:mortality",
                        result_id="result:unbound-provenance",
                        accepted=True,
                    ),
                ),
            )
        )


def test_real_mcp_registers_all_preconfirmation_route_names() -> None:
    names = {tool.name for tool in anyio.run(create_server().list_tools)}

    assert {
        "prepare_run",
        "submit_source_role_review",
        "submit_result_resolution",
        "submit_run_proposal",
        "confirm_run_definition",
    } <= names
