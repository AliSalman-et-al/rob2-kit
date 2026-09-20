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
    activation: AlwaysActive | ConditionalActivation,
    answers: Mapping[str, Answer],
    active: set[str],
) -> bool:
    if isinstance(activation, AlwaysActive):
        return True
    matches = tuple(
        predicate.question_id in active
        and answers.get(predicate.question_id) in predicate.accepted_answers
        for predicate in activation.predicates
    )
    return any(matches) if activation.mode == "any" else all(matches)


def active_questions(answers: Mapping[str, Answer | str]) -> tuple[str, ...]:
    a = _answers(answers)
    active: set[str] = set()
    ordered: list[str] = []
    for question in SCIENTIFIC_PACK.questions:
        if _is_active(question.activation, a, active):
            active.add(question.id)
            ordered.append(question.id)
    return tuple(ordered)


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


def _drivers(domain_id: str, question_ids: set[str]) -> tuple[str, ...]:
    domain = next(domain for domain in SCIENTIFIC_PACK.domains if domain.id == domain_id)
    return tuple(question_id for question_id in domain.question_ids if question_id in question_ids)


def _result(
    domain_id: str,
    judgment: Judgment,
    rule: str,
    question_ids: set[str] | None = None,
) -> Evaluation:
    return Evaluation(
        domain_id=domain_id,
        judgment=judgment,
        trace=(rule,),
        driver_questions=_drivers(domain_id, question_ids or set()),
    )


def evaluate_domain(domain_id: str, answers: Mapping[str, Answer | str]) -> Evaluation:
    a = _validate(domain_id, answers)
    if domain_id == "domain:randomization":
        if a["sq:randomization:concealment"] in NO:
            return _result(
                domain_id,
                Judgment.HIGH,
                "randomization.concealment_failed",
                {"sq:randomization:concealment"},
            )
        if (
            a["sq:randomization:concealment"] == NI
            and a["sq:randomization:baseline-imbalance"] in YES
        ):
            return _result(
                domain_id,
                Judgment.HIGH,
                "randomization.unknown_concealment_and_imbalance",
                {"sq:randomization:concealment", "sq:randomization:baseline-imbalance"},
            )
        if (
            a["sq:randomization:sequence"] in NO
            or a["sq:randomization:concealment"] == NI
            or a["sq:randomization:baseline-imbalance"] in YES
        ):
            return _result(
                domain_id,
                Judgment.SOME_CONCERNS,
                "randomization.some_concerns",
                {
                    question_id
                    for question_id, condition in (
                        ("sq:randomization:sequence", a["sq:randomization:sequence"] in NO),
                        (
                            "sq:randomization:concealment",
                            a["sq:randomization:concealment"] == NI,
                        ),
                        (
                            "sq:randomization:baseline-imbalance",
                            a["sq:randomization:baseline-imbalance"] in YES,
                        ),
                    )
                    if condition
                },
            )
        return _result(domain_id, Judgment.LOW, "randomization.low")
    if domain_id == "domain:deviations":
        if (
            a.get("sq:deviations:context-deviations") in YES
            and a.get("sq:deviations:affected-outcome") in YES | {NI}
            and a.get("sq:deviations:balanced") in NO_OR_UNKNOWN
        ):
            return _result(
                domain_id,
                Judgment.HIGH,
                "deviations.unbalanced_impact",
                {
                    "sq:deviations:context-deviations",
                    "sq:deviations:affected-outcome",
                    "sq:deviations:balanced",
                },
            )
        if a["sq:deviations:appropriate-analysis"] in NO_OR_UNKNOWN and a.get(
            "sq:deviations:substantial-impact"
        ) in YES | {NI}:
            return _result(
                domain_id,
                Judgment.HIGH,
                "deviations.analysis_substantial_impact",
                {"sq:deviations:appropriate-analysis", "sq:deviations:substantial-impact"},
            )
        if (
            a.get("sq:deviations:context-deviations") == NI
            or a.get("sq:deviations:affected-outcome") in NO
            or a.get("sq:deviations:balanced") in YES
            or a.get("sq:deviations:substantial-impact") in NO
        ):
            return _result(
                domain_id,
                Judgment.SOME_CONCERNS,
                "deviations.some_concerns",
                {
                    question_id
                    for question_id, condition in (
                        (
                            "sq:deviations:context-deviations",
                            a.get("sq:deviations:context-deviations") == NI,
                        ),
                        (
                            "sq:deviations:affected-outcome",
                            a.get("sq:deviations:affected-outcome") in NO,
                        ),
                        (
                            "sq:deviations:balanced",
                            a.get("sq:deviations:balanced") in YES,
                        ),
                        (
                            "sq:deviations:substantial-impact",
                            a.get("sq:deviations:substantial-impact") in NO,
                        ),
                    )
                    if condition
                },
            )
        return _result(domain_id, Judgment.LOW, "deviations.low")
    if domain_id == "domain:missing":
        if (
            a["sq:missing:data-available"] in YES
            or a.get("sq:missing:evidence-unbiased") in YES
            or a.get("sq:missing:true-value-dependent") in NO
        ):
            return _result(domain_id, Judgment.LOW, "missing.low")
        if a.get("sq:missing:likely-dependent") in YES | {NI}:
            return _result(
                domain_id,
                Judgment.HIGH,
                "missing.likely_dependent",
                {"sq:missing:likely-dependent"},
            )
        return _result(
            domain_id,
            Judgment.SOME_CONCERNS,
            "missing.some_concerns",
            {
                "sq:missing:data-available",
                "sq:missing:evidence-unbiased",
                "sq:missing:true-value-dependent",
                "sq:missing:likely-dependent",
            },
        )
    if domain_id == "domain:measurement":
        if (
            a["sq:measurement:method-inappropriate"] in YES
            or a["sq:measurement:differential"] in YES
        ):
            return _result(
                domain_id,
                Judgment.HIGH,
                "measurement.inappropriate_or_differential",
                {
                    question_id
                    for question_id, condition in (
                        (
                            "sq:measurement:method-inappropriate",
                            a["sq:measurement:method-inappropriate"] in YES,
                        ),
                        (
                            "sq:measurement:differential",
                            a["sq:measurement:differential"] in YES,
                        ),
                    )
                    if condition
                },
            )
        if a.get("sq:measurement:influence-likely") in YES | {NI}:
            return _result(
                domain_id,
                Judgment.HIGH,
                "measurement.likely_influenced",
                {"sq:measurement:influence-likely"},
            )
        if a["sq:measurement:differential"] == NI or a.get("sq:measurement:influence-likely") in NO:
            return _result(
                domain_id,
                Judgment.SOME_CONCERNS,
                "measurement.some_concerns",
                {
                    question_id
                    for question_id, condition in (
                        (
                            "sq:measurement:differential",
                            a["sq:measurement:differential"] == NI,
                        ),
                        (
                            "sq:measurement:influence-likely",
                            a.get("sq:measurement:influence-likely") in NO,
                        ),
                    )
                    if condition
                },
            )
        return _result(domain_id, Judgment.LOW, "measurement.low")
    if domain_id == "domain:selection":
        if (
            a["sq:selection:multiple-measurements"] in YES
            or a["sq:selection:multiple-analyses"] in YES
        ):
            return _result(
                domain_id,
                Judgment.HIGH,
                "selection.selective_choice",
                {
                    question_id
                    for question_id, condition in (
                        (
                            "sq:selection:multiple-measurements",
                            a["sq:selection:multiple-measurements"] in YES,
                        ),
                        (
                            "sq:selection:multiple-analyses",
                            a["sq:selection:multiple-analyses"] in YES,
                        ),
                    )
                    if condition
                },
            )
        if (
            a["sq:selection:prespecified-analysis"] in NO_OR_UNKNOWN
            or a["sq:selection:multiple-measurements"] == NI
            or a["sq:selection:multiple-analyses"] == NI
        ):
            return _result(
                domain_id,
                Judgment.SOME_CONCERNS,
                "selection.some_concerns",
                {
                    question_id
                    for question_id, condition in (
                        (
                            "sq:selection:prespecified-analysis",
                            a["sq:selection:prespecified-analysis"] in NO_OR_UNKNOWN,
                        ),
                        (
                            "sq:selection:multiple-measurements",
                            a["sq:selection:multiple-measurements"] == NI,
                        ),
                        (
                            "sq:selection:multiple-analyses",
                            a["sq:selection:multiple-analyses"] == NI,
                        ),
                    )
                    if condition
                },
            )
        return _result(domain_id, Judgment.LOW, "selection.low")
    raise AssertionError("unreachable")


def evaluate_overall(judgments: Mapping[str, Judgment | str]) -> OverallEvaluation:
    """Apply the deterministic Cochrane-style overall RoB 2 rule."""

    values = {key: Judgment(value) for key, value in judgments.items()}
    expected = {d.id for d in SCIENTIFIC_PACK.domains}
    if set(values) != expected:
        raise ValueError("all five domain judgments are required")
    if Judgment.HIGH in values.values():
        return OverallEvaluation(
            judgment=Judgment.HIGH,
            trace=("overall.any_high",),
            driver_domains=tuple(
                domain.id
                for domain in SCIENTIFIC_PACK.domains
                if values[domain.id] is Judgment.HIGH
            ),
        )
    concerns = sum(value == Judgment.SOME_CONCERNS for value in values.values())
    if concerns >= 2:
        return OverallEvaluation(
            judgment=Judgment.HIGH,
            trace=("overall.multiple_some_concerns_high",),
            driver_domains=tuple(
                domain.id
                for domain in SCIENTIFIC_PACK.domains
                if values[domain.id] is Judgment.SOME_CONCERNS
            ),
        )
    if concerns:
        return OverallEvaluation(
            judgment=Judgment.SOME_CONCERNS,
            trace=("overall.any_concerns",),
            driver_domains=tuple(
                domain.id
                for domain in SCIENTIFIC_PACK.domains
                if values[domain.id] is Judgment.SOME_CONCERNS
            ),
        )
    return OverallEvaluation(judgment=Judgment.LOW, trace=("overall.all_low",))
