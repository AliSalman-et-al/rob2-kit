"""Answer, judgment, review, and assessment contracts."""

from enum import StrEnum

from pydantic import Field

from rob2_kit.domain.revisions import ContentHash, Identifier, RecordReference, Revision


class SQAnswerCategory(StrEnum):
    YES = "yes"
    PROBABLY_YES = "probably_yes"
    PROBABLY_NO = "probably_no"
    NO = "no"
    NO_INFORMATION = "no_information"


class JudgmentLevel(StrEnum):
    LOW = "low"
    SOME_CONCERNS = "some_concerns"
    HIGH = "high"


class SQAnswerRevision(Revision):
    dependency_roles = {
        "evidence_bundle": "dependency:evidence-bundle",
        "project_rules": "dependency:project-rule",
    }
    sq_id: Identifier
    answer: SQAnswerCategory
    rationale: str = Field(min_length=1)
    evidence_bundle: RecordReference
    project_rules: tuple[RecordReference, ...] = ()
    # Exact release/policy provenance is carried on every answer.  They are
    # hashes rather than mutable pack objects so replay remains host-neutral.
    logic_pack_release_id: str | None = None
    logic_pack_hash: ContentHash | None = None
    guidance_pack_release_id: str | None = None
    guidance_pack_hash: ContentHash | None = None
    evidence_policy_id: str | None = None
    evidence_policy_hash: ContentHash | None = None
    decision_rule_ids: tuple[Identifier, ...] = ()


class DecisionTrace(Revision):
    active_question_ids: tuple[Identifier, ...]
    inactive_question_ids: tuple[Identifier, ...]
    matched_rule_ids: tuple[Identifier, ...]
    resulting_judgment: JudgmentLevel
    domain_id: Identifier | None = None
    evaluated_rule_ids: tuple[Identifier, ...] = ()
    logic_pack_release_id: str | None = None
    logic_pack_hash: ContentHash | None = None


class AlgorithmicJudgmentRevision(Revision):
    dependency_roles = {
        "answer_revisions": "dependency:sq-answer",
        "decision_trace": "dependency:decision-trace",
    }
    domain_id: Identifier
    judgment: JudgmentLevel
    answer_revisions: tuple[RecordReference, ...]
    decision_trace: RecordReference
    logic_pack_release_id: str | None = None
    logic_pack_hash: ContentHash | None = None
    overall_policy_id: Identifier | None = None
    overall_policy_hash: ContentHash | None = None


class JudgmentOverride(Revision):
    dependency_roles = {
        "judgment_revision": "dependency:algorithmic-judgment",
        "policy_authority": "dependency:review-policy",
    }
    judgment_revision: RecordReference
    replacement: JudgmentLevel
    rationale: str = Field(min_length=1)
    policy_authority: RecordReference


class ReviewFinding(Revision):
    dependency_roles = {"affected_records": "dependency:affected-record"}
    finding_type: Identifier
    severity: Identifier
    summary: str = Field(min_length=1)
    affected_records: tuple[RecordReference, ...]


class DomainReviewDispositionKind(StrEnum):
    ACCEPT = "accept"
    CORRECT = "correct"
    OVERRIDE = "override"
    DEFER = "defer"


class DomainReviewDisposition(Revision):
    dependency_roles = {
        "assessment": "dependency:assessment",
        "reviewer_profile": "dependency:reviewer-profile",
    }
    domain_id: Identifier
    disposition: DomainReviewDispositionKind
    assessment: RecordReference
    reviewer_profile: RecordReference
    rationale: str | None = None


class ReviewerProfileRevision(Revision):
    display_name: str = Field(min_length=1)
    affiliation: str | None = None
    external_identifiers: tuple[str, ...] = ()


class AssessmentRevision(Revision):
    dependency_roles = {
        "result_spec": "dependency:result-spec",
        "source_inventory": "dependency:source-inventory",
        "evidence_bundles": "dependency:evidence-bundle",
        "answers": "dependency:sq-answer",
        "judgments": "dependency:algorithmic-judgment",
        "judgment_overrides": "dependency:judgment-override",
        "review_findings": "dependency:review-finding",
    }
    result_spec: RecordReference
    source_inventory: RecordReference
    evidence_bundles: tuple[RecordReference, ...]
    answers: tuple[RecordReference, ...]
    judgments: tuple[RecordReference, ...]
    judgment_overrides: tuple[RecordReference, ...] = ()
    review_findings: tuple[RecordReference, ...] = ()


class AssessmentSignOff(Revision):
    dependency_roles = {
        "assessment": "dependency:assessment",
        "reviewer_profile": "dependency:reviewer-profile",
        "domain_dispositions": "dependency:domain-review-disposition",
        "review_policy": "dependency:review-policy",
    }
    assessment: RecordReference
    reviewer_profile: RecordReference
    domain_dispositions: tuple[RecordReference, ...] = ()
    review_policy: RecordReference | None = None
    attestation: str = (
        "I reviewed this exact Result Assessment under the stated Review policy and "
        "approve its recorded answers, final judgments, overrides, and acknowledged "
        "limitations as the current assessment."
    )
    assurance: str = "local_human_attribution"


class SignOffWithdrawal(Revision):
    dependency_roles = {
        "sign_off": "dependency:assessment-sign-off",
        "reviewer_profile": "dependency:reviewer-profile",
    }
    sign_off: RecordReference
    reviewer_profile: RecordReference
    reason: str = Field(min_length=1)
