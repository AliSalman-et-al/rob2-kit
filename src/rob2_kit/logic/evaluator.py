"""Host-neutral deterministic evaluator for the closed Logic-pack vocabulary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.domain.assessment import JudgmentLevel, SQAnswerCategory
from rob2_kit.logic.packs import Condition, LogicPack


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answers: dict[str, SQAnswerCategory]
    assessor_inputs: dict[str, bool] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    logic_pack_family_id: str
    logic_pack_release_id: str
    logic_pack_hash: str
    answers: dict[str, SQAnswerCategory]
    assessor_inputs: dict[str, bool]
    question_states: dict[str, Literal["answered", "not_applicable"]]
    active_question_ids: tuple[str, ...]
    inactive_question_ids: tuple[str, ...]
    evaluated_rule_ids: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]
    required_assessor_input_ids: tuple[str, ...]
    domain_judgments: dict[str, JudgmentLevel]
    overall_judgment: JudgmentLevel


class ActivationDependencies(BaseModel):
    """Pack-declared values that can affect one question's activation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer_question_ids: tuple[str, ...] = ()
    assessor_input_ids: tuple[str, ...] = ()
    domain_ids: tuple[str, ...] = ()


class LogicEvaluator:
    """Evaluate exact answers without accepting a caller-authored judgment."""

    def __init__(self, pack: LogicPack) -> None:
        self._pack = pack

    def active_question_ids_for_answers(
        self,
        answers: dict[str, SQAnswerCategory],
        assessor_inputs: dict[str, bool] | None = None,
        prior_domain_judgments: dict[str, JudgmentLevel] | None = None,
    ) -> tuple[str, ...]:
        """Return the questions activated by a partial committed answer set.

        This is intentionally narrower than :meth:`evaluate`: it does not
        require every active question to be answered and therefore supports
        incremental work scheduling without assigning any judgment.
        """

        validated = self._validated_partial_answers(answers)
        inputs = self._validated_partial_assessor_inputs(assessor_inputs or {})
        judgments = self._validated_partial_domain_judgments(prior_domain_judgments or {})
        return tuple(
            question.id
            for question in self._pack.questions
            if question.active_if is None
            or self._matches(question.active_if, validated, judgments, inputs)
        )

    def activation_dependencies(self, question_id: str) -> ActivationDependencies:
        """Return the pack-declared context that can activate one question."""

        question = next((item for item in self._pack.questions if item.id == question_id), None)
        if question is None:
            raise ValueError(f"unknown Logic question ID: {question_id}")
        if question.active_if is None:
            return ActivationDependencies()

        def collect(condition: Condition) -> tuple[set[str], set[str], bool]:
            answers = {condition.question_id} if condition.question_id is not None else set()
            inputs = {condition.input_id} if condition.input_id is not None else set()
            has_domain_condition = condition.op in {"domain_all", "domain_any", "domain_count"}
            for item in condition.conditions:
                child_answers, child_inputs, child_has_domain = collect(item)
                answers.update(child_answers)
                inputs.update(child_inputs)
                has_domain_condition = has_domain_condition or child_has_domain
            return answers, inputs, has_domain_condition

        answer_ids, input_ids, has_domain_condition = collect(question.active_if)
        return ActivationDependencies(
            answer_question_ids=tuple(sorted(answer_ids)),
            assessor_input_ids=tuple(sorted(input_ids)),
            # Domain operators evaluate the supplied judgment set as a whole,
            # so every declared domain identity is a dependency.
            domain_ids=tuple(sorted(item.id for item in self._pack.domains))
            if has_domain_condition
            else (),
        )

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        answers = self._validated_partial_answers(request.answers)
        active_ids = set(self.active_question_ids_for_answers(answers, request.assessor_inputs))
        active: list[str] = []
        inactive: list[str] = []
        for question in self._pack.questions:
            is_active = question.id in active_ids
            (active if is_active else inactive).append(question.id)

        impossible = set(answers) & set(inactive)
        if impossible:
            raise ValueError(f"answers supplied for not_applicable questions: {sorted(impossible)}")
        missing = set(active) - set(answers)
        if missing:
            raise ValueError(f"answers required for active questions: {sorted(missing)}")

        domain_judgments: dict[str, JudgmentLevel] = {}
        evaluated_rules: list[str] = []
        matched_rules: list[str] = []
        for domain in self._pack.domains:
            for rule in domain.judgment_rules:
                evaluated_rules.append(rule.id)
                if self._matches(rule.when, answers, domain_judgments, request.assessor_inputs):
                    domain_judgments[domain.id] = rule.judgment
                    matched_rules.append(rule.id)
                    break
            else:
                raise ValueError(f"no judgment rule matched {domain.id}")

        required_inputs = tuple(
            item.id
            for item in self._pack.assessor_inputs
            if self._matches(item.required_if, answers, domain_judgments, request.assessor_inputs)
        )
        unknown_inputs = set(request.assessor_inputs) - {
            item.id for item in self._pack.assessor_inputs
        }
        if unknown_inputs:
            raise ValueError(f"unknown assessor inputs: {sorted(unknown_inputs)}")
        missing_inputs = set(required_inputs) - set(request.assessor_inputs)
        if missing_inputs:
            raise ValueError(f"required assessor inputs missing: {sorted(missing_inputs)}")
        inapplicable_inputs = set(request.assessor_inputs) - set(required_inputs)
        if inapplicable_inputs:
            raise ValueError(
                f"assessor inputs supplied outside their applicability: "
                f"{sorted(inapplicable_inputs)}"
            )

        overall: JudgmentLevel | None = None
        for rule in self._pack.overall_rules:
            evaluated_rules.append(rule.id)
            if self._matches(rule.when, answers, domain_judgments, request.assessor_inputs):
                overall = rule.judgment
                matched_rules.append(rule.id)
                break
        if overall is None:
            raise ValueError("no overall judgment rule matched")

        return EvaluationResult(
            logic_pack_family_id=self._pack.family_id,
            logic_pack_release_id=self._pack.release_id,
            logic_pack_hash=self._pack.content_hash,
            answers={question_id: answers[question_id] for question_id in active},
            assessor_inputs={
                input_id: request.assessor_inputs[input_id] for input_id in required_inputs
            },
            question_states={
                question_id: "answered" if question_id in active else "not_applicable"
                for question_id in (question.id for question in self._pack.questions)
            },
            active_question_ids=tuple(active),
            inactive_question_ids=tuple(inactive),
            evaluated_rule_ids=tuple(evaluated_rules),
            matched_rule_ids=tuple(matched_rules),
            required_assessor_input_ids=required_inputs,
            domain_judgments=domain_judgments,
            overall_judgment=overall,
        )

    def _validated_partial_answers(
        self, answers: dict[str, SQAnswerCategory]
    ) -> dict[str, SQAnswerCategory]:
        answers = self._validate_answer_values(answers)
        questions_by_id = {question.id: question for question in self._pack.questions}
        known_questions = set(questions_by_id)
        unknown = set(answers) - known_questions
        if unknown:
            raise ValueError(f"unknown Logic element IDs: {sorted(unknown)}")

        disallowed = {
            question_id: answer
            for question_id, answer in answers.items()
            if answer not in questions_by_id[question_id].allowed_answers
        }
        if disallowed:
            raise ValueError(
                "answers outside the question vocabulary: "
                + ", ".join(
                    f"{question_id}={answer.value!r}"
                    for question_id, answer in sorted(disallowed.items())
                )
            )
        return answers

    def _validated_partial_assessor_inputs(self, inputs: dict[str, bool]) -> dict[str, bool]:
        known = {item.id for item in self._pack.assessor_inputs}
        unknown = set(inputs) - known
        if unknown:
            raise ValueError(f"unknown assessor inputs: {sorted(unknown)}")
        if any(type(value) is not bool for value in inputs.values()):
            raise ValueError("assessor inputs must use canonical boolean values")
        return dict(inputs)

    def _validated_partial_domain_judgments(
        self, judgments: dict[str, JudgmentLevel]
    ) -> dict[str, JudgmentLevel]:
        known = {item.id for item in self._pack.domains}
        unknown = set(judgments) - known
        if unknown:
            raise ValueError(f"unknown Logic domain IDs: {sorted(unknown)}")
        validated: dict[str, JudgmentLevel] = {}
        for domain_id, judgment in judgments.items():
            try:
                validated[domain_id] = JudgmentLevel(judgment)
            except ValueError as error:
                raise ValueError(f"{judgment!r} is not a canonical domain judgment") from error
        return validated

    @staticmethod
    def _validate_answer_values(
        answers: dict[str, SQAnswerCategory],
    ) -> dict[str, SQAnswerCategory]:
        validated: dict[str, SQAnswerCategory] = {}
        for question_id, answer in answers.items():
            try:
                validated[question_id] = SQAnswerCategory(answer)
            except ValueError as error:
                raise ValueError(
                    f"{answer!r} is not a canonical answer; not_applicable is engine-derived"
                ) from error
        return validated

    def _matches(
        self,
        condition: Condition,
        answers: dict[str, SQAnswerCategory],
        judgments: dict[str, JudgmentLevel],
        inputs: dict[str, bool],
    ) -> bool:
        if condition.op == "all":
            return all(
                self._matches(item, answers, judgments, inputs) for item in condition.conditions
            )
        if condition.op == "any":
            return any(
                self._matches(item, answers, judgments, inputs) for item in condition.conditions
            )
        if condition.op == "answer_in":
            return answers.get(condition.question_id) in condition.answers
        if condition.op == "domain_all":
            return bool(judgments) and all(
                value in condition.judgments for value in judgments.values()
            )
        if condition.op == "domain_any":
            return any(value in condition.judgments for value in judgments.values())
        if condition.op == "domain_count":
            return sum(value == condition.judgment for value in judgments.values()) >= (
                condition.minimum or 0
            )
        if condition.op == "input_equals":
            return inputs.get(condition.input_id) is condition.value
        raise AssertionError(f"unreachable rule operator: {condition.op}")
