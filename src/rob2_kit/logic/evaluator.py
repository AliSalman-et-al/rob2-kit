"""Deterministic transcription of the official RoB 2 proposed-judgement tables."""

from __future__ import annotations

from collections.abc import Mapping

from rob2_kit.models import (
    AlwaysActive,
    Answer,
    ConditionalActivation,
    Evaluation,
    Judgment,
    OverallEvaluation,
)
from rob2_kit.packs.scientific import SCIENTIFIC_PACK

Y, PY, PN, N, NI = (
    Answer.YES,
    Answer.PROBABLY_YES,
    Answer.PROBABLY_NO,
    Answer.NO,
    Answer.NO_INFORMATION,
)
YES = {Y, PY}
NO = {PN, N}
NO_OR_UNKNOWN = {PN, N, NI}


def _answers(answers: Mapping[str, Answer | str]) -> dict[str, Answer]:
    try:
        return {key: Answer(value) for key, value in answers.items()}
    except ValueError as error:
        raise ValueError("unknown signalling answer") from error


def _is_active(
    activation: AlwaysActive | ConditionalActivation, answers: Mapping[str, Answer]
) -> bool:
    if isinstance(activation, AlwaysActive):
        return True
    matches = (
        answers.get(predicate.question_id) in predicate.accepted_answers
        for predicate in activation.predicates
    )
    return any(matches) if activation.mode == "any" else all(matches)


def active_questions(answers: Mapping[str, Answer | str]) -> tuple[str, ...]:
    a = _answers(answers)
    return tuple(
        question.id for question in SCIENTIFIC_PACK.questions if _is_active(question.activation, a)
    )


def _validate(domain_id: str, answers: Mapping[str, Answer | str]) -> dict[str, Answer]:
    a = _answers(answers)
    known_questions = {question.id for question in SCIENTIFIC_PACK.questions}
    if unknown := set(a) - known_questions:
        raise ValueError(f"unknown signalling question: {sorted(unknown)}")
    domain = next((d for d in SCIENTIFIC_PACK.domains if d.id == domain_id), None)
    if domain is None:
        raise ValueError(f"unknown domain: {domain_id}")
    active = set(active_questions(a)) & set(domain.question_ids)
    got = set(a) & set(domain.question_ids)
    if got != active:
        raise ValueError(
            "answers must be supplied exactly for active questions; "
            f"missing={sorted(active - got)}, inactive={sorted(got - active)}"
        )
    for q in SCIENTIFIC_PACK.questions:
        if q.id in got and a[q.id] not in q.allowed_answers:
            raise ValueError(f"answer is not allowed for {q.id}")
    return a


def _result(domain_id: str, judgment: Judgment, rule: str) -> Evaluation:
    return Evaluation(domain_id=domain_id, judgment=judgment, trace=(rule,))


def evaluate_domain(domain_id: str, answers: Mapping[str, Answer | str]) -> Evaluation:
    a = _validate(domain_id, answers)
    if domain_id == "domain:randomization":
        if a["sq:randomization:concealment"] in NO:
            return _result(domain_id, Judgment.HIGH, "randomization.concealment_failed")
        if (
            a["sq:randomization:concealment"] == NI
            and a["sq:randomization:baseline-imbalance"] in YES
        ):
            return _result(
                domain_id, Judgment.HIGH, "randomization.unknown_concealment_and_imbalance"
            )
        if (
            a["sq:randomization:sequence"] in NO
            or a["sq:randomization:concealment"] == NI
            or a["sq:randomization:baseline-imbalance"] in YES
        ):
            return _result(domain_id, Judgment.SOME_CONCERNS, "randomization.some_concerns")
        return _result(domain_id, Judgment.LOW, "randomization.low")
    if domain_id == "domain:deviations":
        if (
            a.get("sq:deviations:context-deviations") in YES
            and a.get("sq:deviations:affected-outcome") in YES | {NI}
            and a.get("sq:deviations:balanced") in NO_OR_UNKNOWN
        ):
            return _result(domain_id, Judgment.HIGH, "deviations.unbalanced_impact")
        if a["sq:deviations:appropriate-analysis"] in NO_OR_UNKNOWN and a.get(
            "sq:deviations:substantial-impact"
        ) in YES | {NI}:
            return _result(domain_id, Judgment.HIGH, "deviations.analysis_substantial_impact")
        if (
            a.get("sq:deviations:context-deviations") == NI
            or a.get("sq:deviations:affected-outcome") in NO
            or a.get("sq:deviations:balanced") in YES
            or a.get("sq:deviations:substantial-impact") in NO
        ):
            return _result(domain_id, Judgment.SOME_CONCERNS, "deviations.some_concerns")
        return _result(domain_id, Judgment.LOW, "deviations.low")
    if domain_id == "domain:missing":
        if (
            a["sq:missing:data-available"] in YES
            or a.get("sq:missing:evidence-unbiased") in YES
            or a.get("sq:missing:true-value-dependent") in NO
        ):
            return _result(domain_id, Judgment.LOW, "missing.low")
        if a.get("sq:missing:likely-dependent") in YES | {NI}:
            return _result(domain_id, Judgment.HIGH, "missing.likely_dependent")
        return _result(domain_id, Judgment.SOME_CONCERNS, "missing.some_concerns")
    if domain_id == "domain:measurement":
        if (
            a["sq:measurement:method-inappropriate"] in YES
            or a["sq:measurement:differential"] in YES
        ):
            return _result(domain_id, Judgment.HIGH, "measurement.inappropriate_or_differential")
        if a.get("sq:measurement:influence-likely") in YES | {NI}:
            return _result(domain_id, Judgment.HIGH, "measurement.likely_influenced")
        if a["sq:measurement:differential"] == NI or a.get("sq:measurement:influence-likely") in NO:
            return _result(domain_id, Judgment.SOME_CONCERNS, "measurement.some_concerns")
        return _result(domain_id, Judgment.LOW, "measurement.low")
    if domain_id == "domain:selection":
        if (
            a["sq:selection:multiple-measurements"] in YES
            or a["sq:selection:multiple-analyses"] in YES
        ):
            return _result(domain_id, Judgment.HIGH, "selection.selective_choice")
        if (
            a["sq:selection:prespecified-analysis"] in NO_OR_UNKNOWN
            or a["sq:selection:multiple-measurements"] == NI
            or a["sq:selection:multiple-analyses"] == NI
        ):
            return _result(domain_id, Judgment.SOME_CONCERNS, "selection.some_concerns")
        return _result(domain_id, Judgment.LOW, "selection.low")
    raise AssertionError("unreachable")


def evaluate_overall(
    judgments: Mapping[str, Judgment | str], *, combined_concerns: bool | None = None
) -> OverallEvaluation:
    values = {key: Judgment(value) for key, value in judgments.items()}
    expected = {d.id for d in SCIENTIFIC_PACK.domains}
    if set(values) != expected:
        raise ValueError("all five domain judgments are required")
    if Judgment.HIGH in values.values():
        return OverallEvaluation(judgment=Judgment.HIGH, trace=("overall.any_high",))
    concerns = sum(value == Judgment.SOME_CONCERNS for value in values.values())
    if concerns >= 2:
        if combined_concerns is None:
            raise ValueError("combined_concerns is required for multiple Some concerns domains")
        return OverallEvaluation(
            judgment=Judgment.HIGH if combined_concerns else Judgment.SOME_CONCERNS,
            trace=("overall.combined_concerns",),
        )
    if concerns:
        return OverallEvaluation(judgment=Judgment.SOME_CONCERNS, trace=("overall.any_concerns",))
    return OverallEvaluation(judgment=Judgment.LOW, trace=("overall.all_low",))
