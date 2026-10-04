"""Opt-in D3 context source material; does not replace the canonical scientific pack.

Complete Box 8 elaborations and shared official guidance are reflowed only.
Provenance and independently captured source layout accompany the prototype record.
"""

from rob2_kit.models import OfficialQuestionGuidance

from .scientific import _GUIDANCE_SOURCE_SHA256, _GUIDANCE_VERSION

D3_GUIDANCE_PROFILE = "official_d3_prototype"
OFFICIAL_SOURCE_URL = (
    "https://drive.google.com/uc?export=download&id=19R9savfPdCHC8XLz2iiMvL_71lPJERWK"
)
FAQ_SOURCE_URL = "https://www.cochrane.org/learn/courses-and-resources/cochrane-methodology/risk-bias/about-risk-bias-2-rob-2"
FAQ_SOURCE_SHA256 = "060C4F0AA70573BB5D07257EB3D7B1DFFF07C4373DE1907E0C1055ADDBA4F8CD"

D3_QUESTION_GUIDANCE: dict[str, OfficialQuestionGuidance] = {
    "sq:missing:data-available": OfficialQuestionGuidance(
        version=_GUIDANCE_VERSION,
        source_locator="Full guidance p. 45, Box 8, signalling question 3.1",
        source_sha256=_GUIDANCE_SOURCE_SHA256,
        source_excerpt=(
            "The appropriate study population for an analysis of the intention to treat "
            "effect is all randomized participants. “Nearly all” should be interpreted as "
            "that the number of participants with missing outcome data is sufficiently "
            "small that their outcomes, whatever they were, could have made no important "
            "difference to the estimated effect of intervention. For continuous outcomes, "
            "availability of data from 95% of the participants will often be sufficient. "
            "For dichotomous outcomes, the proportion required is directly linked to the "
            "risk of the event. If the observed number of events is much greater than the "
            "number of participants with missing outcome data, the bias would necessarily "
            "be small. Only answer ‘No information’ if the trial report provides no "
            "information about the extent of missing outcome data. This situation will "
            "usually lead to a judgement that there is a high risk of bias due to missing "
            "outcome data. Note that imputed data should be regarded as missing data, and "
            "not considered as ‘outcome data’ in the context of this question."
        ),
    ),
    "sq:missing:evidence-unbiased": OfficialQuestionGuidance(
        version=_GUIDANCE_VERSION,
        source_locator="Full guidance p. 45, Box 8, signalling question 3.2",
        source_sha256=_GUIDANCE_SOURCE_SHA256,
        source_excerpt=(
            "Evidence that the result was not biased by missing outcome data may come from: "
            "(1) analysis methods that correct for bias; or (2) sensitivity analyses "
            "showing that results are little changed under a range of plausible assumptions "
            "about the relationship between missingness in the outcome and its true value. "
            "However, imputing the outcome variable, either through methods such as "
            "‘last-observation-carried-forward’ or via multiple imputation based only on "
            "intervention group, should not be assumed to correct for bias due to missing "
            "outcome data."
        ),
    ),
    "sq:missing:true-value-dependent": OfficialQuestionGuidance(
        version=_GUIDANCE_VERSION,
        source_locator="Full guidance p. 45, Box 8, signalling question 3.3",
        source_sha256=_GUIDANCE_SOURCE_SHA256,
        source_excerpt=(
            "If loss to follow up, or withdrawal from the study, could be related to "
            "participants’ health status, then it is possible that missingness in the "
            "outcome was influenced by its true value. However, if all missing outcome data "
            "occurred for documented reasons that are unrelated to the outcome then the "
            "risk of bias due to missing outcome data will be low (for example, failure of "
            "a measuring device or interruptions to routine data collection). In "
            "time-to-event analyses, participants censored during trial follow-up, for "
            "example because they withdrew from the study, should be regarded as having "
            "missing outcome data, even though some of their follow up is included in the "
            "analysis. Note that such participants may be shown as included in analyses in "
            "CONSORT flow diagrams."
        ),
    ),
    "sq:missing:likely-dependent": OfficialQuestionGuidance(
        version=_GUIDANCE_VERSION,
        source_locator="Full guidance pp. 45-46, Box 8, signalling question 3.4",
        source_sha256=_GUIDANCE_SOURCE_SHA256,
        source_excerpt=(
            "This question distinguishes between situations in which (i) missingness in the "
            "outcome could depend on its true value (assessed as ‘Some concerns’) from "
            "those in which (ii) it is likely that missingness in the outcome depended on "
            "its true value (assessed as ‘High risk of bias’). Five reasons for answering "
            "‘Yes’ are: 1. Differences between intervention groups in the proportions of "
            "missing outcome data. If there is a difference between the effects of the "
            "experimental and comparator interventions on the outcome, and the missingness "
            "in the outcome is influenced by its true value, then the proportions of "
            "missing outcome data are likely to differ between intervention groups. Such a "
            "difference suggests a risk of bias due to missing outcome data, because the "
            "trial result will be sensitive to missingness in the outcome being related to "
            "its true value. For time-to-event-data, the analogue is that rates of "
            "censoring (loss to follow-up) differ between the intervention groups. 2. "
            "Reported reasons for missing outcome data provide evidence that missingness in "
            "the outcome depends on its true value; 3. Reported reasons for missing outcome "
            "data differ between the intervention groups; 4. The circumstances of the trial "
            "make it likely that missingness in the outcome depends on its true value. For "
            "example, in trials of interventions to treat schizophrenia it is widely "
            "understood that continuing symptoms make drop out more likely. 5. In "
            "time-to-event analyses, participants’ follow up is censored when they stop or "
            "change their assigned intervention, for example because of drug toxicity or, "
            "in cancer trials, when participants switch to second-line chemotherapy. Answer "
            "‘No’ if the analysis accounted for participant characteristics that are likely "
            "to explain the relationship between missingness in the outcome and its true "
            "value."
        ),
    ),
}

D3_SHARED_GUIDANCE = (
    OfficialQuestionGuidance(
        version=_GUIDANCE_VERSION,
        source_locator="Full guidance p. 3, sections 1.1 and 1.1.1",
        source_sha256=_GUIDANCE_SOURCE_SHA256,
        source_excerpt=(
            "1.1 Signalling questions Inclusion of signalling questions within each domain "
            "of bias is a key feature of RoB 2. Signalling questions aim to elicit "
            "information relevant to an assessment of risk of bias. They seek to be "
            "reasonably factual in nature. Responses to these questions feed into "
            "algorithms we have developed to guide users of the tool to judgements about "
            "the risk of bias. The response options for the signalling questions are: (1) "
            "Yes; (2) Probably yes; (3) Probably no; (4) No; (5) No information; To "
            "maximize the signalling questions’ simplicity and clarity, they are phrased "
            "such that a response of ‘Yes’ may be indicative of either a low or high risk "
            "of bias, depending on the most natural way to ask the question. Responses of "
            "‘Yes’ and ‘Probably yes’ have the same implications for risk of bias, as do "
            "responses of ‘No’ and ‘Probably no’. The definitive versions (‘Yes’ and ‘No’) "
            "would typically imply that firm evidence is available in relation to the "
            "signalling question; the ‘Probably’ versions would typically imply that a "
            "judgement has been made. If review authors calculate measures of agreement "
            "(e.g. kappa statistics) for the answers to the signalling questions, we "
            "recommend treating ‘Yes’ and ‘Probably yes’ as the same response and ‘No’ and "
            "‘Probably no’ as the same response. The ‘No information’ response should be "
            "used only when both (i) insufficient details are reported to permit a response "
            "of ‘Probably yes’ or ‘Probably no’, and (ii) in the absence of these details "
            "it would be unreasonable to respond ‘Probably yes’ or ‘Probably no’ in the "
            "circumstances of the trial. For example, in the context of a large trial run "
            "by an experienced clinical trials unit, absence of specific information about "
            "generation of the randomization sequence, in a paper published in a journal "
            "with rigorously enforced word count limits, is likely to result in a response "
            "of ‘Probably yes’ rather than ‘No information’ to the signalling question "
            "about sequence generation. The implications for risk of bias judgements of a "
            "‘No information’ response to a signalling question differ according to the "
            "purpose of the question. If the question seeks to identify evidence of a "
            "problem, then ‘No information’ corresponds to no evidence of that problem. If "
            "the question relates to an item that is expected to be reported (such as "
            "whether any participants were lost to follow up), then the absence of "
            "information leads to concerns about there being a problem. For signalling "
            "questions that are answered only if the response to a previous question "
            "implies that they are required, a response option ‘Not applicable’ is "
            "available. Signalling questions should be answered independently: the answer "
            "to one question should not affect answers to other questions in the same or "
            "other domains other than through determining which subsequent questions are "
            "answered. 1.1.1 Free-text boxes alongside signalling questions The tool "
            "provides space for free text alongside the signalling question. In some "
            "instances, when the same information is likely to be used to answer more than "
            "one question, one text box covers more than one question. These boxes should "
            "be used to provide support for the answer to each signalling question. Brief "
            "direct quotations from the text of the study report should be used whenever "
            "possible."
        ),
    ),
    OfficialQuestionGuidance(
        version=_GUIDANCE_VERSION,
        source_locator="Full guidance p. 39, section 6.1, Background",
        source_sha256=_GUIDANCE_SOURCE_SHA256,
        source_excerpt=(
            "Randomization provides a fair comparison between two or more intervention "
            "groups by balancing, on average, the distribution of known and unknown "
            "prognostic factors at baseline between the intervention groups. Missing "
            "measurements of the outcome, for example due to dropout during the study, may "
            "lead to bias in the intervention effect estimate. Possible reasons for missing "
            "outcome data include (83): • participants withdraw from the study or cannot be "
            "located (‘loss to follow-up’ or ‘dropout’); • participants do not attend a "
            "study visit at which outcomes should have been measured; • participants attend "
            "a study visit but do not provide relevant data; • data or records are lost or "
            "are unavailable for other reasons; and • participants can no longer experience "
            "the outcome, for example because they have died. This domain addresses risk of "
            "bias due to missing outcome data, including biases introduced by procedures "
            "used to impute, or otherwise account for, the missing outcome data. Some "
            "participants may be excluded from an analysis for reasons other than missing "
            "outcome data. In particular, a naïve ‘per protocol’ analysis is restricted to "
            "participants who received the intended intervention (see section 1.3.1). "
            "Potential bias introduced by such analyses, or by other exclusions of eligible "
            "participants for whom outcome data are available, is addressed in the domain "
            "‘Bias due to deviations from intended interventions’ (see section 5), in which "
            "the final signalling questions examine whether the analysis approach was "
            "appropriate. This is a notable change from the previous Cochrane RoB tool for "
            "randomized trials, in which the domain addressing bias due to incomplete "
            "outcome data addressed both genuinely missing data and data deliberately "
            "excluded by the trial investigators."
        ),
    ),
    OfficialQuestionGuidance(
        version=_GUIDANCE_VERSION,
        source_locator="Full guidance p. 44, section 6.3",
        source_sha256=_GUIDANCE_SOURCE_SHA256,
        source_excerpt=(
            "6.3 Using this domain of the tool (1) Risk of bias will be low if outcome data "
            "are available for all, or nearly all, randomized participants. The meaning of "
            "‘nearly all’ in this context is that the number of participants with missing "
            "outcome data is so small that their outcomes, whatever they were, could have "
            "made no important difference to the estimated effect of intervention. If this "
            "is the case then no further signalling questions need be answered. Absence of "
            "information about the extent of missing outcome data (for example, when no "
            "CONSORT flow diagram was provided in the trial report) will usually lead to a "
            "judgement of high risk of bias for this domain. (2) Risk of bias will be low "
            "if sensitivity analyses, conducted by either the trial investigators or the "
            "review authors (see section 6.1.7), confirm that the finding is robust to "
            "plausible values of the missing outcome data. Such analyses are likely to be "
            "particularly useful when the amount of missing data is sufficiently large for "
            "the potential impact on the estimated effect of intervention to be "
            "substantial. If sensitivity analyses confirm that the result is robust, then "
            "the result may be regarded as at low risk of bias and no further signalling "
            "questions need be answered. (3) As explained in section 6.1.3, missing outcome "
            "data can only lead to bias if the chance that the outcome is missing depends "
            "on its true value. It may be possible to exclude this based on reported "
            "reasons for missing outcome data (for example, if outcome data are only "
            "missing because of failure of a measuring instrument or closure of a centre in "
            "a multicentre trial). However, if it is possible that missingness in the "
            "outcome could depend on its true value then review investigators will need to "
            "consider the proportions of and reasons for missing outcome data. (4) A "
            "difference between the experimental and comparator intervention groups in the "
            "proportions of missing outcome data may indicate a risk of bias (see section "
            "6.1.4). For time-to-event-data, review authors should consider whether rates "
            "of censoring (loss to follow-up) differ between the intervention groups. (5) "
            "Either reasons for missing outcome data reported by trial investigators, or "
            "the circumstances of the trial, may lead review authors to conclude that it is "
            "likely that missingness in the outcome depended on its true value. (6) "
            "Differing reasons for missing outcome data in the experimental and comparator "
            "intervention groups may lead to substantial bias. For example, in a trial of "
            "an experimental intervention aimed at smoking cessation there would be serious "
            "bias if some comparator intervention participants left the study due to a lack "
            "of enthusiasm at receiving nothing novel (and continued to smoke) while some "
            "experimental intervention participants left the study due to successful "
            "cessation of smoking."
        ),
    ),
)

D3_FAQ_GUIDANCE = {
    "sq:missing:data-available": OfficialQuestionGuidance(
        version="Undated page; retrieved 4 October 2026",
        source_locator="FAQs relating to Domain 3; SQ3.1: unknown extent of missing data",
        source_sha256=FAQ_SOURCE_SHA256,
        source_excerpt=("A ‘Probably yes’ or ‘Probably no’ response may be the most appropriate."),
    ),
    "sq:missing:evidence-unbiased": OfficialQuestionGuidance(
        version="Undated page; retrieved 4 October 2026",
        source_locator="FAQs relating to Domain 3; SQ3.2: lists of methods correcting bias",
        source_sha256=FAQ_SOURCE_SHA256,
        source_excerpt=("It is not helpful to focus on methods per se."),
    ),
}
