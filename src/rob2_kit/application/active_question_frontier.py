"""Private, append-only ledger for active signaling-question work.

This module deliberately stops before Domain publication.  It binds one
question answer to a procedurally closed v3 evidence workflow, then derives
the next questions from the immutable Logic pack.
"""

from typing import Literal

from pydantic import Field, model_validator

from rob2_kit.domain.assessment import JudgmentLevel, SQAnswerCategory
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.domain.revisions import ContentHash, FrozenModel, Identifier
from rob2_kit.evidence.workflow import V3EvidenceWorkflowState, v3_coverage_progress
from rob2_kit.logic.evaluator import ActivationDependencies, LogicEvaluator
from rob2_kit.logic.packs import LogicPack, Question


class QuestionEvidenceClosure(FrozenModel):
    """Immutable identity for one question's procedurally closed evidence work."""

    question_id: Identifier
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    obligation_revision_id: Identifier
    obligation_hash: ContentHash
    inventory_snapshot_hash: ContentHash
    workflow_state_hash: ContentHash
    closure_hash: ContentHash = ""

    @model_validator(mode="after")
    def validate_hash(self) -> "QuestionEvidenceClosure":
        payload = self.model_dump(mode="json")
        payload["closure_hash"] = None
        expected = canonical_hash(payload)
        if self.closure_hash and self.closure_hash != expected:
            raise ValueError("question evidence closure hash must bind its exact identity")
        object.__setattr__(self, "closure_hash", expected)
        return self


class QuestionEvidenceDiagnostic(FrozenModel):
    """Exact workflow identity for an accepted terminal evidence limitation."""

    question_id: Identifier
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    obligation_revision_id: Identifier
    obligation_hash: ContentHash
    inventory_snapshot_hash: ContentHash
    workflow_state_hash: ContentHash
    diagnostic_hash: ContentHash = ""

    @model_validator(mode="after")
    def validate_hash(self) -> "QuestionEvidenceDiagnostic":
        payload = self.model_dump(mode="json")
        payload["diagnostic_hash"] = None
        expected = canonical_hash(payload)
        if self.diagnostic_hash and self.diagnostic_hash != expected:
            raise ValueError("question evidence diagnostic hash must bind its exact identity")
        object.__setattr__(self, "diagnostic_hash", expected)
        return self


def evidence_closure_from_workflow(
    workflow: V3EvidenceWorkflowState,
) -> QuestionEvidenceClosure:
    """Create a closure only when the v3 reducer has procedurally closed it."""

    progress = v3_coverage_progress(workflow)
    if not progress["question_ready"] or not _progress_navigation_closed(progress):
        raise ValueError("question evidence workflow is not procedurally closed")
    return QuestionEvidenceClosure(
        question_id=workflow.question_id,
        run_id=workflow.run_id,
        result_id=workflow.result_id,
        domain_id=workflow.domain_id,
        obligation_revision_id=workflow.obligation_revision_id,
        obligation_hash=workflow.obligation_hash,
        inventory_snapshot_hash=workflow.inventory_snapshot_hash,
        workflow_state_hash=workflow.content_hash,
    )


def evidence_diagnostic_from_workflow(
    workflow: V3EvidenceWorkflowState,
) -> QuestionEvidenceDiagnostic:
    """Bind only reducer-accepted terminal limitations, never an answer basis."""

    progress = v3_coverage_progress(workflow)
    stages = {
        stage["stage_id"]: stage
        for proposition in progress["propositions"]
        for evidence_pass in proposition["passes"]
        for stage in evidence_pass["stages"]
        if stage["active"]
    }
    outcomes = {item.stage_id: item for item in workflow.stage_outcomes}
    limitation_seen = False

    def closed(stage_id: str, seen: frozenset[str] = frozenset()) -> bool:
        nonlocal limitation_seen
        if stage_id in seen or stage_id not in stages:
            return False
        stage = stages[stage_id]
        outcome = outcomes.get(stage_id)
        if outcome is None:
            return False
        navigation_complete = all(intent["complete"] for intent in stage["intents"])
        navigation_clean = navigation_complete and all(
            intent["clean"] for intent in stage["intents"]
        )
        kind = outcome.outcome_kind.value
        if kind == "obligation_satisfied":
            return navigation_clean
        if kind == "semantic_uncertainty_unresolved":
            limitation_seen = True
            return navigation_complete and not navigation_clean
        if kind == "source_unavailable_after_attempt":
            limitation_seen = True
            return outcome.acquisition_receipt_id in {
                item.receipt_id for item in workflow.acquisition_receipts
            }
        if kind == "scope_limitation_unresolved":
            limitation_seen = True
            scope = next(item for item in workflow.stage_scopes if item.stage_id == stage_id)
            return navigation_complete if scope.authorized_source_ids else True
        if kind != "escalation_required" or not navigation_complete:
            return False
        targets = [
            item.target_stage_id
            for item in workflow.obligation.escalation_triggers
            if item.source_stage_id == stage_id
        ]
        return bool(targets) and all(closed(target, seen | {stage_id}) for target in targets)

    if not stages or progress["question_ready"] or not all(closed(stage_id) for stage_id in stages):
        raise ValueError("question evidence workflow has no accepted terminal diagnostic")
    if not limitation_seen:
        raise ValueError("question evidence workflow has no terminal limitation")
    return QuestionEvidenceDiagnostic(
        question_id=workflow.question_id,
        run_id=workflow.run_id,
        result_id=workflow.result_id,
        domain_id=workflow.domain_id,
        obligation_revision_id=workflow.obligation_revision_id,
        obligation_hash=workflow.obligation_hash,
        inventory_snapshot_hash=workflow.inventory_snapshot_hash,
        workflow_state_hash=workflow.content_hash,
    )


class AssessorInputActivationFact(FrozenModel):
    """One immutable assessor input used when deriving an active frontier."""

    input_id: Identifier
    value: bool

    @model_validator(mode="after")
    def validate_value(self) -> "AssessorInputActivationFact":
        if type(self.value) is not bool:
            raise ValueError("assessor activation inputs must use canonical boolean values")
        return self


class DomainJudgmentActivationFact(FrozenModel):
    """One immutable prior Domain judgment used only for question activation."""

    domain_id: Identifier
    judgment: JudgmentLevel


class QuestionFrontierEntry(FrozenModel):
    """One independently committable active question and its dependency token."""

    question_id: Identifier
    dependency_context_hash: ContentHash
    entry_hash: ContentHash = ""

    @model_validator(mode="after")
    def validate_hash(self) -> "QuestionFrontierEntry":
        payload = self.model_dump(mode="json")
        payload["entry_hash"] = None
        expected = canonical_hash(payload)
        if self.entry_hash and self.entry_hash != expected:
            raise ValueError("question frontier entry hash must bind its dependencies")
        object.__setattr__(self, "entry_hash", expected)
        return self


class ActiveQuestionFrontier(FrozenModel):
    """Deterministic current question work, ordered by the bound Logic pack."""

    logic_pack_release_id: str
    logic_pack_hash: ContentHash
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    assessor_inputs: tuple[AssessorInputActivationFact, ...] = ()
    prior_domain_judgments: tuple[DomainJudgmentActivationFact, ...] = ()
    entries: tuple[QuestionFrontierEntry, ...]
    complete: bool
    status: Literal["active", "complete_with_answers", "diagnostic_terminal"]
    frontier_hash: ContentHash = ""

    @model_validator(mode="after")
    def validate_hash(self) -> "ActiveQuestionFrontier":
        payload = self.model_dump(mode="json")
        payload["frontier_hash"] = None
        expected = canonical_hash(payload)
        if self.frontier_hash and self.frontier_hash != expected:
            raise ValueError("active question frontier hash must bind the current frontier")
        object.__setattr__(self, "frontier_hash", expected)
        return self

    @property
    def question_ids(self) -> tuple[Identifier, ...]:
        return tuple(item.question_id for item in self.entries)


class EngineVerifiedNoInformationBasis(FrozenModel):
    """Engine-issued verification identity; never a caller-selected boolean."""

    verification_id: Identifier
    verification_hash: ContentHash


class QuestionEvidenceBundleBinding(FrozenModel):
    """Frozen question Evidence Bundle identity and its closed answer basis."""

    question_id: Identifier
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    bundle_revision_id: Identifier
    bundle_content_hash: ContentHash
    supporting_evidence_ids: tuple[Identifier, ...] = ()
    contradicting_evidence_ids: tuple[Identifier, ...] = ()
    engine_verified_no_information_basis: EngineVerifiedNoInformationBasis | None = None

    @model_validator(mode="after")
    def validate_basis(self) -> "QuestionEvidenceBundleBinding":
        evidence_ids = (*self.supporting_evidence_ids, *self.contradicting_evidence_ids)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("question evidence bundle cannot repeat qualifying evidence")
        if not evidence_ids and self.engine_verified_no_information_basis is None:
            raise ValueError(
                "question evidence bundle requires qualifying claims or an engine-verified "
                "No-information basis"
            )
        return self


class QuestionAnswerCommitStep(FrozenModel):
    """One immutable answer coupled to exact question-scoped evidence closure."""

    step_id: Identifier
    question_id: Identifier
    answer: SQAnswerCategory
    rationale: str = Field(min_length=1)
    logic_pack_family_id: str
    logic_pack_release_id: str
    logic_pack_hash: ContentHash
    expected_frontier_entry_hash: ContentHash
    evidence_closure: QuestionEvidenceClosure
    evidence_bundle: QuestionEvidenceBundleBinding
    content_hash: ContentHash = ""

    @model_validator(mode="after")
    def validate_step(self) -> "QuestionAnswerCommitStep":
        if self.evidence_closure.question_id != self.question_id:
            raise ValueError("question commit evidence closure must bind the same question")
        if not self.rationale.strip():
            raise ValueError("question commit rationale cannot be blank")
        if self.evidence_bundle.question_id != self.question_id:
            raise ValueError("question commit evidence bundle must bind the same question")
        if (
            self.evidence_bundle.run_id,
            self.evidence_bundle.result_id,
            self.evidence_bundle.domain_id,
        ) != (
            self.evidence_closure.run_id,
            self.evidence_closure.result_id,
            self.evidence_closure.domain_id,
        ):
            raise ValueError("question commit evidence bundle must match the closure scope")
        payload = self.model_dump(mode="json")
        payload["content_hash"] = None
        expected = canonical_hash(payload)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("question commit hash must bind its answer and evidence closure")
        object.__setattr__(self, "content_hash", expected)
        return self


class QuestionDiagnosticStop(FrozenModel):
    """Immutable non-answer terminal for one question's limited evidence state."""

    stop_id: Identifier
    question_id: Identifier
    logic_pack_family_id: str
    logic_pack_release_id: str
    logic_pack_hash: ContentHash
    expected_frontier_entry_hash: ContentHash
    evidence_diagnostic: QuestionEvidenceDiagnostic
    content_hash: ContentHash = ""

    @model_validator(mode="after")
    def validate_stop(self) -> "QuestionDiagnosticStop":
        if self.evidence_diagnostic.question_id != self.question_id:
            raise ValueError("question diagnostic must bind the same question")
        payload = self.model_dump(mode="json")
        payload["content_hash"] = None
        expected = canonical_hash(payload)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("question diagnostic hash must bind its workflow identity")
        object.__setattr__(self, "content_hash", expected)
        return self


class QuestionAnswerCorrection(FrozenModel):
    """Immutable replacement of one effective question answer."""

    correction_id: Identifier
    question_id: Identifier
    prior_step_hash: ContentHash
    answer: SQAnswerCategory
    rationale: str = Field(min_length=1)
    logic_pack_family_id: str
    logic_pack_release_id: str
    logic_pack_hash: ContentHash
    evidence_closure: QuestionEvidenceClosure
    evidence_bundle: QuestionEvidenceBundleBinding
    content_hash: ContentHash = ""

    @model_validator(mode="after")
    def validate_correction(self) -> "QuestionAnswerCorrection":
        payload = self.model_dump(mode="json")
        payload["content_hash"] = None
        expected = canonical_hash(payload)
        if self.content_hash and self.content_hash != expected:
            raise ValueError(
                "question correction hash must bind its exact predecessor and evidence"
            )
        object.__setattr__(self, "content_hash", expected)
        return self


class EffectiveQuestionAnswer(FrozenModel):
    """One currently reachable answer, projected without rewriting audit history."""

    question_id: Identifier
    answer: SQAnswerCategory
    rationale: str = Field(min_length=1)
    evidence_closure: QuestionEvidenceClosure
    evidence_bundle: QuestionEvidenceBundleBinding
    effective_step_hash: ContentHash


class ActiveQuestionLedger(FrozenModel):
    """History only: answer steps never replace or rewrite earlier steps."""

    logic_pack: LogicPack
    run_id: Identifier
    result_id: Identifier
    domain_id: Identifier
    assessor_inputs: tuple[AssessorInputActivationFact, ...] = ()
    prior_domain_judgments: tuple[DomainJudgmentActivationFact, ...] = ()
    steps: tuple[QuestionAnswerCommitStep, ...] = ()
    corrections: tuple[QuestionAnswerCorrection, ...] = ()
    diagnostic_stops: tuple[QuestionDiagnosticStop, ...] = ()
    history_hash: ContentHash = ""

    @model_validator(mode="after")
    def validate_ledger(self) -> "ActiveQuestionLedger":
        domain = next((item for item in self.logic_pack.domains if item.id == self.domain_id), None)
        if domain is None:
            raise ValueError("question ledger names an unknown Logic domain")
        question_ids = set(domain.question_ids)
        questions = {question.id: question for question in self.logic_pack.questions}
        evaluator = LogicEvaluator(self.logic_pack)
        input_ids = [item.input_id for item in self.assessor_inputs]
        if input_ids != sorted(set(input_ids)):
            raise ValueError(
                "ledger assessor activation inputs must be unique and canonically ordered"
            )
        known_input_ids = {item.id for item in self.logic_pack.assessor_inputs}
        if unknown_inputs := set(input_ids) - known_input_ids:
            raise ValueError(
                f"ledger has unknown assessor activation inputs: {sorted(unknown_inputs)}"
            )
        judgment_ids = [item.domain_id for item in self.prior_domain_judgments]
        if judgment_ids != sorted(set(judgment_ids)):
            raise ValueError("ledger prior domain judgments must be unique and canonically ordered")
        known_domain_ids = {item.id for item in self.logic_pack.domains}
        if unknown_judgments := set(judgment_ids) - known_domain_ids:
            raise ValueError(
                f"ledger has unknown prior domain judgments: {sorted(unknown_judgments)}"
            )
        inputs = {item.input_id: item.value for item in self.assessor_inputs}
        judgments = {item.domain_id: item.judgment for item in self.prior_domain_judgments}
        committed_answers: dict[str, SQAnswerCategory] = {}
        seen_steps: set[str] = set()
        corrections = {item.question_id: item for item in self.corrections}
        for step in self.steps:
            if step.step_id in seen_steps:
                raise ValueError("question commit history cannot repeat step IDs")
            if step.question_id not in question_ids:
                raise ValueError("question commit history names an unknown Logic question")
            if (
                step.logic_pack_family_id,
                step.logic_pack_release_id,
                step.logic_pack_hash,
            ) != (
                self.logic_pack.family_id,
                self.logic_pack.release_id,
                self.logic_pack.content_hash,
            ):
                raise ValueError("question commit history changed Logic pack identity")
            if (
                step.evidence_closure.run_id,
                step.evidence_closure.result_id,
                step.evidence_closure.domain_id,
            ) != (self.run_id, self.result_id, self.domain_id):
                raise ValueError("question commit history changed Run, Result, or Domain identity")
            if step.answer not in questions[step.question_id].allowed_answers:
                raise ValueError(
                    "question commit history has an answer outside its Logic vocabulary"
                )
            if step.question_id in committed_answers:
                # A later immutable step for an invalidated question is a
                # fresh answer, not a rewrite of its audit predecessor.
                committed_answers.pop(step.question_id)
            if step.question_id not in set(
                evaluator.active_question_ids_for_answers(committed_answers, inputs, judgments)
            ):
                # Corrections are stored independently from answer records so
                # an older dependent step remains auditable after a changed
                # prerequisite. It is intentionally not effective history.
                continue
            expected_entry_hash = QuestionFrontierEntry(
                question_id=step.question_id,
                dependency_context_hash=_dependency_context_hash(
                    questions[step.question_id],
                    evaluator.activation_dependencies(step.question_id),
                    committed_answers,
                    inputs,
                    judgments,
                ),
            ).entry_hash
            if step.expected_frontier_entry_hash != expected_entry_hash:
                # A dependency hash changed after a correction; keep the old
                # record as audit-only and let the recomputed frontier issue
                # a fresh token for a replacement step.
                continue
            seen_steps.add(step.step_id)
            correction = corrections.get(step.question_id)
            committed_answers[step.question_id] = (
                correction.answer if correction is not None else step.answer
            )
        step_hashes = {item.question_id: item.content_hash for item in self.steps}
        seen_corrections: set[str] = set()
        for correction in self.corrections:
            if correction.correction_id in seen_corrections:
                raise ValueError("question correction history cannot repeat correction IDs")
            if correction.question_id not in step_hashes:
                raise ValueError("question correction names no committed answer")
            if correction.prior_step_hash != step_hashes[correction.question_id]:
                raise ValueError("question correction has a stale effective predecessor")
            if correction.answer not in questions[correction.question_id].allowed_answers:
                raise ValueError("question correction has an answer outside its Logic vocabulary")
            if (
                correction.logic_pack_family_id,
                correction.logic_pack_release_id,
                correction.logic_pack_hash,
            ) != (
                self.logic_pack.family_id,
                self.logic_pack.release_id,
                self.logic_pack.content_hash,
            ):
                raise ValueError("question correction changed Logic pack identity")
            if (
                correction.evidence_closure.run_id,
                correction.evidence_closure.result_id,
                correction.evidence_closure.domain_id,
            ) != (self.run_id, self.result_id, self.domain_id):
                raise ValueError("question correction changed Run, Result, or Domain identity")
            committed_answers[correction.question_id] = correction.answer
            step_hashes[correction.question_id] = correction.content_hash
            seen_corrections.add(correction.correction_id)
        seen_stops: set[str] = set()
        for stop in self.diagnostic_stops:
            if stop.stop_id in seen_stops:
                raise ValueError("question diagnostic history cannot repeat stop IDs")
            if stop.question_id in {item.question_id for item in self.steps}:
                raise ValueError(
                    "question history cannot answer and diagnostically stop one question"
                )
            if stop.question_id not in question_ids:
                raise ValueError("question diagnostic history names an unknown Logic question")
            if (
                stop.logic_pack_family_id,
                stop.logic_pack_release_id,
                stop.logic_pack_hash,
            ) != (
                self.logic_pack.family_id,
                self.logic_pack.release_id,
                self.logic_pack.content_hash,
            ):
                raise ValueError("question diagnostic history changed Logic pack identity")
            if (
                stop.evidence_diagnostic.run_id,
                stop.evidence_diagnostic.result_id,
                stop.evidence_diagnostic.domain_id,
            ) != (self.run_id, self.result_id, self.domain_id):
                raise ValueError(
                    "question diagnostic history changed Run, Result, or Domain identity"
                )
            if stop.question_id not in set(
                evaluator.active_question_ids_for_answers(committed_answers, inputs, judgments)
            ):
                raise ValueError("question diagnostic history contains an inactive stop")
            expected_entry_hash = QuestionFrontierEntry(
                question_id=stop.question_id,
                dependency_context_hash=_dependency_context_hash(
                    questions[stop.question_id],
                    evaluator.activation_dependencies(stop.question_id),
                    committed_answers,
                    inputs,
                    judgments,
                ),
            ).entry_hash
            if stop.expected_frontier_entry_hash != expected_entry_hash:
                raise ValueError("question diagnostic history has a stale dependency/frontier hash")
            seen_stops.add(stop.stop_id)
        payload = self.model_dump(mode="json")
        payload["history_hash"] = None
        expected = canonical_hash(payload)
        if self.history_hash and self.history_hash != expected:
            raise ValueError("question ledger history hash must bind every immutable step")
        object.__setattr__(self, "history_hash", expected)
        return self


def new_active_question_ledger(
    logic_pack: LogicPack,
    *,
    run_id: Identifier,
    result_id: Identifier,
    domain_id: Identifier,
    assessor_inputs: tuple[AssessorInputActivationFact, ...] = (),
    prior_domain_judgments: tuple[DomainJudgmentActivationFact, ...] = (),
) -> ActiveQuestionLedger:
    """Start a ledger pinned to one immutable Logic pack release."""

    return ActiveQuestionLedger(
        logic_pack=logic_pack,
        run_id=run_id,
        result_id=result_id,
        domain_id=domain_id,
        assessor_inputs=assessor_inputs,
        prior_domain_judgments=prior_domain_judgments,
    )


def active_question_frontier(ledger: ActiveQuestionLedger) -> ActiveQuestionFrontier:
    """Derive only questions whose activation conditions are already true.

    ``LogicEvaluator`` owns condition semantics.  In particular, absent
    answers cannot satisfy ``answer_in``; this is intentionally not a
    full-domain membership check.
    """

    answers = effective_question_answers(ledger)
    diagnostic_question_ids = {stop.question_id for stop in ledger.diagnostic_stops}
    inputs = {item.input_id: item.value for item in ledger.assessor_inputs}
    judgments = {item.domain_id: item.judgment for item in ledger.prior_domain_judgments}
    evaluator = LogicEvaluator(ledger.logic_pack)
    entries: list[QuestionFrontierEntry] = []
    domain = next(item for item in ledger.logic_pack.domains if item.id == ledger.domain_id)
    active_ids = set(evaluator.active_question_ids_for_answers(answers, inputs, judgments))
    questions = {question.id: question for question in ledger.logic_pack.questions}
    for question_id in domain.question_ids:
        question = questions[question_id]
        if question.id in answers or question.id in diagnostic_question_ids:
            continue
        if question.id not in active_ids:
            continue
        entries.append(
            QuestionFrontierEntry(
                question_id=question.id,
                dependency_context_hash=_dependency_context_hash(
                    question,
                    evaluator.activation_dependencies(question.id),
                    answers,
                    inputs,
                    judgments,
                ),
            )
        )
    status: Literal["active", "complete_with_answers", "diagnostic_terminal"] = "active"
    if not entries:
        status = "diagnostic_terminal" if diagnostic_question_ids else "complete_with_answers"
    return ActiveQuestionFrontier(
        logic_pack_release_id=ledger.logic_pack.release_id,
        logic_pack_hash=ledger.logic_pack.content_hash,
        run_id=ledger.run_id,
        result_id=ledger.result_id,
        domain_id=ledger.domain_id,
        assessor_inputs=ledger.assessor_inputs,
        prior_domain_judgments=ledger.prior_domain_judgments,
        entries=tuple(entries),
        complete=status == "complete_with_answers",
        status=status,
    )


def effective_question_steps(ledger: ActiveQuestionLedger) -> tuple[EffectiveQuestionAnswer, ...]:
    """Replay reachable answers while retaining unreachable history for audit only.

    Corrections replace their exact predecessor for the effective projection.
    If that changes a prerequisite, later stored steps are deliberately not
    deleted; they simply cease to be reachable and must be re-established
    through the normal question frontier.
    """

    corrections = {item.question_id: item for item in ledger.corrections}
    answers: dict[Identifier, SQAnswerCategory] = {}
    effective: list[EffectiveQuestionAnswer] = []
    inputs = {item.input_id: item.value for item in ledger.assessor_inputs}
    judgments = {item.domain_id: item.judgment for item in ledger.prior_domain_judgments}
    evaluator = LogicEvaluator(ledger.logic_pack)
    for step in ledger.steps:
        if step.question_id in answers:
            answers.pop(step.question_id)
            effective = [item for item in effective if item.question_id != step.question_id]
        if step.question_id not in set(
            evaluator.active_question_ids_for_answers(answers, inputs, judgments)
        ):
            continue
        correction = corrections.get(step.question_id)
        if correction is None:
            effective.append(
                EffectiveQuestionAnswer(
                    question_id=step.question_id,
                    answer=step.answer,
                    rationale=step.rationale,
                    evidence_closure=step.evidence_closure,
                    evidence_bundle=step.evidence_bundle,
                    effective_step_hash=step.content_hash,
                )
            )
            answers[step.question_id] = step.answer
        else:
            effective.append(
                EffectiveQuestionAnswer(
                    question_id=correction.question_id,
                    answer=correction.answer,
                    rationale=correction.rationale,
                    evidence_closure=correction.evidence_closure,
                    evidence_bundle=correction.evidence_bundle,
                    effective_step_hash=correction.content_hash,
                )
            )
            answers[step.question_id] = correction.answer
    return tuple(effective)


def effective_question_answers(ledger: ActiveQuestionLedger) -> dict[Identifier, SQAnswerCategory]:
    """Return answers from the current effective (rather than audit) history."""

    return {item.question_id: item.answer for item in effective_question_steps(ledger)}


def append_question_answer(
    ledger: ActiveQuestionLedger,
    step: QuestionAnswerCommitStep,
    workflow: V3EvidenceWorkflowState,
) -> ActiveQuestionLedger:
    """Append one active answer after checking exact evidence and dependencies.

    Replay is idempotent only for the byte-identical logical step.  Frontier
    entry tokens are dependency-scoped, so independently active peer questions
    do not serialize each other merely because one peer commits first.
    """

    existing = next((item for item in ledger.steps if item.step_id == step.step_id), None)
    if existing is not None:
        if existing != step:
            raise ValueError("question commit step ID was replayed with different content")
        return ledger
    if any(item.question_id == step.question_id for item in ledger.diagnostic_stops):
        raise ValueError("question already has an immutable committed answer")
    if (
        step.logic_pack_family_id,
        step.logic_pack_release_id,
        step.logic_pack_hash,
    ) != (
        ledger.logic_pack.family_id,
        ledger.logic_pack.release_id,
        ledger.logic_pack.content_hash,
    ):
        raise ValueError("question commit has changed Logic pack identity")
    domain = next(item for item in ledger.logic_pack.domains if item.id == ledger.domain_id)
    question = next(
        (item for item in ledger.logic_pack.questions if item.id == step.question_id), None
    )
    if question is None:
        raise ValueError("question commit names an unknown Logic question")
    if question.id not in domain.question_ids:
        raise ValueError("question commit names a question outside the ledger Domain")
    if step.answer not in question.allowed_answers:
        raise ValueError("question commit answer is outside its Logic vocabulary")
    frontier = active_question_frontier(ledger)
    entry = next((item for item in frontier.entries if item.question_id == step.question_id), None)
    if entry is None:
        raise ValueError("question commit is inactive or out of order")
    if step.expected_frontier_entry_hash != entry.entry_hash:
        raise ValueError("question commit has a stale dependency/frontier hash")
    if step.evidence_closure != evidence_closure_from_workflow(workflow):
        raise ValueError("question commit evidence closure does not match the closed workflow")
    return ActiveQuestionLedger(
        logic_pack=ledger.logic_pack,
        run_id=ledger.run_id,
        result_id=ledger.result_id,
        domain_id=ledger.domain_id,
        assessor_inputs=ledger.assessor_inputs,
        prior_domain_judgments=ledger.prior_domain_judgments,
        steps=(*ledger.steps, step),
        corrections=ledger.corrections,
        diagnostic_stops=ledger.diagnostic_stops,
    )


def append_question_correction(
    ledger: ActiveQuestionLedger, correction: QuestionAnswerCorrection
) -> ActiveQuestionLedger:
    """Append a correction only against the exact current effective answer."""

    existing = next(
        (item for item in ledger.corrections if item.correction_id == correction.correction_id),
        None,
    )
    if existing is not None:
        if existing != correction:
            raise ValueError("question correction ID was replayed with different content")
        return ledger
    effective_hashes = {item.question_id: item.content_hash for item in ledger.steps}
    for item in ledger.corrections:
        effective_hashes[item.question_id] = item.content_hash
    if effective_hashes.get(correction.question_id) != correction.prior_step_hash:
        raise ValueError("question correction predecessor is stale or conflicting")
    return ActiveQuestionLedger(
        logic_pack=ledger.logic_pack,
        run_id=ledger.run_id,
        result_id=ledger.result_id,
        domain_id=ledger.domain_id,
        assessor_inputs=ledger.assessor_inputs,
        prior_domain_judgments=ledger.prior_domain_judgments,
        steps=ledger.steps,
        corrections=(*ledger.corrections, correction),
        diagnostic_stops=ledger.diagnostic_stops,
    )


def append_question_diagnostic_stop(
    ledger: ActiveQuestionLedger,
    stop: QuestionDiagnosticStop,
    workflow: V3EvidenceWorkflowState,
) -> ActiveQuestionLedger:
    """Remove one active question after a v3 terminal limitation, without answering it."""

    existing = next(
        (item for item in ledger.diagnostic_stops if item.stop_id == stop.stop_id), None
    )
    if existing is not None:
        if existing != stop:
            raise ValueError("question diagnostic stop ID was replayed with different content")
        return ledger
    if any(item.question_id == stop.question_id for item in ledger.steps) or any(
        item.question_id == stop.question_id for item in ledger.diagnostic_stops
    ):
        raise ValueError("question already has an immutable answer or diagnostic stop")
    if (
        stop.logic_pack_family_id,
        stop.logic_pack_release_id,
        stop.logic_pack_hash,
    ) != (
        ledger.logic_pack.family_id,
        ledger.logic_pack.release_id,
        ledger.logic_pack.content_hash,
    ):
        raise ValueError("question diagnostic has changed Logic pack identity")
    frontier = active_question_frontier(ledger)
    entry = next((item for item in frontier.entries if item.question_id == stop.question_id), None)
    if entry is None:
        raise ValueError("question diagnostic is inactive or out of order")
    if stop.expected_frontier_entry_hash != entry.entry_hash:
        raise ValueError("question diagnostic has a stale dependency/frontier hash")
    if stop.evidence_diagnostic != evidence_diagnostic_from_workflow(workflow):
        raise ValueError("question diagnostic does not match the terminal workflow")
    return ActiveQuestionLedger(
        logic_pack=ledger.logic_pack,
        run_id=ledger.run_id,
        result_id=ledger.result_id,
        domain_id=ledger.domain_id,
        assessor_inputs=ledger.assessor_inputs,
        prior_domain_judgments=ledger.prior_domain_judgments,
        steps=ledger.steps,
        corrections=ledger.corrections,
        diagnostic_stops=(*ledger.diagnostic_stops, stop),
    )


def _dependency_context_hash(
    question: Question,
    dependencies: ActivationDependencies,
    answers: dict[str, SQAnswerCategory],
    inputs: dict[str, bool],
    judgments: dict[str, JudgmentLevel],
) -> ContentHash:
    return canonical_hash(
        {
            "question": question.model_dump(mode="json"),
            "dependency_answers": {
                question_id: answers[question_id].value
                for question_id in dependencies.answer_question_ids
                if question_id in answers
            },
            "dependency_inputs": {
                input_id: inputs[input_id]
                for input_id in dependencies.assessor_input_ids
                if input_id in inputs
            },
            "dependency_domain_judgments": {
                domain_id: judgments[domain_id].value
                for domain_id in dependencies.domain_ids
                if domain_id in judgments
            },
        }
    )


def _progress_navigation_closed(progress: dict[str, object]) -> bool:
    """Require reducer-reported terminal, clean navigation for every active stage."""

    for proposition in progress["propositions"]:
        for evidence_pass in proposition["passes"]:
            for stage in evidence_pass["stages"]:
                if stage["active"] and any(
                    not intent["complete"] or not intent["clean"] for intent in stage["intents"]
                ):
                    return False
    return True
