# ruff: noqa: E501
"""Independently transcribed RoB 2 parallel-assignment question pack."""

import json
from pathlib import Path
from typing import Literal

from rob2_kit.models import (
    ActivationPredicate,
    AlwaysActive,
    Answer,
    ConditionalActivation,
    Domain,
    OfficialDomainGuidance,
    OfficialQuestionGuidance,
    Provenance,
    QuerySuggestion,
    Question,
    QuestionGuidance,
    QuestionNavigation,
    ScientificPack,
    sha256,
)

_P = Provenance(
    id="cochrane-rob2-2019",
    title="RoB 2: a revised tool for assessing risk of bias in randomised trials",
    version="22 August 2019",
    url="https://www.riskofbias.info/welcome/rob-2-0-tool/current-version-of-rob-2",
    locator="Full guidance pp. 17, 28-29, 45-46, 54, 63-65 (Boxes 4, 6, 8, 10, 11)",
    attribution="Sterne et al.; Cochrane RoB 2 authors",
)

_ALWAYS = AlwaysActive()
_YES = (Answer.YES, Answer.PROBABLY_YES)
_YES_OR_UNKNOWN = _YES + (Answer.NO_INFORMATION,)
_NO = (Answer.PROBABLY_NO, Answer.NO)
_NO_OR_UNKNOWN = _NO + (Answer.NO_INFORMATION,)


def _predicate(question_id: str, answers: tuple[Answer, ...]) -> ActivationPredicate:
    return ActivationPredicate(question_id=question_id, accepted_answers=answers)


def _rule(mode: Literal["any", "all"], *predicates: ActivationPredicate) -> ConditionalActivation:
    return ConditionalActivation(mode=mode, predicates=predicates)


_GUIDANCE_VERSION = "22 August 2019"
_GUIDANCE_SOURCE_SHA256 = "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670"
_OFFICIAL_CONTENT = json.loads(
    Path(__file__).with_name("official-guidance.json").read_text(encoding="utf-8")
)
_OFFICIAL_ELABORATIONS: dict[str, str] = _OFFICIAL_CONTENT["questions"]
_QUESTION_LOCATORS = {
    "sq:randomization:sequence": "Full guidance p. 17, Box 4, signalling question 1.1",
    "sq:randomization:concealment": "Full guidance p. 17, Box 4, signalling question 1.2",
    "sq:randomization:baseline-imbalance": "Full guidance pp. 17-18, Box 4, signalling question 1.3",
    "sq:deviations:participants-aware": "Full guidance p. 28, Box 6, signalling question 2.1",
    "sq:deviations:personnel-aware": "Full guidance p. 28, Box 6, signalling question 2.2",
    "sq:deviations:context-deviations": "Full guidance p. 28, Box 6, signalling question 2.3",
    "sq:deviations:affected-outcome": "Full guidance p. 28, Box 6, signalling question 2.4",
    "sq:deviations:balanced": "Full guidance p. 29, Box 6, signalling question 2.5",
    "sq:deviations:appropriate-analysis": "Full guidance p. 29, Box 6, signalling question 2.6",
    "sq:deviations:substantial-impact": "Full guidance p. 29, Box 6, signalling question 2.7",
    "sq:missing:data-available": "Full guidance p. 45, Box 8, signalling question 3.1",
    "sq:missing:evidence-unbiased": "Full guidance p. 45, Box 8, signalling question 3.2",
    "sq:missing:true-value-dependent": "Full guidance p. 45, Box 8, signalling question 3.3",
    "sq:missing:likely-dependent": "Full guidance pp. 45-46, Box 8, signalling question 3.4",
    "sq:measurement:method-inappropriate": "Full guidance p. 54, Box 10, signalling question 4.1",
    "sq:measurement:differential": "Full guidance p. 54, Box 10, signalling question 4.2",
    "sq:measurement:assessor-aware": "Full guidance p. 54, Box 10, signalling question 4.3",
    "sq:measurement:influence-possible": "Full guidance p. 54, Box 10, signalling question 4.4",
    "sq:measurement:influence-likely": "Full guidance p. 54, Box 10, signalling question 4.5",
    "sq:selection:prespecified-analysis": "Full guidance p. 63, Box 11, signalling question 5.1",
    "sq:selection:multiple-measurements": "Full guidance pp. 63-64, Box 11, signalling question 5.2",
    "sq:selection:multiple-analyses": "Full guidance pp. 64-65, Box 11, signalling question 5.3",
}


def _suggestion(
    query: str,
    mode: Literal["all", "phrase", "any", "prefix"],
    purpose: str,
    source_role: Literal["main_article", "registry", "supplement", "sap", "protocol", "other"]
    | None = None,
) -> QuerySuggestion:
    return QuerySuggestion(query=query, mode=mode, source_role=source_role, purpose=purpose)


# These are retrieval vocabulary, not claims about what every Source contains.
# Keep each question's set short so a host can execute alternatives directly.
_QUERY_SUGGESTIONS: dict[str, tuple[QuerySuggestion, ...]] = {
    "sq:randomization:sequence": (
        _suggestion(
            "computer generated random numbers", "all", "computer sequence generation", "protocol"
        ),
        _suggestion("randomly permuted blocks", "phrase", "randomized block sequence", "protocol"),
        _suggestion("minimization", "any", "minimization sequence method", "protocol"),
        _suggestion("random number table", "phrase", "random sequence method", "protocol"),
        _suggestion("coin tossing", "phrase", "physical random sequence method"),
    ),
    "sq:randomization:concealment": (
        _suggestion("allocation concealment", "all", "concealment method", "protocol"),
        _suggestion("central randomization", "phrase", "central allocation", "protocol"),
        _suggestion("interactive web response system", "phrase", "remote allocation", "protocol"),
        _suggestion("IWRS", "prefix", "remote allocation acronym", "protocol"),
        _suggestion("opaque sealed envelopes", "phrase", "envelope safeguards", "protocol"),
    ),
    "sq:randomization:baseline-imbalance": (
        _suggestion("baseline characteristics", "all", "baseline group comparison"),
        _suggestion("baseline imbalance", "phrase", "randomization imbalance"),
    ),
    "sq:deviations:participants-aware": (
        _suggestion("participant blinding", "all", "participant awareness"),
        _suggestion("open label", "phrase", "unblinded participant conduct"),
        _suggestion("side effects", "phrase", "intervention-specific unblinding"),
    ),
    "sq:deviations:personnel-aware": (
        _suggestion("personnel blinding", "all", "carer awareness"),
        _suggestion("double blind", "phrase", "blinding description"),
        _suggestion("intervention provider", "phrase", "delivery personnel"),
    ),
    "sq:deviations:context-deviations": (
        _suggestion("nonadherence", "any", "deviations from assigned intervention"),
        _suggestion("treatment contamination", "phrase", "cross-group intervention"),
        _suggestion(
            "protocol deviation", "phrase", "reported deviations and their causes", "protocol"
        ),
    ),
    "sq:deviations:affected-outcome": (
        _suggestion("effect estimate", "phrase", "deviation impact on outcome"),
        _suggestion("outcome affected", "all", "deviation effect"),
    ),
    "sq:deviations:balanced": (
        _suggestion("between intervention groups", "phrase", "balance of deviations"),
        _suggestion("differential nonadherence", "phrase", "unequal deviations"),
    ),
    "sq:deviations:appropriate-analysis": (
        _suggestion("intention-to-treat", "phrase", "analysis by assignment"),
        _suggestion("intent-to-treat", "phrase", "alternative analysis-by-assignment wording"),
        _suggestion("all randomized patients", "all", "reported analysis population"),
        _suggestion("per protocol", "phrase", "analysis restrictions"),
    ),
    "sq:deviations:substantial-impact": (
        _suggestion("excluded participants", "all", "post-randomization exclusions"),
        _suggestion("wrong intervention group", "phrase", "analysis group mismatch"),
    ),
    "sq:missing:data-available": (
        _suggestion("missing outcome data", "all", "outcome availability"),
        _suggestion("loss to follow-up", "phrase", "follow-up completeness"),
        _suggestion("participant flow", "phrase", "randomized follow-up accounting"),
        _suggestion("CONSORT", "phrase", "participant-flow diagram", "supplement"),
        _suggestion("outcome data available", "all", "observed outcome reporting"),
        _suggestion("mortality status unknown", "all", "unknown mortality status", "supplement"),
        _suggestion("missing values", "all", "missing outcome counts", "supplement"),
    ),
    "sq:missing:evidence-unbiased": (
        _suggestion("sensitivity analysis", "phrase", "missing-data sensitivity analysis", "sap"),
        _suggestion("missing data bias", "all", "bias from missing outcomes"),
        _suggestion("multiple imputation", "phrase", "missing-data method", "sap"),
    ),
    "sq:missing:true-value-dependent": (
        _suggestion("reason for withdrawal", "all", "missingness reason"),
        _suggestion("loss to follow-up", "phrase", "health-related missingness"),
    ),
    "sq:missing:likely-dependent": (
        _suggestion("censoring", "any", "outcome-dependent missingness"),
        _suggestion("missing by treatment group", "all", "differential missingness"),
        _suggestion("reason for missing outcome", "all", "missingness mechanism"),
    ),
    "sq:measurement:method-inappropriate": (
        _suggestion("outcome measurement validity", "all", "measurement validity"),
        _suggestion("sensitive to treatment effect", "phrase", "measurement sensitivity"),
    ),
    "sq:measurement:differential": (
        _suggestion("same measurement method", "phrase", "comparable ascertainment"),
        _suggestion("diagnostic detection bias", "phrase", "differential detection"),
        _suggestion("measurement threshold", "phrase", "between-group measurement threshold"),
    ),
    "sq:measurement:assessor-aware": (
        _suggestion("outcome assessor blinding", "all", "assessor awareness"),
        _suggestion("assessor blinded", "phrase", "blinded outcome assessment"),
    ),
    "sq:measurement:influence-possible": (
        _suggestion("participant reported outcome", "phrase", "participant assessment influence"),
        _suggestion("observer reported outcome", "phrase", "observer judgement influence"),
    ),
    "sq:measurement:influence-likely": (
        _suggestion("beliefs about treatment", "all", "belief-driven assessment influence"),
        _suggestion("assessment influenced", "phrase", "reported influence on outcome"),
    ),
    "sq:selection:prespecified-analysis": (
        _suggestion("analysis plan", "phrase", "prespecified analysis", "sap"),
        _suggestion("prespecified final analysis", "all", "reported final-analysis timing"),
        _suggestion("final analysis", "phrase", "reported analysis threshold"),
        _suggestion("before unblinding", "phrase", "analysis timing", "protocol"),
        _suggestion("statistical analysis plan", "phrase", "finalized analysis plan", "sap"),
    ),
    "sq:selection:multiple-measurements": (
        _suggestion(
            "multiple outcome measures", "all", "eligible outcome measurements", "protocol"
        ),
        _suggestion("time points", "any", "eligible outcome timing", "protocol"),
        _suggestion("outcome scale", "phrase", "eligible measurement scales", "protocol"),
    ),
    "sq:selection:multiple-analyses": (
        _suggestion("multiple analyses", "phrase", "eligible analysis methods", "sap"),
        _suggestion("analysis methods", "all", "planned analysis alternatives", "sap"),
        _suggestion("adjusted analysis", "phrase", "analysis adjustment choice", "sap"),
    ),
}

_GUIDANCE = {
    question_id: QuestionGuidance(
        official=OfficialQuestionGuidance(
            version=_GUIDANCE_VERSION,
            source_locator=locator,
            source_sha256=_GUIDANCE_SOURCE_SHA256,
            source_excerpt=_OFFICIAL_ELABORATIONS[locator],
        ),
        operational=QuestionNavigation(
            id="rob2-kit.parallel-assignment.question-navigation",
            version="1.0.0",
            attribution="rob2-kit maintainers",
            query_suggestions=_QUERY_SUGGESTIONS[question_id],
        ),
    )
    for question_id, locator in _QUESTION_LOCATORS.items()
}

_Q = (
    (
        "sq:randomization:sequence",
        "domain:randomization",
        "Was the allocation sequence random?",
        _ALWAYS,
    ),
    (
        "sq:randomization:concealment",
        "domain:randomization",
        "Was the allocation sequence concealed until participants were enrolled and assigned to interventions?",
        _ALWAYS,
    ),
    (
        "sq:randomization:baseline-imbalance",
        "domain:randomization",
        "Did baseline differences between intervention groups suggest a problem with the randomization process?",
        _ALWAYS,
    ),
    (
        "sq:deviations:participants-aware",
        "domain:deviations",
        "Were participants aware of their assigned intervention during the trial?",
        _ALWAYS,
    ),
    (
        "sq:deviations:personnel-aware",
        "domain:deviations",
        "Were carers and people delivering the interventions aware of participants' assigned intervention during the trial?",
        _ALWAYS,
    ),
    (
        "sq:deviations:context-deviations",
        "domain:deviations",
        "If Y/PY/NI to 2.1 or 2.2: Were there deviations from the intended intervention that arose because of the trial context?",
        _rule(
            "any",
            _predicate("sq:deviations:participants-aware", _YES_OR_UNKNOWN),
            _predicate("sq:deviations:personnel-aware", _YES_OR_UNKNOWN),
        ),
    ),
    (
        "sq:deviations:affected-outcome",
        "domain:deviations",
        "If Y/PY to 2.3: Were these deviations likely to have affected the outcome?",
        _rule("any", _predicate("sq:deviations:context-deviations", _YES)),
    ),
    (
        "sq:deviations:balanced",
        "domain:deviations",
        "If Y/PY/NI to 2.4: Were these deviations from intended intervention balanced between groups?",
        _rule("any", _predicate("sq:deviations:affected-outcome", _YES_OR_UNKNOWN)),
    ),
    (
        "sq:deviations:appropriate-analysis",
        "domain:deviations",
        "Was an appropriate analysis used to estimate the effect of assignment to intervention?",
        _ALWAYS,
    ),
    (
        "sq:deviations:substantial-impact",
        "domain:deviations",
        "If N/PN/NI to 2.6: Was there potential for a substantial impact (on the result) of the failure to analyse participants in the group to which they were randomized?",
        _rule("any", _predicate("sq:deviations:appropriate-analysis", _NO_OR_UNKNOWN)),
    ),
    (
        "sq:missing:data-available",
        "domain:missing",
        "Were data for this outcome available for all, or nearly all, participants randomized?",
        _ALWAYS,
    ),
    (
        "sq:missing:evidence-unbiased",
        "domain:missing",
        "If N/PN/NI to 3.1: Is there evidence that the result was not biased by missing outcome data?",
        _rule("any", _predicate("sq:missing:data-available", _NO_OR_UNKNOWN)),
        (Answer.YES, Answer.PROBABLY_YES, Answer.PROBABLY_NO, Answer.NO),
    ),
    (
        "sq:missing:true-value-dependent",
        "domain:missing",
        "If N/PN to 3.2: Could missingness in the outcome depend on its true value?",
        _rule("any", _predicate("sq:missing:evidence-unbiased", _NO)),
    ),
    (
        "sq:missing:likely-dependent",
        "domain:missing",
        "If Y/PY/NI to 3.3: Is it likely that missingness in the outcome depended on its true value?",
        _rule("any", _predicate("sq:missing:true-value-dependent", _YES_OR_UNKNOWN)),
    ),
    (
        "sq:measurement:method-inappropriate",
        "domain:measurement",
        "Was the method of measuring the outcome inappropriate?",
        _ALWAYS,
    ),
    (
        "sq:measurement:differential",
        "domain:measurement",
        "Could measurement or ascertainment of the outcome have differed between intervention groups?",
        _ALWAYS,
    ),
    (
        "sq:measurement:assessor-aware",
        "domain:measurement",
        "If N/PN/NI to 4.1 and 4.2: Were outcome assessors aware of the intervention received by study participants?",
        _rule(
            "all",
            _predicate("sq:measurement:method-inappropriate", _NO_OR_UNKNOWN),
            _predicate("sq:measurement:differential", _NO_OR_UNKNOWN),
        ),
    ),
    (
        "sq:measurement:influence-possible",
        "domain:measurement",
        "If Y/PY/NI to 4.3: Could assessment of the outcome have been influenced by knowledge of intervention received?",
        _rule("any", _predicate("sq:measurement:assessor-aware", _YES_OR_UNKNOWN)),
    ),
    (
        "sq:measurement:influence-likely",
        "domain:measurement",
        "If Y/PY/NI to 4.4: Is it likely that assessment of the outcome was influenced by knowledge of intervention received?",
        _rule("any", _predicate("sq:measurement:influence-possible", _YES_OR_UNKNOWN)),
    ),
    (
        "sq:selection:prespecified-analysis",
        "domain:selection",
        "Were the data that produced this result analysed in accordance with a pre-specified analysis plan that was finalized before unblinded outcome data were available for analysis?",
        _ALWAYS,
    ),
    (
        "sq:selection:multiple-measurements",
        "domain:selection",
        "Is the numerical result being assessed likely to have been selected, on the basis of the results, from multiple eligible outcome measurements (e.g. scales, definitions, time points) within the outcome domain?",
        _ALWAYS,
    ),
    (
        "sq:selection:multiple-analyses",
        "domain:selection",
        "Is the numerical result being assessed likely to have been selected, on the basis of the results, from multiple eligible analyses of the data?",
        _ALWAYS,
    ),
)
_QUESTIONS = tuple(
    Question(
        id=i,
        domain_id=d,
        wording=w,
        activation=a,
        allowed_answers=answers[0] if answers else tuple(Answer),
        guidance=_GUIDANCE[i],
    )
    for i, d, w, a, *answers in _Q
)
_DOMAINS = tuple(
    Domain(id=domain, question_ids=tuple(q.id for q in _QUESTIONS if q.domain_id == domain))
    for domain in (
        "domain:randomization",
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    )
)
_CONTENT = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "provenance": _P,
    "questions": _QUESTIONS,
    "domains": _DOMAINS,
    "official_sections": tuple(
        OfficialDomainGuidance(
            domain_id=section["domain_id"],
            question_ids=tuple(section.get("question_ids", ())),
            source_url=section.get("source_url", _OFFICIAL_CONTENT["source_url"]),
            guidance=OfficialQuestionGuidance(
                version=section.get("version", _GUIDANCE_VERSION),
                source_sha256=section.get("source_sha256", _GUIDANCE_SOURCE_SHA256),
                source_locator=section["source_locator"],
                source_excerpt=section["source_excerpt"],
            ),
        )
        for section in _OFFICIAL_CONTENT["sections"]
    ),
}
SCIENTIFIC_PACK = ScientificPack(**_CONTENT, content_hash=sha256(_CONTENT))


def load_scientific_pack(data: dict[str, object]) -> ScientificPack:
    """Validate a serialized pack and reject a mismatched declared identity hash."""

    pack = ScientificPack.model_validate(data)
    content = pack.model_dump(mode="python", exclude={"content_hash"}, exclude_none=True)
    if pack.content_hash != sha256(content):
        raise ValueError("scientific pack content hash does not match its content")
    return pack
