from typing import Any

import pytest
from pydantic import ValidationError

from rob2_kit.models import (
    ActivationPredicate,
    Answer,
    ConditionalActivation,
    GuidanceAnchor,
    OfficialQuestionGuidance,
    OperationalQuestionGuidance,
    Question,
    QuestionGuidance,
    ScientificPack,
)

_GUIDANCE = QuestionGuidance(
    official=OfficialQuestionGuidance(
        version="test",
        source_locator="test source, question 1",
        source_sha256="A" * 64,
        source_excerpt="the test official source excerpt",
    ),
    operational=OperationalQuestionGuidance(
        id="test-guidance",
        version="1",
        attribution="test",
        bias_construct="the test construct",
        decision_rule="apply the test decision rule",
        evidence_needed=("the test evidence",),
        no_information_rule="use no_information when the test evidence is unavailable",
        answer_anchors=(GuidanceAnchor(answer=Answer.YES, text="the test yes anchor"),),
        considerations=("the test consideration",),
        invalid_shortcuts=("the test shortcut",),
    ),
)


def _question(**values: Any) -> Question:
    values.setdefault("guidance", _GUIDANCE)
    return Question(**values)


@pytest.mark.parametrize(
    "questions",
    (
        (
            _question(
                id="first",
                domain_id="domain",
                wording="first",
                activation=ConditionalActivation(
                    mode="any",
                    predicates=(
                        ActivationPredicate(question_id="second", accepted_answers=(Answer.YES,)),
                    ),
                ),
            ),
            _question(id="second", domain_id="domain", wording="second"),
        ),
        (
            _question(id="first", domain_id="other-domain", wording="first"),
            _question(
                id="second",
                domain_id="domain",
                wording="second",
                activation=ConditionalActivation(
                    mode="any",
                    predicates=(
                        ActivationPredicate(question_id="first", accepted_answers=(Answer.YES,)),
                    ),
                ),
            ),
        ),
    ),
)
def test_activation_predicates_target_earlier_questions_in_the_same_domain(
    questions: tuple[Question, ...],
) -> None:
    with pytest.raises(ValidationError):
        ScientificPack(
            id="pack",
            version="1",
            provenance={
                "id": "source",
                "title": "source",
                "version": "1",
                "url": "https://example.invalid",
                "locator": "here",
                "attribution": "source",
            },
            questions=questions,
            domains=(),
            content_hash="sha256:test",
        )
