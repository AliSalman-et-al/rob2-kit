"""Preparation and failure outcome contracts."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from rob2_kit.domain.revisions import FrozenModel, Identifier, RecordReference, Revision


class PreparationOutcomeKind(StrEnum):
    DRAFT_READY = "draft_ready"
    PREPARATION_INCOMPLETE = "preparation_incomplete"
    TRIAL_FAILED = "trial_failed"


class IncompleteReason(StrEnum):
    MATERIAL_EVIDENCE_GAP = "material_evidence_gap"
    INSUFFICIENT_READABLE_COVERAGE = "insufficient_readable_coverage"
    UNRESOLVED_MATERIAL_CONFLICT = "unresolved_material_conflict"


class TrialFailureReason(StrEnum):
    REQUIRED_PRIMARY_UNRECOVERABLE = "required_primary_unrecoverable"
    RESULT_UNRECOVERABLE = "result_unrecoverable"
    PAGE_ATTRIBUTION_UNTRUSTWORTHY = "page_attribution_untrustworthy"


class DraftReady(FrozenModel):
    outcome: Literal["draft_ready"] = "draft_ready"
    assessment: RecordReference
    review_findings: tuple[RecordReference, ...] = ()


class PreparationIncomplete(FrozenModel):
    outcome: Literal["preparation_incomplete"] = "preparation_incomplete"
    result_spec: RecordReference
    reason: IncompleteReason
    detail: str = Field(min_length=1)


class TrialFailed(FrozenModel):
    outcome: Literal["trial_failed"] = "trial_failed"
    trial_id: Identifier
    reason: TrialFailureReason
    detail: str = Field(min_length=1)


PreparationOutcome = DraftReady | PreparationIncomplete | TrialFailed


class PreparationAttempt(Revision):
    dependency_roles = {
        "project_manifest": "dependency:project-manifest",
        "result_spec": "dependency:result-spec",
    }
    project_manifest: RecordReference
    result_spec: RecordReference
    outcome: PreparationOutcome | None = None


class ReviewReceiptOutcome(StrEnum):
    ACTION_COMPLETED = "action_completed"
    CORRECTION_REQUESTED = "correction_requested"
    DEFERRED = "deferred"
    ASSESSMENT_SIGNED_OFF = "assessment_signed_off"


class ReviewReceipt(Revision):
    dependency_roles = {
        "assessment": "dependency:assessment",
        "ledger_event": "dependency:ledger-event",
    }
    outcome: ReviewReceiptOutcome
    review_action_id: Identifier
    assessment: RecordReference
    ledger_event: RecordReference
