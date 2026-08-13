# ruff: noqa: E501
"""Independently transcribed RoB 2 parallel-assignment question pack.

Wording and algorithms are from the official 22 August 2019 full guidance,
Boxes 4, 6, 8, 10 and 11.  The separate evaluator implements its tables.
"""

from rob2_kit.models import Answer, Domain, Provenance, Question, ScientificPack, sha256

_P = Provenance(
    id="cochrane-rob2-2019",
    title="RoB 2: a revised tool for assessing risk of bias in randomised trials",
    version="22 August 2019",
    url="https://www.riskofbias.info/welcome/rob-2-0-tool/current-version-of-rob-2",
    locator="Full guidance pp. 17, 28-29, 45-46, 54, 63-65 (Boxes 4, 6, 8, 10, 11)",
    attribution="Sterne et al.; Cochrane RoB 2 authors",
)

_Q = (
    (
        "sq:randomization:sequence",
        "domain:randomization",
        "Was the allocation sequence random?",
        None,
        None,
    ),
    (
        "sq:randomization:concealment",
        "domain:randomization",
        "Was the allocation sequence concealed until participants were enrolled and assigned to interventions?",
        None,
        None,
    ),
    (
        "sq:randomization:baseline-imbalance",
        "domain:randomization",
        "Did baseline differences between intervention groups suggest a problem with the randomization process?",
        None,
        None,
    ),
    (
        "sq:deviations:participants-aware",
        "domain:deviations",
        "Were participants aware of their assigned intervention during the trial?",
        None,
        None,
    ),
    (
        "sq:deviations:personnel-aware",
        "domain:deviations",
        "Were carers and people delivering the interventions aware of participants' assigned intervention during the trial?",
        None,
        None,
    ),
    (
        "sq:deviations:context-deviations",
        "domain:deviations",
        "If Y/PY/NI to 2.1 or 2.2: Were there deviations from the intended intervention that arose because of the trial context?",
        "2.1 or 2.2 is Y/PY/NI",
        None,
    ),
    (
        "sq:deviations:affected-outcome",
        "domain:deviations",
        "If Y/PY to 2.3: Were these deviations likely to have affected the outcome?",
        "2.3 is Y/PY",
        None,
    ),
    (
        "sq:deviations:balanced",
        "domain:deviations",
        "If Y/PY/NI to 2.4: Were these deviations from intended intervention balanced between groups?",
        "2.4 is Y/PY/NI",
        None,
    ),
    (
        "sq:deviations:appropriate-analysis",
        "domain:deviations",
        "Was an appropriate analysis used to estimate the effect of assignment to intervention?",
        None,
        None,
    ),
    (
        "sq:deviations:substantial-impact",
        "domain:deviations",
        "If N/PN/NI to 2.6: Was there potential for a substantial impact (on the result) of the failure to analyse participants in the group to which they were randomized?",
        "2.6 is N/PN/NI",
        None,
    ),
    (
        "sq:missing:data-available",
        "domain:missing",
        "Were data for this outcome available for all, or nearly all, participants randomized?",
        None,
        None,
    ),
    (
        "sq:missing:evidence-unbiased",
        "domain:missing",
        "If N/PN/NI to 3.1: Is there evidence that the result was not biased by missing outcome data?",
        "3.1 is N/PN/NI",
        (Answer.YES, Answer.PROBABLY_YES, Answer.PROBABLY_NO, Answer.NO),
    ),
    (
        "sq:missing:true-value-dependent",
        "domain:missing",
        "If N/PN to 3.2: Could missingness in the outcome depend on its true value?",
        "3.2 is N/PN",
        None,
    ),
    (
        "sq:missing:likely-dependent",
        "domain:missing",
        "If Y/PY/NI to 3.3: Is it likely that missingness in the outcome depended on its true value?",
        "3.3 is Y/PY/NI",
        None,
    ),
    (
        "sq:measurement:method-inappropriate",
        "domain:measurement",
        "Was the method of measuring the outcome inappropriate?",
        None,
        None,
    ),
    (
        "sq:measurement:differential",
        "domain:measurement",
        "Could measurement or ascertainment of the outcome have differed between intervention groups?",
        None,
        None,
    ),
    (
        "sq:measurement:assessor-aware",
        "domain:measurement",
        "If N/PN/NI to 4.1 and 4.2: Were outcome assessors aware of the intervention received by study participants?",
        "4.1 and 4.2 are N/PN/NI",
        None,
    ),
    (
        "sq:measurement:influence-possible",
        "domain:measurement",
        "If Y/PY/NI to 4.3: Could assessment of the outcome have been influenced by knowledge of intervention received?",
        "4.3 is Y/PY/NI",
        None,
    ),
    (
        "sq:measurement:influence-likely",
        "domain:measurement",
        "If Y/PY/NI to 4.4: Is it likely that assessment of the outcome was influenced by knowledge of intervention received?",
        "4.4 is Y/PY/NI",
        None,
    ),
    (
        "sq:selection:prespecified-analysis",
        "domain:selection",
        "Were the data that produced this result analysed in accordance with a pre-specified analysis plan that was finalized before unblinded outcome data were available for analysis?",
        None,
        None,
    ),
    (
        "sq:selection:multiple-measurements",
        "domain:selection",
        "Is the numerical result being assessed likely to have been selected, on the basis of the results, from multiple eligible outcome measurements (e.g. scales, definitions, time points) within the outcome domain?",
        None,
        None,
    ),
    (
        "sq:selection:multiple-analyses",
        "domain:selection",
        "Is the numerical result being assessed likely to have been selected, on the basis of the results, from multiple eligible analyses of the data?",
        None,
        None,
    ),
)
_QUESTIONS = tuple(
    Question(id=i, domain_id=d, wording=w, active_when=a, allowed_answers=answers or tuple(Answer))
    for i, d, w, a, answers in _Q
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
}
SCIENTIFIC_PACK = ScientificPack(**_CONTENT, content_hash=sha256(_CONTENT))


def load_scientific_pack(data: dict[str, object]) -> ScientificPack:
    """Validate a serialized pack and reject a mismatched declared identity hash."""
    pack = ScientificPack.model_validate(data)
    content = pack.model_dump(mode="python", exclude={"content_hash"}, exclude_none=True)
    if pack.content_hash != sha256(content):
        raise ValueError("scientific pack content hash does not match its content")
    return pack
