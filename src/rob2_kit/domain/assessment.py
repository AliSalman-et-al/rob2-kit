"""Answer, judgment, and immutable assessment contracts."""

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


class AssessmentRevision(Revision):
    dependency_roles = {
        "result_spec": "dependency:result-spec",
        "source_inventory": "dependency:source-inventory",
        "evidence_bundles": "dependency:evidence-bundle",
        "answers": "dependency:sq-answer",
        "judgments": "dependency:algorithmic-judgment",
    }
    result_spec: RecordReference
    source_inventory: RecordReference
    evidence_bundles: tuple[RecordReference, ...]
    answers: tuple[RecordReference, ...]
    judgments: tuple[RecordReference, ...]
