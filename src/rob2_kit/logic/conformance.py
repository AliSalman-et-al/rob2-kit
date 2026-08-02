"""Independent golden-case conformance for an exact Logic-pack release."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from rob2_kit.domain.assessment import JudgmentLevel, SQAnswerCategory
from rob2_kit.logic.evaluator import EvaluationRequest, LogicEvaluator
from rob2_kit.logic.packs import LogicPack, _PackSafeLoader


class ConformanceFailure(ValueError):
    """Raised when a pack differs from its independently transcribed oracle."""


class ReviewerSlot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    reviewer_name: str | None = None
    completed: bool = False

    @model_validator(mode="after")
    def completed_review_is_named(self) -> "ReviewerSlot":
        if self.completed and not self.reviewer_name:
            raise ValueError("a completed human review must name its reviewer")
        return self


class GoldenCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    answers: dict[str, SQAnswerCategory]
    assessor_inputs: dict[str, bool] = Field(default_factory=dict)
    expected_domains: dict[str, JudgmentLevel]
    expected_overall: JudgmentLevel
    expected_active: tuple[str, ...] = ()
    expected_inactive: tuple[str, ...] = ()
    expected_matched_rules: tuple[str, ...]


class ConformanceSuite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    logic_family_id: str
    logic_release_id: str
    logic_content_hash: str
    transcription_source: str
    reviewer_slots: tuple[ReviewerSlot, ReviewerSlot]
    covered_branch_question_ids: tuple[str, ...]
    covered_rule_ids: tuple[str, ...]
    invalid_cases: tuple[dict[str, Any], ...]
    golden_cases: tuple[GoldenCase, ...]


def load_conformance_suite(path: Path) -> ConformanceSuite:
    with path.open(encoding="utf-8") as source:
        return ConformanceSuite.model_validate(yaml.load(source, Loader=_PackSafeLoader))


def assert_conformance(pack: LogicPack, suite: ConformanceSuite) -> None:
    """Fail on release/hash drift, incomplete inventory, or any golden-case mismatch."""
    if (pack.family_id, pack.release_id, pack.content_hash) != (
        suite.logic_family_id,
        suite.logic_release_id,
        suite.logic_content_hash,
    ):
        raise ConformanceFailure("conformance suite is not pinned to this exact Logic release")

    branch_ids = {question.id for question in pack.questions if question.active_if is not None}
    if branch_ids != set(suite.covered_branch_question_ids):
        raise ConformanceFailure("conformance branch inventory is incomplete")
    rule_ids = {rule.id for domain in pack.domains for rule in domain.judgment_rules} | {
        rule.id for rule in pack.overall_rules
    }
    if rule_ids != set(suite.covered_rule_ids):
        raise ConformanceFailure("conformance judgment-rule inventory is incomplete")
    golden_rule_ids = {
        rule_id for case in suite.golden_cases for rule_id in case.expected_matched_rules
    }
    if rule_ids != golden_rule_ids:
        raise ConformanceFailure("golden cases do not exercise every judgment rule")

    evaluator = LogicEvaluator(pack)
    for invalid in suite.invalid_cases:
        try:
            evaluator.evaluate(EvaluationRequest.model_validate(invalid))
        except (ValueError, TypeError):
            continue
        raise ConformanceFailure(f"invalid case was accepted: {invalid!r}")

    for case in suite.golden_cases:
        try:
            result = evaluator.evaluate(
                EvaluationRequest(
                    answers=case.answers,
                    assessor_inputs=case.assessor_inputs,
                )
            )
        except (ValueError, TypeError) as error:
            raise ConformanceFailure(f"golden case failed: {case.id}") from error
        domains_match = all(
            result.domain_judgments[domain_id] == judgment
            for domain_id, judgment in case.expected_domains.items()
        )
        active_match = (
            not case.expected_active or result.active_question_ids == case.expected_active
        )
        inactive_match = (
            not case.expected_inactive or result.inactive_question_ids == case.expected_inactive
        )
        rules_match = set(case.expected_matched_rules) <= set(result.matched_rule_ids)
        if not (
            domains_match
            and result.overall_judgment == case.expected_overall
            and active_match
            and inactive_match
            and rules_match
        ):
            raise ConformanceFailure(f"golden case failed: {case.id}")
