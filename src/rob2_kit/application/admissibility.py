"""Deterministic admissibility checks for RoB 2 signalling evidence.

The checks deliberately target known invalid proxies. They do not decide the
RoB 2 answer; they prevent an affirmative or negative token from being
justified by facts that cannot establish the proposition.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AdmissibilityDefect(_Closed):
    pointer: str
    code: str
    detail: str
    suggested_answer: Literal["no_information"] | None = None


_AFFIRMATIVE = {"yes", "probably_yes"}
_NEGATIVE = {"no", "probably_no"}
_PROXY = re.compile(
    r"\b(?:typically|standardly|generally|usually|trial reputation|"
    r"well[- ]balanced|similar group sizes|no reported problems|"
    r"objective outcome|stratif(?:ied|ication))\b",
    re.IGNORECASE,
)

_RULES: dict[str, tuple[re.Pattern[str], ...]] = {
    "sq:randomization:sequence": (
        re.compile(r"\brandom(?:ly|ization|isation| allocation| sequence)\b", re.I),
        re.compile(r"\bpermuted block", re.I),
        re.compile(r"\bcomputer[- ]generated", re.I),
    ),
    "sq:randomization:concealment": (
        re.compile(r"\ballocation (?:was )?concealed\b", re.I),
        re.compile(r"\bcentral(?:ized|ised)? randomi[sz]ation\b", re.I),
        re.compile(r"\binteractive (?:voice|web) response\b", re.I),
        re.compile(r"\btelephone randomi[sz]ation\b", re.I),
        re.compile(r"\bsealed,? opaque", re.I),
        re.compile(r"\bpharmacy[- ]controlled", re.I),
    ),
    "sq:missing:data-available": (
        re.compile(r"\b(?:follow[- ]up|outcome data|vital status|endpoint data)\b", re.I),
        re.compile(r"\b(?:lost to follow[- ]up|censored|missing outcome)\b", re.I),
        re.compile(r"\b\d+\s*/\s*\d+\b", re.I),
    ),
    "sq:deviations:appropriate-analysis": (
        re.compile(r"\bintention[- ]to[- ]treat\b", re.I),
        re.compile(r"\bas randomized\b", re.I),
        re.compile(r"\bassigned (?:group|intervention)\b", re.I),
    ),
    "sq:selection:prespecified-analysis": (
        re.compile(r"\b(?:protocol|statistical analysis plan|sap|registry)\b", re.I),
        re.compile(r"\bpre[- ]specified\b", re.I),
    ),
}


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


def _use_text(use: Mapping[str, object]) -> str:
    chunks = [use.get("source_fact"), use.get("claim"), use.get("evidence_text")]
    return "\n".join(str(item) for item in chunks if isinstance(item, str))


def validate_answer(
    question_id: str,
    answer: str,
    rationale: str,
    evidence_uses: Sequence[Mapping[str, object]],
    *,
    pointer: str,
) -> tuple[AdmissibilityDefect, ...]:
    defects: list[AdmissibilityDefect] = []
    source_text = "\n".join(_use_text(use) for use in evidence_uses)
    inference_text = "\n".join(
        str(use.get("inference") or use.get("rationale") or "") for use in evidence_uses
    )
    if answer in _AFFIRMATIVE and question_id in _RULES:
        patterns = _RULES[question_id]
        if not any(pattern.search(source_text) for pattern in patterns):
            defects.append(
                AdmissibilityDefect(
                    pointer=pointer,
                    code="inadmissible_proxy",
                    detail=(
                        "the answer lacks a source fact that can establish the "
                        "signalling proposition"
                    ),
                    suggested_answer="no_information",
                )
            )
    if answer in {"probably_yes", "probably_no"} and (
        not source_text.strip()
        or (
            _PROXY.search(inference_text)
            and not any(pattern.search(source_text) for pattern in _RULES.get(question_id, ()))
        )
    ):
        defects.append(
            AdmissibilityDefect(
                pointer=pointer,
                code="generic_expectation",
                detail=(
                    "a probable answer requires source-specific indirect Evidence, "
                    "not routine practice or trial reputation"
                ),
                suggested_answer="no_information",
            )
        )
    if question_id == "sq:randomization:concealment" and answer in _AFFIRMATIVE:
        proxy_only = _PROXY.search(source_text) and not any(
            pattern.search(source_text) for pattern in _RULES[question_id]
        )
        if proxy_only:
            defects.append(
                AdmissibilityDefect(
                    pointer=pointer,
                    code="concealment_not_reported",
                    detail=(
                        "stratification, baseline balance, and coordinating-group "
                        "reputation do not establish allocation concealment"
                    ),
                    suggested_answer="no_information",
                )
            )
    if question_id == "sq:missing:data-available" and answer in _AFFIRMATIVE:
        if re.search(r"\brandomi[sz]ed\b", source_text, re.I) and not re.search(
            r"\b(?:follow[- ]up|outcome data|vital status|endpoint data|"
            r"censored|missing)\b",
            source_text,
            re.I,
        ):
            defects.append(
                AdmissibilityDefect(
                    pointer=pointer,
                    code="enrollment_is_not_outcome_coverage",
                    detail=(
                        "randomized enrollment counts alone do not establish "
                        "outcome-data availability"
                    ),
                    suggested_answer="no_information",
                )
            )
    first = _first_sentence(rationale).casefold()
    if answer in _AFFIRMATIVE and re.match(r"^(?:no|not|there (?:was|is) no)\b", first):
        defects.append(
            AdmissibilityDefect(
                pointer=pointer,
                code="polarity_mismatch",
                detail=("answer token and first rationale sentence have opposite polarity"),
            )
        )
    if answer in _NEGATIVE and re.match(
        r"^(?:yes|the proposition (?:was|is)|there (?:was|is))\b", first
    ):
        defects.append(
            AdmissibilityDefect(
                pointer=pointer,
                code="polarity_mismatch",
                detail=("answer token and first rationale sentence have opposite polarity"),
            )
        )
    unique = {(item.pointer, item.code, item.detail): item for item in defects}
    return tuple(unique[key] for key in sorted(unique))


def validate_domain_answers(
    answers: Sequence[Mapping[str, object]],
    evidence_text_by_identity: Mapping[str, str],
) -> tuple[AdmissibilityDefect, ...]:
    defects: list[AdmissibilityDefect] = []
    for index, answer in enumerate(answers):
        question_id = str(answer.get("question_id", ""))
        token = str(answer.get("answer", ""))
        rationale = str(answer.get("rationale", ""))
        uses: list[dict[str, object]] = []
        raw_uses = answer.get("evidence_uses", ())
        if isinstance(raw_uses, Sequence) and not isinstance(raw_uses, str | bytes | bytearray):
            for use in raw_uses:
                if not isinstance(use, Mapping):
                    continue
                rendered = dict(use)
                evidence = use.get("evidence", ())
                texts: list[str] = []
                if isinstance(evidence, Sequence) and not isinstance(
                    evidence, str | bytes | bytearray
                ):
                    for reference in evidence:
                        if isinstance(reference, Mapping) and isinstance(
                            reference.get("identity"), str
                        ):
                            text = evidence_text_by_identity.get(str(reference["identity"]))
                            if text:
                                texts.append(text)
                rendered["evidence_text"] = "\n".join(texts)
                uses.append(rendered)
        defects.extend(
            validate_answer(
                question_id,
                token,
                rationale,
                uses,
                pointer=f"/active_answers/{index}",
            )
        )
    return tuple(defects)
