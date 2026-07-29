"""Answer, judgment, review, and assessment contracts."""

from enum import StrEnum

from pydantic import Field

from rob2_kit.domain.revisions import Identifier, RecordReference, Revision


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


class DecisionTrace(Revision):
    active_question_ids: tuple[Identifier, ...]
    inactive_question_ids: tuple[Identifier, ...]
    matched_rule_ids: tuple[Identifier, ...]
    resulting_judgment: JudgmentLevel


class AlgorithmicJudgmentRevision(Revision):
    dependency_roles = {
        "answer_revisions": "dependency:sq-answer",
        "decision_trace": "dependency:decision-trace",
    }
    domain_id: Identifier
    judgment: JudgmentLevel
    answer_revisions: tuple[RecordReference, ...]
    decision_trace: RecordReference


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
    domain_id: Identifier
    disposition: DomainReviewDispositionKind
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
        "review_findings": "dependency:review-finding",
    }
    result_spec: RecordReference
    source_inventory: RecordReference
    evidence_bundles: tuple[RecordReference, ...]
    answers: tuple[RecordReference, ...]
    judgments: tuple[RecordReference, ...]
    review_findings: tuple[RecordReference, ...] = ()


class AssessmentSignOff(Revision):
    dependency_roles = {
        "assessment": "dependency:assessment",
        "reviewer_profile": "dependency:reviewer-profile",
    }
    assessment: RecordReference
    reviewer_profile: RecordReference
    assurance: str = "local_human_attribution"
