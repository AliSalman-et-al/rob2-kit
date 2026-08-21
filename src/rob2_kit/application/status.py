"""Restart-safe status derived from verified durable application state."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
from pathlib import Path

from ._state import identity, read_json, record_uri
from .acknowledgments import verify_acknowledgment
from .contracts import (
    ApproveBatchContinuation,
    AuthoritativePresentation,
    CaptureBatchContinuation,
    Continuation,
    FinalizeBatchContinuation,
    FinishTrialContinuation,
    PreflightSourcesContinuation,
    RecordKind,
    RecordReference,
    ResearcherReviewContinuation,
    ReviewAcknowledgmentReference,
    ReviewAuthority,
    ReviewAuthorityRequirement,
    SaveIntakePlanContinuation,
    SaveProposalContinuation,
    TransitionReference,
    TrialDisposition,
    ValidateDomainJudgmentContinuation,
    VerifiedCondition,
    VerifiedCurrentStatus,
    WorkflowPhase,
)


def _record(kind: RecordKind, identity: object) -> RecordReference | None:
    if not isinstance(identity, str):
        return None
    try:
        return RecordReference(kind=kind, identity=identity, uri=record_uri(kind.value, identity))
    except ValueError:
        return None


def _condition(code: str, detail: str) -> tuple[VerifiedCondition, ...]:
    return (VerifiedCondition(code=code, detail=detail),)


def _status(
    phase: WorkflowPhase,
    code: str,
    headline: str,
    summary: str,
    *,
    review: ReviewAuthorityRequirement,
    continuation: Continuation | None = None,
    trials: tuple[tuple[str, TrialDisposition], ...] = (),
    domains: tuple[tuple[str, tuple[str, ...]], ...] = (),
    conditions: tuple[VerifiedCondition, ...] = (),
) -> VerifiedCurrentStatus:
    return VerifiedCurrentStatus(
        phase=phase,
        trial_dispositions=trials,
        committed_domains=domains,
        conditions=conditions,
        review=review,
        continuation=continuation,
        presentation=AuthoritativePresentation(code=code, headline=headline, summary=summary),
    )


def _empty() -> VerifiedCurrentStatus:
    return _status(
        WorkflowPhase.EMPTY,
        "empty",
        "No active Batch",
        "No source preflight or Captured Batch exists.",
        review=ReviewAuthorityRequirement(required=ReviewAuthority.NONE, satisfied=True),
        continuation=PreflightSourcesContinuation(),
    )


def _captured_bytes_verified(workspace: str | Path, state: dict[str, object]) -> bool:
    captured = read_json(workspace, "captured_batch.json")
    if (
        captured is None
        or captured.get("identity") != state.get("captured_identity")
        or not isinstance(captured.get("sources"), list)
    ):
        return False
    root = Path(workspace).resolve(strict=True)
    batch_dir = (
        root / ".rob2-kit" / "sources-v3" / str(state["captured_identity"]).removeprefix("sha256:")
    )
    if not batch_dir.is_dir() or batch_dir.is_symlink():
        return False
    for source in captured["sources"]:
        if not isinstance(source, dict) or not all(
            isinstance(source.get(key), str) for key in ("trial_id", "candidate_identity", "sha256")
        ):
            return False
        path = batch_dir / source["trial_id"] / source["candidate_identity"]
        if (
            not path.is_file()
            or path.is_symlink()
            or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]
        ):
            return False
    return True


def _ack(
    workspace: str | Path,
    filename: str,
    identity: object,
    record: RecordReference | None = None,
    authority_override: ReviewAuthority | None = None,
) -> ReviewAcknowledgmentReference | None:
    if not isinstance(identity, str):
        return None
    try:
        reference = ReviewAcknowledgmentReference(
            kind="review_ack", identity=identity, uri=record_uri("review_ack", identity)
        )
    except ValueError:
        return None
    if record is None:
        return None
    purpose = (
        "proposal"
        if filename == "proposal_ack.json"
        else "trial_finish"
        if filename.startswith("trial-finish")
        else "intake"
    )
    authority = authority_override or (
        ReviewAuthority.RESEARCHER
        if purpose in {"proposal", "trial_finish"}
        else ReviewAuthority.HOST
    )
    return verify_acknowledgment(
        workspace, filename, reference, record=record, purpose=purpose, authority=authority
    )


def current_status(workspace: str | Path) -> VerifiedCurrentStatus:
    state = read_json(workspace, "state.json")
    if state is None:
        return _empty()
    try:
        phase = WorkflowPhase(state.get("phase", WorkflowPhase.EMPTY))
        trials = tuple(
            sorted(
                (str(k), TrialDisposition(v))
                for k, v in dict(state.get("trial_dispositions", {})).items()
            )
        )
        domains = tuple(
            sorted(
                (str(k), tuple(str(item) for item in value))
                for k, value in dict(state.get("domains", {})).items()
            )
        )
        required = ReviewAuthority(state.get("review_authority", "none"))
    except (TypeError, ValueError):
        return _status(
            WorkflowPhase.EMPTY,
            "state_corrupt",
            "Workflow state is unavailable",
            "Stored workflow state is corrupt.",
            review=ReviewAuthorityRequirement(required=ReviewAuthority.NONE),
            conditions=_condition(
                "state_corrupt", "state.json does not contain a valid workflow state"
            ),
        )
    review = ReviewAuthorityRequirement(
        required=required,
        satisfied=bool(state.get("review_satisfied", required is ReviewAuthority.NONE)),
    )
    preflight, plan = (
        _record(RecordKind.SOURCE_PREFLIGHT, state.get("preflight_identity")),
        _record(RecordKind.INTAKE_PLAN, state.get("plan_identity")),
    )
    captured, approved = (
        _record(RecordKind.CAPTURED_BATCH, state.get("captured_identity")),
        _record(RecordKind.APPROVED_BATCH, state.get("approved_batch_identity")),
    )
    work_packet = _record(
        RecordKind.APPROVED_WORK_PACKET, state.get("work_packet_identity")
    )
    if work_packet is not None and read_json(
        workspace, f"domain-packet-{work_packet.identity.removeprefix('sha256:')}.json"
    ) is None:
        work_packet = None
    if phase is WorkflowPhase.INTAKE:
        if preflight is None or read_json(workspace, "preflight.json") is None:
            return _status(
                phase,
                "preflight_unavailable",
                "Source preflight required",
                "The stored source preflight is unavailable; run a fresh preflight.",
                review=review,
                continuation=PreflightSourcesContinuation(),
                trials=trials,
                domains=domains,
                conditions=_condition(
                    "preflight_unavailable", "preflight record is missing or corrupt"
                ),
            )
        if plan is None or read_json(workspace, "intake_plan.json") is None:
            return _status(
                phase,
                "intake_review_required",
                "Intake review required",
                "Source preflight is available and requires an explicit Intake plan.",
                review=review,
                continuation=SaveIntakePlanContinuation(preflight=preflight),
                trials=trials,
                domains=domains,
            )
        from .intake import intake_required_authority, verify_intake_plan

        try:
            verified_plan = verify_intake_plan(read_json(workspace, "intake_plan.json"))
            if verified_plan.identity != plan.identity:
                raise ValueError("plan identity does not match state")
            required_intake = intake_required_authority(verified_plan)
        except ValueError:
            return _status(
                phase,
                "intake_plan_corrupt",
                "Intake plan unavailable",
                "The stored Intake plan failed integrity verification.",
                review=ReviewAuthorityRequirement(required=ReviewAuthority.NONE),
                continuation=PreflightSourcesContinuation(),
                trials=trials,
                domains=domains,
                conditions=_condition("intake_plan_corrupt", "stored Intake plan identity mismatch"),
            )
        ack = _ack(
            workspace,
            "review_ack.json",
            state.get("ack_identity"),
            plan,
            required_intake,
        )
        if ack is None:
            return _status(
                phase,
                "intake_acknowledgment_required",
                "Intake acknowledgment required",
                "The exact Intake plan must be acknowledged before capture.",
                review=ReviewAuthorityRequirement(required=required_intake),
                continuation=(
                    ResearcherReviewContinuation(
                        record=plan, purpose="intake", unlocks="capture_batch"
                    )
                    if required_intake is ReviewAuthority.RESEARCHER
                    else None
                ),
                trials=trials,
                domains=domains,
                conditions=_condition(
                    "intake_acknowledgment_required",
                    "the stored Intake acknowledgment is unavailable",
                ),
            )
        return _status(
            phase,
            "capture_ready",
            "Batch capture ready",
            "The verified Intake plan can be captured.",
            review=ReviewAuthorityRequirement(
                required=required_intake, satisfied=True, acknowledgment=ack
            ),
            continuation=CaptureBatchContinuation(plan=plan, acknowledgment=ack),
            trials=trials,
            domains=domains,
        )
    if phase is WorkflowPhase.PROPOSAL:
        from .intake import _captured_replay_is_exact

        if (
            captured is None
            or not _captured_replay_is_exact(workspace, state.get("captured_identity"))
            or not _captured_bytes_verified(workspace, state)
        ):
            return _status(
                WorkflowPhase.INTAKE,
                "captured_integrity_failure",
                "Source preflight required",
                "Captured source bytes failed verification; run a fresh source preflight.",
                review=review,
                continuation=PreflightSourcesContinuation(
                    expected_head=preflight.identity if preflight else None
                ),
                trials=trials,
                domains=domains,
                conditions=_condition(
                    "captured_integrity_failure",
                    "captured Batch record or bytes failed verification",
                ),
            )
        proposal = read_json(workspace, "proposal_review.json")
        if proposal is None:
            return _status(
                phase,
                "proposal_required",
                "Proposal review required",
                "The Captured Batch is ready for a Proposal.",
                review=review,
                continuation=SaveProposalContinuation(captured_batch=captured),
                trials=trials,
                domains=domains,
            )
        proposal_ref = _record(RecordKind.PROPOSAL_REVIEW, proposal.get("identity"))
        try:
            transition = TransitionReference.model_validate(proposal.get("transition"))
        except ValueError:
            transition = None
        if proposal_ref is None or transition is None:
            return _status(
                phase,
                "proposal_corrupt",
                "Proposal review unavailable",
                "The stored Proposal Review cannot be verified.",
                review=review,
                trials=trials,
                domains=domains,
                conditions=_condition(
                    "proposal_corrupt",
                    "proposal review identity or transition is missing or corrupt",
                ),
            )
        from .proposal import Compatibility, _current_review

        try:
            verified_proposal = _current_review(workspace)
        except (TypeError, ValueError):
            return _status(
                phase,
                "proposal_corrupt",
                "Proposal review unavailable",
                "The stored Proposal Review cannot be verified.",
                review=ReviewAuthorityRequirement(required=ReviewAuthority.NONE),
                trials=trials,
                domains=domains,
                conditions=_condition(
                    "proposal_corrupt", "stored Proposal Review failed integrity verification"
                ),
            )
        needs_input_trials = {item.trial_id for item in verified_proposal.needs_input}
        if any(
            item.compatibility.status is not Compatibility.COMPATIBLE
            and item.trial_id not in needs_input_trials
            for item in verified_proposal.results
        ):
            return _status(
                phase,
                "proposal_compatibility_unresolved",
                "Proposal repair required",
                "The stored Proposal Review contains a non-compatible Result without a matching preapproval needs-input disposition.",
                review=ReviewAuthorityRequirement(required=ReviewAuthority.NONE, satisfied=True),
                continuation=SaveProposalContinuation(captured_batch=captured),
                trials=trials,
                domains=domains,
                conditions=_condition(
                    "proposal_compatibility_unresolved",
                    "repair the Proposal Result or provide a matching preapproval needs-input disposition",
                ),
            )
        ack = _ack(workspace, "proposal_ack.json", state.get("ack_identity"), proposal_ref)
        if ack is None:
            return _status(
                phase,
                "proposal_acknowledgment_required",
                "Researcher Proposal review required",
                "The exact whole-Batch Proposal Review requires researcher acknowledgment.",
                review=ReviewAuthorityRequirement(required=ReviewAuthority.RESEARCHER),
                continuation=ResearcherReviewContinuation(
                    record=proposal_ref, purpose="proposal", unlocks="approve_batch"
                ),
                trials=trials,
                domains=domains,
            )
        return _status(
            phase,
            "proposal_approval_ready",
            "Proposal approval ready",
            "The acknowledged exact Proposal Review can be approved.",
            review=ReviewAuthorityRequirement(
                required=ReviewAuthority.RESEARCHER, satisfied=True, acknowledgment=ack
            ),
            continuation=ApproveBatchContinuation(
                review=proposal_ref, transition=transition, acknowledgment=ack
            ),
            trials=trials,
            domains=domains,
        )
    if phase in {WorkflowPhase.ASSESSMENT, WorkflowPhase.READY_TO_FINALIZE}:
        if approved is None or read_json(workspace, "approved_batch.json") is None:
            return _status(
                phase,
                "approved_batch_unavailable",
                "Approved Batch unavailable",
                "The stored approved Batch cannot be verified.",
                review=review,
                trials=trials,
                domains=domains,
                conditions=_condition(
                    "approved_batch_unavailable", "approved Batch record is missing or corrupt"
                ),
            )
        terminal = {
            TrialDisposition.ASSESSED,
            TrialDisposition.NEEDS_INPUT,
            TrialDisposition.FAILED,
        }
        if phase is WorkflowPhase.READY_TO_FINALIZE or (
            trials and all(value in terminal for _, value in trials)
        ):
            return _status(
                WorkflowPhase.READY_TO_FINALIZE,
                "ready_to_finalize",
                "Batch ready to finalize",
                "Every Trial has a terminal disposition.",
                review=review,
                continuation=FinalizeBatchContinuation(approved_batch=approved),
                trials=trials,
                domains=domains,
            )
        pending = state.get("trial_finish_transition")
        if isinstance(pending, dict):
            try:
                transition = TransitionReference.model_validate(pending)
                transition_record = read_json(
                    workspace,
                    f"transition-{transition.identity.removeprefix('sha256:')}.json",
                )
                synthesis = (
                    None
                    if transition_record is None
                    else _record(
                        RecordKind.SYNTHESIS,
                        transition_record.get("synthesis", {}).get("identity"),
                    )
                )
                candidate_raw = None if transition_record is None else transition_record.get("candidate")
                candidate_record = synthesis
                if isinstance(candidate_raw, dict) and candidate_raw.get("disposition") != "assessed" and synthesis is not None:
                    candidate_identity = identity({"synthesis": synthesis.model_dump(mode="json"), "candidate": candidate_raw})
                    candidate_record = _record(RecordKind.TRIAL_OUTCOME, candidate_identity)
            except ValueError:
                transition, synthesis, candidate_record = None, None, None
            if transition is None or synthesis is None or candidate_record is None:
                return _status(
                    phase,
                    "trial_finish_unavailable",
                    "Trial finish unavailable",
                    "The prepared Trial finish cannot be verified.",
                    review=review,
                    trials=trials,
                    domains=domains,
                    conditions=_condition(
                        "trial_finish_unavailable", "trial finish transition is missing or corrupt"
                    ),
                )
            ack_identity = state.get("trial_finish_ack_identity")
            ack = _ack(
                workspace,
                f"trial-finish-ack-{str(ack_identity).removeprefix('sha256:')}.json",
                ack_identity,
                candidate_record,
            )
            if ack is not None:
                return _status(
                    phase,
                    "trial_finish_ready",
                    "Trial finish ready",
                    "The verified Trial finish can be completed.",
                    review=ReviewAuthorityRequirement(
                        required=ReviewAuthority.RESEARCHER,
                        satisfied=True,
                        acknowledgment=ack,
                    ),
                    continuation=FinishTrialContinuation(
                        transition=transition, acknowledgment=ack
                    ),
                    trials=trials,
                    domains=domains,
                )
            return _status(
                phase,
                "trial_finish_acknowledgment_required",
                "Trial finish review required",
                "The prepared Trial finish requires researcher acknowledgment.",
                review=ReviewAuthorityRequirement(required=ReviewAuthority.RESEARCHER),
                continuation=ResearcherReviewContinuation(
                    record=candidate_record, purpose="trial_finish", unlocks="finish_trial"
                ),
                trials=trials,
                domains=domains,
            )
        return _status(
            phase,
            "assessment_in_progress",
            "Assessment in progress",
            "The approved Batch has pending Trial Domain work.",
            review=review,
            continuation=ValidateDomainJudgmentContinuation(packet=work_packet or approved),
            trials=trials,
            domains=domains,
        )
    if phase is WorkflowPhase.FINALIZED:
        finalization = read_json(workspace, "finalization-summary.json")
        result_identity = state.get("finalization_identity")
        result = (
            read_json(workspace, f"finalization-{result_identity.removeprefix('sha256:')}.json")
            if isinstance(result_identity, str)
            else None
        )
        if isinstance(finalization, dict) and isinstance(finalization.get("presentation"), dict) and result is not None:
            from .finalization import FinalizationResult, verify_finalization_result

            try:
                artifact_verified = (
                    verify_finalization_result(
                        workspace, FinalizationResult.model_validate(result)
                    )
                    is not None
                )
            except (OSError, ValueError, TypeError):
                artifact_verified = False
            if not artifact_verified:
                finalization = None
        if isinstance(finalization, dict) and isinstance(finalization.get("presentation"), dict):
            presentation = AuthoritativePresentation.model_validate(finalization["presentation"])
            return _status(
                phase,
                presentation.code,
                presentation.headline,
                presentation.summary,
                review=review,
                trials=trials,
                domains=domains,
            )
        return _status(
            phase,
            "finalization_corrupt",
            "Batch finalization unavailable",
            "The finalized Batch summary cannot be verified.",
            review=review,
            trials=trials,
            domains=domains,
            conditions=_condition(
                "finalization_corrupt", "finalization summary is missing or corrupt"
            ),
        )
    return _empty()


def status_json(workspace: str | Path) -> str:
    return current_status(workspace).model_dump_json(exclude_none=True, exclude_defaults=True)
