"""The shared, adapter-independent application boundary."""

from typing import Any

from .contracts import (
    AuthoritativePresentation,
    Continuation,
    EvidenceReference,
    OperationOutcome,
    RecordReference,
    RenderReference,
    ReviewAcknowledgmentReference,
    ReviewAuthority,
    ReviewAuthorityRequirement,
    TransitionReference,
    TrialDisposition,
    VerifiedCurrentStatus,
    WorkflowPhase,
)
from .intake import (
    CaptureReceipt,
    CaptureRequest,
    IntakePlan,
    IntakePlanEntry,
    IntakePlanReceipt,
    acknowledge_intake,
    capture_batch,
    save_intake_plan,
)
from .preflight import (
    PREFLIGHT_LIMITS,
    AuthorizedSourceRoot,
    CandidateInspection,
    CandidateSource,
    PreflightLimits,
    PreflightRequest,
    SourcePreflight,
    inspect_candidate_sources,
    preflight_sources,
)
from .status import current_status, status_json

__all__ = [
    "AuthoritativePresentation",
    "AuthorizedSourceRoot",
    "CandidateInspection",
    "CandidateSource",
    "CaptureReceipt",
    "CaptureRequest",
    "Continuation",
    "EvidenceReference",
    "IntakePlan",
    "IntakePlanEntry",
    "IntakePlanReceipt",
    "OperationOutcome",
    "PreflightLimits",
    "PreflightRequest",
    "PREFLIGHT_LIMITS",
    "RecordReference",
    "RenderReference",
    "ReviewAcknowledgmentReference",
    "ReviewAuthority",
    "ReviewAuthorityRequirement",
    "SourcePreflight",
    "TransitionReference",
    "TrialDisposition",
    "VerifiedCurrentStatus",
    "WorkflowPhase",
    "acknowledge_intake",
    "capture_batch",
    "current_status",
    "inspect_candidate_sources",
    "preflight_sources",
    "save_intake_plan",
    "status_json",
    "ApprovalRequest",
    "ClarificationSelection",
    "ProposalInput",
    "acknowledge_proposal",
    "apply_clarification",
    "approve_batch",
    "save_proposal",
    "EvidenceRetrievalRequest",
    "EvidenceRetrievalResponse",
    "EvidenceCatalogRequest",
    "EvidenceCatalogSlice",
    "TextEvidenceRecord",
    "VisualEvidenceRecord",
    "list_sources",
    "retrieve_evidence",
    "resolve_evidence",
    "DomainDraftInput",
    "DomainAnswerInput",
    "DomainEvidenceUseInput",
    "DomainOverrideInput",
    "DomainValidationRequest",
    "validate_domain_judgment",
    "commit_domain_judgment",
    "prepare_domain_packet",
    "prepare_trial_finish",
    "finish_trial",
    "acknowledge_trial_finish",
    "TrialFinishCandidate",
    "TrialFinishRequest",
    "TrialFinishResult",
    "TrialPrepareResult",
    "TrialSynthesis",
    "FinalizationCounts",
    "FinalizationCondition",
    "FinalizationResult",
    "finalize_batch",
    "verify_finalization",
]


def __getattr__(name: str) -> Any:
    # Keep the retrieval module lazy: it imports the render and projection
    # machinery, while those modules use the package's state primitives.
    if name in {
        "EvidenceRetrievalRequest",
        "EvidenceRetrievalResponse",
        "EvidenceCatalogRequest",
        "EvidenceCatalogSlice",
        "TextEvidenceRecord",
        "VisualEvidenceRecord",
        "list_sources",
        "retrieve_evidence",
        "resolve_evidence",
    }:
        from . import evidence

        return getattr(evidence, name)
    if name in {
        "DomainDraftInput", "DomainAnswerInput", "DomainEvidenceUseInput",
        "DomainOverrideInput", "DomainValidationRequest", "validate_domain_judgment",
        "commit_domain_judgment", "prepare_domain_packet",
    }:
        from . import domains

        return getattr(domains, name)
    if name in {
        "prepare_trial_finish", "finish_trial", "acknowledge_trial_finish",
        "TrialFinishCandidate", "TrialFinishRequest", "TrialFinishResult",
        "TrialPrepareResult", "TrialSynthesis",
    }:
        from . import trials

        return getattr(trials, name)
    if name in {
        "FinalizationCounts", "FinalizationCondition", "FinalizationResult",
        "finalize_batch", "verify_finalization",
    }:
        from . import finalization

        return getattr(finalization, name)
    if name in {
        "ApprovalRequest",
        "ClarificationSelection",
        "ProposalInput",
        "acknowledge_proposal",
        "apply_clarification",
        "approve_batch",
        "save_proposal",
    }:
        from . import proposal

        return getattr(proposal, name)
    raise AttributeError(name)
