# ruff: noqa: E501
"""Independently transcribed RoB 2 parallel-assignment question pack."""

from typing import Literal

from rob2_kit.models import (
    ActivationPredicate,
    AlwaysActive,
    Answer,
    ConditionalActivation,
    Domain,
    OfficialQuestionGuidance,
    OperationalQuestionGuidance,
    Provenance,
    QuerySuggestion,
    Question,
    QuestionGuidance,
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
_OPERATIONAL_GUIDANCE_ID = "rob2-kit.parallel-assignment.question-guidance"
_OPERATIONAL_GUIDANCE_VERSION = "1.0.2"
_OPERATIONAL_ATTRIBUTION = "rob2-kit maintainers"

_OFFICIAL_ELABORATIONS = {
    "Full guidance p. 17, Box 4, signalling question 1.1": "Answer ‘Yes’ if a random component was used in the sequence generation process. Examples include computer-generated random numbers; reference to a random number table; coin tossing; shuffling cards or envelopes; throwing dice; or drawing lots. Answer ‘No’ if no random element was used in generating the allocation sequence or the sequence is predictable. Answer ‘No information’ if the only information about randomization methods is a statement that the study is randomized.",
    "Full guidance p. 17, Box 4, signalling question 1.2": "Answer ‘Yes’ if the trial used any form of remote or centrally administered method to allocate interventions to participants, where the process of allocation is controlled by an external unit or organization, independent of the enrolment personnel. Answer ‘Yes’ if envelopes or drug containers were used appropriately. Answer ‘No’ if there is reason to suspect that the enrolling investigator or the participant had knowledge of the forthcoming allocation.",
    "Full guidance pp. 17-18, Box 4, signalling question 1.3": "Note that differences that are compatible with chance do not lead to a risk of bias. Answer ‘No’ if no imbalances are apparent or if any observed imbalances are compatible with chance. Answer ‘Yes’ if there are imbalances that indicate problems with the randomization process, including substantial differences between intervention group sizes, a substantial excess in statistically significant differences beyond that expected by chance, or imbalance in one or more key prognostic factors very unlikely to be due to chance. Answer ‘No information’ when there is no useful baseline information available.",
    "Full guidance p. 28, Box 6, signalling question 2.1": "If participants are aware of their assigned intervention it is more likely that health-related behaviours will differ between the intervention groups. Blinding participants, most commonly through use of a placebo or sham intervention, may prevent such differences. If participants experienced side effects or toxicities that they knew to be specific to one of the interventions, answer this question ‘Yes’ or ‘Probably yes’.",
    "Full guidance p. 28, Box 6, signalling question 2.2": "If carers or people delivering the interventions are aware of the assigned intervention then its implementation, or administration of non-protocol interventions, may differ between the intervention groups. Blinding may prevent such differences. If randomized allocation was not concealed, then it is likely that carers and people delivering the interventions were aware of participants’ assigned intervention during the trial.",
    "Full guidance p. 28, Box 6, signalling question 2.3": "Answer ‘Yes’ or ‘Probably yes’ only if there is evidence, or strong reason to believe, that the trial context led to failure to implement the protocol interventions or to implementation of interventions not allowed by the protocol. Answer ‘No’ or ‘Probably no’ if there were changes from assigned intervention that are inconsistent with the trial protocol, such as non-adherence to intervention, but these are consistent with what could occur outside the trial context. The answer ‘No information’ may be appropriate.",
    "Full guidance p. 28, Box 6, signalling question 2.4": "Changes from assigned intervention that are inconsistent with the trial protocol and arose because of the trial context will impact on the intervention effect estimate if they affect the outcome, but not otherwise.",
    "Full guidance p. 29, Box 6, signalling question 2.5": "Changes from assigned intervention that are inconsistent with the trial protocol and arose because of the trial context are more likely to impact on intervention effect estimate if they are not balanced between the intervention groups.",
    "Full guidance p. 29, Box 6, signalling question 2.6": "Both intention-to-treat (ITT) analyses and modified intention-to-treat (mITT) analyses excluding participants with missing outcome data should be considered appropriate. Both naïve ‘per-protocol’ analyses and ‘as treated’ analyses should be considered inappropriate. Analyses excluding eligible trial participants post-randomization should also be considered inappropriate.",
    "Full guidance p. 29, Box 6, signalling question 2.7": "This question addresses whether the number of participants who were analysed in the wrong intervention group, or excluded from the analysis, was sufficient that there could have been a substantial impact on the result. It is not possible to specify a precise rule: there may be potential for substantial impact even if fewer than 5% of participants were analysed in the wrong group or excluded, if the outcome is rare or if exclusions are strongly related to prognostic factors.",
    "Full guidance p. 45, Box 8, signalling question 3.1": "‘Nearly all’ should be interpreted as that the number of participants with missing outcome data is sufficiently small that their outcomes, whatever they were, could have made no important difference to the estimated effect of intervention. For continuous outcomes, availability of data from 95% of the participants will often be sufficient. Note that imputed data should be regarded as missing data.",
    "Full guidance p. 45, Box 8, signalling question 3.2": "Evidence that the result was not biased by missing outcome data may come from analysis methods that correct for bias, or sensitivity analyses showing that results are little changed under a range of plausible assumptions about the relationship between missingness in the outcome and its true value. However, imputing the outcome variable, either through methods such as ‘last-observation-carried-forward’ or via multiple imputation based only on intervention group, should not be assumed to correct for bias due to missing outcome data.",
    "Full guidance p. 45, Box 8, signalling question 3.3": "If loss to follow up, or withdrawal from the study, could be related to participants’ health status, then it is possible that missingness in the outcome was influenced by its true value. However, if all missing outcome data occurred for documented reasons that are unrelated to the outcome then the risk of bias due to missing outcome data will be low.",
    "Full guidance pp. 45-46, Box 8, signalling question 3.4": "This question distinguishes between situations in which (i) missingness could depend on its true value and (ii) it is likely that missingness depended on its true value. Five reasons for answering ‘Yes’ are differences between intervention groups in the proportions of missing outcome data; reported reasons that provide evidence that missingness depends on its true value; reasons that differ between intervention groups; trial circumstances; and censoring when participants stop or change their assigned intervention.",
    "Full guidance p. 54, Box 10, signalling question 4.1": "Answer ‘Yes’ or ‘Probably yes’ if the method of measuring the outcome is inappropriate, for example because it is unlikely to be sensitive to plausible intervention effects or the measurement instrument has been demonstrated to have poor validity.",
    "Full guidance p. 54, Box 10, signalling question 4.2": "Comparable methods of outcome measurement involve the same measurement methods and thresholds, used at comparable time points. Differences between intervention groups may arise because of ‘diagnostic detection bias’ in the context of passive collection of outcome data, or if an intervention involves additional visits to a healthcare provider.",
    "Full guidance p. 54, Box 10, signalling question 4.3": "Answer ‘No’ if outcome assessors were blinded to intervention status. For participant-reported outcomes, the outcome assessor is the study participant.",
    "Full guidance p. 54, Box 10, signalling question 4.4": "Knowledge of the assigned intervention could influence participant-reported outcomes, observer-reported outcomes involving some judgement, and intervention provider decision outcomes. They are unlikely to influence observer-reported outcomes that do not involve judgement, for example all-cause mortality.",
    "Full guidance p. 54, Box 10, signalling question 4.5": "This question distinguishes between situations in which knowledge of intervention status could have influenced outcome assessment but there is no reason to believe that it did from those in which knowledge of intervention status was likely to influence outcome assessment. When there are strong levels of belief in either beneficial or harmful effects of the intervention, it is more likely that the outcome was influenced.",
    "Full guidance p. 63, Box 11, signalling question 5.1": "To avoid the possibility of selection of the reported result, finalization of the analysis intentions must precede availability of unblinded outcome data to the trial investigators. Changes to analysis plans that were made before unblinded outcome data were available, or that were clearly unrelated to the results, do not raise concerns about bias in selection of the reported result.",
    "Full guidance pp. 63-64, Box 11, signalling question 5.2": "Answer ‘Yes’ or ‘Probably yes’ if there is clear evidence that a domain was measured in multiple eligible ways, but data for only one or a subset of measures is fully reported without justification, and the fully reported result is likely to have been selected on the basis of the results. Answer ‘No information’ if analysis intentions are not available or are not reported in sufficient detail and there is more than one way in which the outcome domain could have been measured.",
    "Full guidance pp. 64-65, Box 11, signalling question 5.3": "Answer ‘Yes’ or ‘Probably yes’ if there is clear evidence that a measurement was analysed in multiple eligible ways, but data for only one or a subset of analyses is fully reported without justification, and the fully reported result is likely to have been selected on the basis of the results. Answer ‘No information’ if analysis intentions are not available or are not reported in sufficient detail and there is more than one way in which the outcome measurement could have been analysed.",
}


def _anchor(answer: Answer, text: str) -> tuple[Answer, str]:
    return answer, text


def _guidance(
    locator: str,
    bias_construct: str,
    decision_rule: str,
    evidence_needed: tuple[str, ...],
    no_information_rule: str,
    anchors: tuple[tuple[Answer, str], ...],
    considerations: tuple[str, ...],
    invalid_shortcuts: tuple[str, ...],
) -> QuestionGuidance:
    return QuestionGuidance(
        official=OfficialQuestionGuidance(
            version=_GUIDANCE_VERSION,
            source_locator=locator,
            source_sha256=_GUIDANCE_SOURCE_SHA256,
            source_excerpt=_OFFICIAL_ELABORATIONS[locator],
        ),
        operational=OperationalQuestionGuidance(
            id=_OPERATIONAL_GUIDANCE_ID,
            version=_OPERATIONAL_GUIDANCE_VERSION,
            attribution=_OPERATIONAL_ATTRIBUTION,
            bias_construct=bias_construct,
            decision_rule=decision_rule,
            evidence_needed=evidence_needed,
            no_information_rule=no_information_rule,
            answer_anchors=tuple({"answer": answer, "text": text} for answer, text in anchors),
            considerations=considerations,
            invalid_shortcuts=invalid_shortcuts,
        ),
    )


_GUIDANCE: dict[str, QuestionGuidance] = {
    "sq:randomization:sequence": _guidance(
        "Full guidance p. 17, Box 4, signalling question 1.1",
        "Whether a random component was used to generate the allocation sequence.",
        "Answer yes when a random component was used; answer no when no random element was used or the sequence is predictable. A statement that the study is randomized alone supports no_information.",
        (
            "The sequence-generation method, such as computer random numbers, a random number table, coin tossing, or minimization with a random element.",
        ),
        "Answer no_information when the only information about randomization methods is that the study is randomized. Do not turn missing reporting into proof that the sequence was non-random.",
        (
            _anchor(Answer.YES, "A random component was used in sequence generation."),
            _anchor(Answer.NO, "No random element was used, or the sequence was predictable."),
            _anchor(Answer.NO_INFORMATION, "The report only states that the study is randomized."),
        ),
        (
            "Minimization should generally be considered random when it includes a random element.",
            "The baseline-imbalance answer must not change this answer.",
            "For retrieval, search terms from the official guidance such as 'computer-generated random numbers', 'random number table', 'coin tossing', and 'minimization', plus the generic concept 'sequence generation'. A truncated broad any-term search is discovery, not evidence that the method is absent.",
        ),
        (
            "underwent randomization",
            "was called randomized",
            "had balanced groups",
            "was centrally registered",
        ),
    ),
    "sq:randomization:concealment": _guidance(
        "Full guidance p. 17, Box 4, signalling question 1.2",
        "Whether the allocation sequence was concealed until participants were enrolled and assigned.",
        "Answer yes for remote or centrally administered allocation independent of enrolment personnel, or appropriately used opaque sequentially numbered sealed envelopes or identical sequentially numbered drug containers. Answer no when the enrolling investigator or participant could know the forthcoming allocation.",
        (
            "The method used before assignment and who controlled it; for envelopes or containers, capture the details that make them tamper-resistant and irreversible before assignment.",
        ),
        "Answer no_information when the report does not provide enough information to assess concealment; do not infer concealment from central registration or a sequence number alone.",
        (
            _anchor(
                Answer.YES,
                "Remote or central allocation was controlled by an independent external unit, or appropriate envelopes/containers were used.",
            ),
            _anchor(
                Answer.NO,
                "The enrolling investigator or participant had knowledge of the forthcoming allocation.",
            ),
        ),
        (
            "Allocation concealment concerns the process before assignment, not blinding after assignment.",
            "The reported sequence-generation method does not establish concealment.",
            "For retrieval, search compact concealment concepts such as 'central randomization', 'interactive voice response', 'web response', and 'opaque sealed envelopes'. A truncated broad any-term search is discovery, not evidence that concealment details are absent.",
        ),
        (
            "stratification",
            "central registration",
            "a numbered sequence",
            "sealed envelopes without their safeguards",
        ),
    ),
    "sq:randomization:baseline-imbalance": _guidance(
        "Full guidance pp. 17-18, Box 4, signalling question 1.3",
        "Whether baseline differences between intervention groups suggest a problem with randomization.",
        "Answer no when no imbalance is apparent or observed differences are compatible with chance. Answer yes for substantial group-size differences, an excess of statistically significant baseline differences beyond chance, a key prognostic imbalance very unlikely due to chance and large enough to bias the estimate, or excessive similarity incompatible with chance.",
        (
            "Baseline characteristics for the randomized groups, intended allocation ratio, prognostic factors, and outcome baseline measures.",
        ),
        "Answer no_information when no useful baseline information is available, for example in an abstract or when only final-analysis participants are described.",
        (
            _anchor(
                Answer.YES, "Baseline imbalance indicates a problem with the randomization process."
            ),
            _anchor(
                Answer.NO,
                "No imbalance is apparent or observed differences are compatible with chance.",
            ),
            _anchor(Answer.NO_INFORMATION, "No useful baseline information is available."),
        ),
        (
            "A few statistically significant differences at the conventional 0.05 threshold are usually compatible with chance.",
            "This answer must not alter answers about sequence generation or concealment.",
        ),
        (
            "a baseline table header",
            "balanced groups",
            "statistical significance of one isolated comparison",
            "an ITT analysis",
        ),
    ),
    "sq:deviations:participants-aware": _guidance(
        "Full guidance p. 28, Box 6, signalling question 2.1",
        "Whether participants were aware of their assigned intervention during the trial.",
        "Answer yes or probably yes when participants knew their assignment, including when intervention-specific side effects or toxicities revealed it. Blinding participants, commonly with placebo or sham intervention, may prevent such differences.",
        (
            "A direct report of participant blinding, open-label conduct, or participant knowledge during the trial.",
        ),
        "Use no_information only after considering direct facts, indirect evidence, and trial circumstances; "
        "an absent explicit awareness statement alone is insufficient when those facts support a probable judgment.",
        (
            _anchor(Answer.YES, "Participants were aware of their assigned intervention."),
            _anchor(Answer.NO, "Participants were blinded to their assigned intervention."),
        ),
        (
            "Awareness is about knowledge of assignment, not whether participants completed or received treatment.",
        ),
        ("completed treatment", "received the intervention", "was randomized"),
    ),
    "sq:deviations:personnel-aware": _guidance(
        "Full guidance p. 28, Box 6, signalling question 2.2",
        "Whether carers and people delivering interventions were aware of participants' assigned intervention.",
        "Answer yes or probably yes when carers or intervention personnel knew assignment, including when participant side effects or toxicities revealed it. If randomized allocation was not concealed, awareness by carers and delivery personnel is likely.",
        (
            "A direct report of blinding or awareness by carers and people delivering the intervention, plus the allocation process when it bears on their awareness.",
        ),
        "Use no_information when awareness of carers or delivery personnel cannot be determined.",
        (
            _anchor(
                Answer.YES, "Carers or intervention personnel were aware of assigned intervention."
            ),
            _anchor(
                Answer.NO, "Carers or intervention personnel were blinded to assigned intervention."
            ),
        ),
        ("Assess the people delivering interventions, not merely outcome assessors.",),
        ("completed treatment", "received the intervention", "was randomized"),
    ),
    "sq:deviations:context-deviations": _guidance(
        "Full guidance p. 28, Box 6, signalling question 2.3",
        "Whether deviations inconsistent with protocol arose because of the trial context.",
        "Answer yes or probably yes with evidence or strong reason that the trial context caused failure to implement protocol interventions or implementation of prohibited interventions. Answer no or probably no when no such deviation occurred, including ordinary non-adherence outside the trial context or protocol-consistent changes.",
        (
            "Evidence linking the deviation to recruitment, engagement, or trial personnel and showing it was inconsistent with the protocol.",
        ),
        "Use no_information when reported details are insufficient and trial circumstances do not support a reasonable probable judgment about trial-context-caused deviations.",
        (
            _anchor(Answer.YES, "The trial context caused protocol-inconsistent deviations."),
            _anchor(
                Answer.NO, "No protocol-inconsistent deviation arose because of the trial context."
            ),
            _anchor(
                Answer.NO_INFORMATION,
                "Reported details and trial circumstances do not support a judgment about trial-context-caused deviations.",
            ),
        ),
        (
            "Side-effect-related compromised blinding counts only when resulting changes were protocol-inconsistent and context-caused.",
        ),
        (
            "nonadherence alone",
            "an ITT analysis",
            "participants switched treatment",
            "a protocol deviation without its cause",
        ),
    ),
    "sq:deviations:affected-outcome": _guidance(
        "Full guidance p. 28, Box 6, signalling question 2.4",
        "Whether context-caused protocol-inconsistent deviations were likely to affect the outcome.",
        "Answer yes or probably yes when the identified deviations could affect the intervention effect estimate through this outcome; answer no or probably no when they would not affect the outcome.",
        (
            "A direct link between the identified context-caused deviation and this outcome or its effect estimate.",
        ),
        "Use no_information when the effect of the identified deviations on the outcome cannot be determined.",
        (
            _anchor(Answer.YES, "The identified deviations were likely to affect the outcome."),
            _anchor(Answer.NO, "The identified deviations were not likely to affect the outcome."),
        ),
        (
            "This question concerns the deviations already identified in 2.3, not any non-adherence in isolation.",
        ),
        ("nonadherence alone", "an ITT analysis", "a deviation without outcome impact"),
    ),
    "sq:deviations:balanced": _guidance(
        "Full guidance p. 29, Box 6, signalling question 2.5",
        "Whether context-caused protocol-inconsistent deviations were balanced between intervention groups.",
        "Answer yes or probably yes when the identified deviations were balanced between groups; answer no or probably no when they were not balanced.",
        (
            "Group-specific counts or descriptions of the identified deviations and their comparability between intervention groups.",
        ),
        "Use no_information when balance of the identified deviations cannot be determined.",
        (
            _anchor(
                Answer.YES, "The identified deviations were balanced between intervention groups."
            ),
            _anchor(
                Answer.NO,
                "The identified deviations were not balanced between intervention groups.",
            ),
        ),
        (
            "Balance refers to the deviations identified in 2.3 and their potential effect, not to baseline group sizes.",
        ),
        ("equal randomized group sizes", "an ITT analysis", "absence of a reported problem"),
    ),
    "sq:deviations:appropriate-analysis": _guidance(
        "Full guidance p. 29, Box 6, signalling question 2.6",
        "Whether an appropriate analysis estimated the effect of assignment to intervention. Compare randomized assignment with the population and groups actually analysed, including exclusions, reassignment, and reasons; an ITT label alone does not establish this.",
        "Consider ITT and modified ITT excluding participants with missing outcome data appropriate. Consider naive per-protocol, as-treated, and post-randomization exclusion of eligible participants inappropriate; post-randomization exclusion of ineligible participants may be appropriate when eligibility could not have been influenced by assignment.",
        (
            "The analysis population and grouping rule, including whether participants remained grouped by assignment and which post-randomization exclusions occurred.",
        ),
        "Use no_information only after considering direct facts, indirect evidence, and trial circumstances; "
        "an incomplete analysis description alone is insufficient when those facts support a probable judgment "
        "about appropriateness.",
        (
            _anchor(
                Answer.YES,
                "An ITT or appropriate modified ITT analysis estimated assignment effect.",
            ),
            _anchor(
                Answer.NO,
                "A naive per-protocol, as-treated, or inappropriate post-randomization exclusion analysis was used.",
            ),
        ),
        (
            "The question is about effect of assignment, so grouping must follow randomized assignment.",
        ),
        (
            "an endpoint definition",
            "an ITT label without its population",
            "a per-protocol label without the analysis population",
        ),
    ),
    "sq:deviations:substantial-impact": _guidance(
        "Full guidance p. 29, Box 6, signalling question 2.7",
        "Whether failure to analyse participants in their randomized group could substantially affect the result.",
        "Assess whether the number analysed in the wrong group or excluded was sufficient for substantial impact. There is no precise percentage rule: fewer than 5% may still matter for rare outcomes or exclusions strongly related to prognostic factors.",
        (
            "Counts and reasons for participants analysed in the wrong group or excluded, outcome rarity, and prognostic relevance of exclusions.",
        ),
        "Use no_information when the potential magnitude of impact cannot be assessed.",
        (
            _anchor(
                Answer.YES,
                "The wrong-group analysis or exclusions could substantially affect the result.",
            ),
            _anchor(
                Answer.NO,
                "The wrong-group analysis or exclusions could not substantially affect the result.",
            ),
        ),
        ("This is conditional on an inappropriate or uncertain analysis in 2.6.",),
        ("a small percentage alone", "an ITT analysis", "a group label without exclusion counts"),
    ),
    "sq:missing:data-available": _guidance(
        "Full guidance p. 45, Box 8, signalling question 3.1",
        "Whether outcome data were available for all or nearly all randomized participants.",
        "Use the randomized population. For yes or probably yes, require actual outcome-availability evidence. Nearly all means missing outcomes were sufficiently few that, whatever they were, they could make no important difference; 95% often suffices for continuous outcomes, while dichotomous outcomes depend on event risk. Imputed data count as missing.",
        (
            "For yes or probably yes, actual outcome-availability evidence can be comparable observed-outcome counts, arm-specific loss-to-follow-up or censoring accounting, or an explicit complete/nearly-complete ascertainment statement.",
            "Compare the approved outcome/time point across participant-flow and outcome-data passages. For each comparable arm or unit distinguish randomized, observed, analysed, and imputed counts, plus exclusions and reasons. A missing count or an explicit complete-ascertainment statement is valid source information; do not substitute an analysis denominator for observed data. Calculate randomized minus observed only when population, arm, unit, and time point are the same. Imputed data count as missing.",
        ),
        "Only answer no_information when the report provides no information about the extent of missing outcome data.",
        (
            _anchor(
                Answer.YES,
                "Outcome data were available for all or nearly all randomized participants.",
            ),
            _anchor(
                Answer.NO,
                "Outcome data were not available for all or nearly all randomized participants.",
            ),
            _anchor(
                Answer.NO_INFORMATION,
                "The report provides no information about the extent of missing outcome data.",
            ),
        ),
        (
            "The appropriate population is all randomized participants, not only participants included in a final analysis. Keep outcome availability distinct from exclusions for analysis or conduct; the same passage may inform both Domains for different scientific reasons.",
            "Distinguish administrative censoring at a common data cutoff from censoring caused by missing follow-up; inspect actual rates and follow-up accounting rather than treating a generic censoring rule as outcome-availability evidence.",
        ),
        (
            "a complete-case analysis label",
            "an ITT analysis",
            "analysis denominators or ITT membership alone",
            "planned or scheduled follow-up alone",
            "treatment continuation or discontinuation alone",
            "a generic censoring rule without actual rates or follow-up accounting",
            "imputed data counted as observed outcomes",
        ),
    ),
    "sq:missing:evidence-unbiased": _guidance(
        "Full guidance p. 45, Box 8, signalling question 3.2",
        "Whether there is evidence that the result was not biased by missing outcome data.",
        "Evidence may come from methods correcting for bias or sensitivity analyses showing little change under plausible assumptions about missingness and true outcome. Last-observation-carried-forward or multiple imputation based only on intervention group should not be assumed to correct bias.",
        (
            "A bias-correcting analysis or sensitivity analysis with plausible missingness assumptions and its result.",
        ),
        "No_information is not an allowed response to this question in the parallel-assignment pack; provide direct evidence or answer no/probably no.",
        (
            _anchor(
                Answer.YES,
                "A bias-correcting or informative sensitivity analysis indicates the result was not biased.",
            ),
            _anchor(
                Answer.NO,
                "The available evidence does not show that the result was free from missing-data bias.",
            ),
        ),
        ("Imputation alone is not evidence that missing outcome data did not bias the result.",),
        (
            "an ITT analysis",
            "last observation carried forward",
            "multiple imputation based only on intervention group",
        ),
    ),
    "sq:missing:true-value-dependent": _guidance(
        "Full guidance p. 45, Box 8, signalling question 3.3",
        "Whether missingness in the outcome could depend on its true value.",
        "Answer yes or probably yes when loss to follow-up or withdrawal could relate to health status or outcome. Answer no or probably no when all missingness had documented reasons unrelated to outcome, such as a failed measuring device or interruption to routine data collection.",
        (
            "Reasons for missingness and their relationship to participants' health status or true outcome, including censoring and treatment switching in time-to-event analyses.",
        ),
        "Use no_information when the reasons for missingness do not permit assessment of dependence on the true value.",
        (
            _anchor(Answer.YES, "Missingness could depend on the true outcome value."),
            _anchor(Answer.NO, "Documented missingness reasons are unrelated to the outcome."),
        ),
        (
            "For time-to-event outcomes, inspect censoring reasons and timing to identify missing follow-up. A common administrative cutoff does not by itself establish outcome-dependent missingness.",
        ),
        (
            "complete follow-up claims",
            "an ITT analysis",
            "a reason for withdrawal without its relation to outcome",
        ),
    ),
    "sq:missing:likely-dependent": _guidance(
        "Full guidance pp. 45-46, Box 8, signalling question 3.4",
        "Whether missingness that could depend on true value likely depended on it.",
        "Consider differences in missingness or censoring rates, reasons that depend on true value, reasons differing between groups, trial circumstances, and censoring after stopping or changing intervention. Answer no when analysis accounted for participant characteristics likely to explain the relationship.",
        (
            "Group-specific missingness or censoring, reasons for missingness, trial circumstances, and any analysis accounting for relevant participant characteristics.",
        ),
        "Use no_information when likelihood of dependence on true value cannot be judged from the available evidence.",
        (
            _anchor(Answer.YES, "Missingness likely depended on the true outcome value."),
            _anchor(
                Answer.NO,
                "The analysis accounted for characteristics explaining the relationship, or dependence was not likely.",
            ),
        ),
        (
            "Possible dependence in 3.3 does not establish likely dependence in 3.4. Judge likelihood from missingness reasons and trial circumstances; absent contrary evidence alone does not establish likelihood.",
        ),
        ("different group sizes alone", "an ITT analysis", "a generic loss-to-follow-up statement"),
    ),
    "sq:measurement:method-inappropriate": _guidance(
        "Full guidance p. 54, Box 10, signalling question 4.1",
        "Whether the method of measuring the outcome was inappropriate for the outcome.",
        "Answer yes or probably yes when the method is unlikely to be sensitive to plausible intervention effects or the instrument has demonstrated poor validity. Do not assess whether choosing the outcome itself was sensible.",
        (
            "The measurement method's sensitivity to plausible effects and evidence of instrument validity for this outcome.",
        ),
        "Use no_information when appropriateness of the measurement method cannot be determined.",
        (
            _anchor(
                Answer.YES,
                "The measurement method is unsuitable, insensitive, or poorly valid for this outcome.",
            ),
            _anchor(Answer.NO, "The measurement method is appropriate for this outcome."),
        ),
        ("For pre-specified outcomes the answer will usually be no or probably no.",),
        (
            "a surrogate or proxy label",
            "an endpoint definition",
            "a statistically significant result",
        ),
    ),
    "sq:measurement:differential": _guidance(
        "Full guidance p. 54, Box 10, signalling question 4.2",
        "Whether measurement or ascertainment of the outcome could have differed between intervention groups.",
        "Comparable measurement uses the same methods and thresholds at comparable time points. Consider diagnostic detection bias from passive collection and additional healthcare visits caused by an intervention.",
        (
            "Methods, thresholds, timing, and opportunities for outcome ascertainment in each intervention group.",
        ),
        "Use no_information when comparability of measurement or ascertainment cannot be assessed.",
        (
            _anchor(
                Answer.YES, "Measurement or ascertainment could differ between intervention groups."
            ),
            _anchor(
                Answer.NO,
                "The same comparable measurement or ascertainment was used between groups.",
            ),
        ),
        (
            "Compare actual methods and detection opportunities. Assessor awareness or possible reporting influence alone does not establish a between-group method difference; assess awareness and influence in 4.3 to 4.5.",
        ),
        ("a common endpoint label", "an equal number randomized", "an ITT analysis"),
    ),
    "sq:measurement:assessor-aware": _guidance(
        "Full guidance p. 54, Box 10, signalling question 4.3",
        "Whether outcome assessors were aware of the intervention received, when 4.1 and 4.2 are not yes/probably yes. Identify who determines the approved outcome at the relevant time point and distinguish that assessor from someone who merely records it.",
        "Answer no when outcome assessors were blinded to intervention status. For participant-reported outcomes, the participant is the outcome assessor. This question is applicable only after the stated activation conditions.",
        ("Who assessed the outcome and whether that assessor was blinded to intervention status.",),
        "Use no_information when assessor awareness cannot be determined; do not infer blinding from an objective endpoint or from blinding elsewhere in the trial.",
        (
            _anchor(Answer.NO, "Outcome assessors were blinded to intervention status."),
            _anchor(Answer.YES, "Outcome assessors knew the intervention received."),
        ),
        ("The assessor can be a participant, intervention provider, or independent observer.",),
        (
            "an objective endpoint",
            "a blinded statistician",
            "participant completion of treatment",
            "blinding of participants only",
        ),
    ),
    "sq:measurement:influence-possible": _guidance(
        "Full guidance p. 54, Box 10, signalling question 4.4",
        "Whether assessment could have been influenced by knowledge of intervention received. Keep assessor awareness separate from the mechanism by which awareness could change a judgement.",
        "Knowledge could influence participant-reported outcomes, observer-reported outcomes involving judgement, and intervention-provider decisions; it is unlikely to influence observer-reported outcomes without judgement, such as all-cause mortality.",
        (
            "Outcome type, assessor role, degree of judgement, and whether knowledge of assignment could change assessment.",
        ),
        "Use no_information when possible influence cannot be determined; this question is conditional on awareness in 4.3.",
        (
            _anchor(Answer.YES, "Knowledge of intervention could influence assessment."),
            _anchor(
                Answer.NO,
                "The outcome assessment could not be influenced by knowledge of intervention.",
            ),
        ),
        ("Applicability is determined by the preceding assessor-awareness answer.",),
        (
            "an objective endpoint label",
            "assessor awareness without outcome type",
            "blinding of participants only",
        ),
    ),
    "sq:measurement:influence-likely": _guidance(
        "Full guidance p. 54, Box 10, signalling question 4.5",
        "Whether knowledge of intervention likely influenced outcome assessment. Require evidence or strong beliefs plus a judgement opportunity; awareness alone does not establish influence.",
        "Distinguish possible influence without reason to believe it occurred from likely influence. Strong beliefs about benefits or harms make influence more likely, for example patient-reported symptoms in homeopathy or recovery assessed by an intervention physiotherapist.",
        (
            "Evidence of actual influence or strong beliefs and judgement opportunities that make influence likely, given the assessor and outcome.",
        ),
        "Use no_information when likelihood of influence cannot be judged; this question is conditional on possible influence in 4.4.",
        (
            _anchor(Answer.YES, "Knowledge of intervention likely influenced assessment."),
            _anchor(
                Answer.NO,
                "Knowledge could have influenced assessment but it was not likely to do so.",
            ),
        ),
        (
            "Possible influence without evidence it occurred maps differently from likely influence.",
        ),
        ("assessor awareness alone", "an objective endpoint label", "an ITT analysis"),
    ),
    "sq:selection:prespecified-analysis": _guidance(
        "Full guidance p. 63, Box 11, signalling question 5.1",
        "Whether data producing this result followed a pre-specified plan finalized before unblinded outcome data were available.",
        "Compare the approved result with intended measurements, timing, population, and analyses. Distinguish source creation/version and amendment dates from trial events and retrieval time; only compare chronology when the relevant events and precision are established. Changes made before unblinded data were available, or clearly unrelated to results such as a broken machine, do not raise concerns.",
        (
            "A sufficiently detailed protocol or SAP, its finalization date relative to unblinded outcome data, and the reported analysis.",
        ),
        "Use no_information only after considering direct facts, indirect evidence, and trial circumstances; "
        "an unavailable or incomplete intention statement alone is insufficient when those facts support a "
        "probable judgment about timing and correspondence. Use no_information when genuine timing evidence "
        "cannot support a defensible yes or no judgment.",
        (
            _anchor(
                Answer.YES,
                "The result follows a sufficiently detailed plan finalized before unblinded outcome data were available.",
            ),
            _anchor(Answer.NO, "The result did not follow such a pre-specified plan."),
            _anchor(
                Answer.NO_INFORMATION,
                "Analysis intentions or their timing are not sufficiently reported.",
            ),
        ),
        (
            "Assess the plan against the exact result, not merely whether a protocol or registry exists.",
        ),
        (
            "an objective definition",
            "a registry link",
            "an endpoint label",
            "a protocol mention without date or detail",
        ),
    ),
    "sq:selection:multiple-measurements": _guidance(
        "Full guidance pp. 63-64, Box 11, signalling question 5.2",
        "Whether the result was selected from multiple eligible outcome measurements within the outcome domain on the basis of results.",
        "Answer yes or probably yes when clear evidence shows multiple eligible measures but only one or a subset is fully reported without justification and selection likely depended on results. Answer no or probably no when all eligible intended measures are reported, only one possible measurement exists, or an unrelated inconsistency is explained.",
        (
            "The protocol or SAP's eligible scales, definitions, time points, assessors, or subscales and which were reported, with any justification.",
        ),
        "Answer no_information when intentions are unavailable or insufficiently detailed and more than one eligible measurement was possible.",
        (
            _anchor(
                Answer.YES,
                "Multiple eligible measurements existed and the reported subset was likely selected on the results.",
            ),
            _anchor(
                Answer.NO,
                "All eligible measurements correspond to intentions, or only one eligible measurement was possible.",
            ),
            _anchor(
                Answer.NO_INFORMATION,
                "Measurement intentions are insufficiently reported despite multiple possible measurements.",
            ),
        ),
        ("Restrict the assessment to measurements eligible for the reviewer's synthesis.",),
        (
            "an endpoint definition",
            "a single reported time point",
            "a single scale without the eligible set",
            "a single ITT analysis",
        ),
    ),
    "sq:selection:multiple-analyses": _guidance(
        "Full guidance pp. 64-65, Box 11, signalling question 5.3",
        "Whether the result was selected from multiple eligible analyses of the data on the basis of results.",
        "Answer yes or probably yes when clear evidence shows multiple eligible analyses but only one or a subset is fully reported without justification and selection likely depended on results. Answer no or probably no when all eligible intended analyses are reported, only one possible analysis exists, or an unrelated inconsistency is explained.",
        (
            "The protocol or SAP's eligible analysis methods and which were reported, including adjustment, transformation, composite definitions, and missing-data strategies.",
        ),
        "Answer no_information when intentions are unavailable or insufficiently detailed and more than one eligible analysis was possible.",
        (
            _anchor(
                Answer.YES,
                "Multiple eligible analyses existed and the reported subset was likely selected on the results.",
            ),
            _anchor(
                Answer.NO,
                "All eligible analyses correspond to intentions, or only one eligible analysis was possible.",
            ),
            _anchor(
                Answer.NO_INFORMATION,
                "Analysis intentions are insufficiently reported despite multiple possible analyses.",
            ),
        ),
        ("Restrict the assessment to analyses eligible for the reviewer's synthesis.",),
        (
            "an endpoint definition",
            "a single ITT analysis",
            "one reported model",
            "a registry link without analysis detail",
        ),
    ),
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
        _suggestion("protocol deviation", "phrase", "trial-context deviation", "protocol"),
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
        _suggestion("all randomized patients", "all", "equivalent assignment-population wording"),
        _suggestion("per protocol", "phrase", "non-assignment analysis"),
    ),
    "sq:deviations:substantial-impact": (
        _suggestion("excluded participants", "all", "post-randomization exclusions"),
        _suggestion("wrong intervention group", "phrase", "analysis group mismatch"),
    ),
    "sq:missing:data-available": (
        _suggestion("missing outcome data", "all", "outcome availability"),
        _suggestion("loss to follow-up", "phrase", "follow-up completeness"),
        _suggestion("outcome data available", "all", "observed outcome reporting"),
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
    question_id: guidance.model_copy(
        update={
            "operational": guidance.operational.model_copy(
                update={"query_suggestions": _QUERY_SUGGESTIONS[question_id]}
            )
        }
    )
    for question_id, guidance in _GUIDANCE.items()
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
}
SCIENTIFIC_PACK = ScientificPack(**_CONTENT, content_hash=sha256(_CONTENT))


def load_scientific_pack(data: dict[str, object]) -> ScientificPack:
    """Validate a serialized pack and reject a mismatched declared identity hash."""

    pack = ScientificPack.model_validate(data)
    content = pack.model_dump(mode="python", exclude={"content_hash"}, exclude_none=True)
    if pack.content_hash != sha256(content):
        raise ValueError("scientific pack content hash does not match its content")
    return pack
