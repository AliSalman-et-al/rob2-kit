"""Strict, canonical data shared by the RoB 2 packs and evaluator."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Answer(StrEnum):
    YES = "yes"
    PROBABLY_YES = "probably_yes"
    PROBABLY_NO = "probably_no"
    NO = "no"
    NO_INFORMATION = "no_information"


class Judgment(StrEnum):
    LOW = "low"
    SOME_CONCERNS = "some_concerns"
    HIGH = "high"


def canonical_json_bytes(value: object) -> bytes:
    """Return the one JSON representation used for content identities."""

    def json_value(item: object) -> object:
        if isinstance(item, BaseModel):
            return json_value(item.model_dump(mode="python", exclude_none=True))
        if isinstance(item, Mapping):
            return {str(key): json_value(value) for key, value in item.items()}
        if isinstance(item, (tuple, list)):
            return [json_value(value) for value in item]
        if isinstance(item, datetime):
            if item.tzinfo is None or item.utcoffset() is None:
                raise ValueError("canonical timestamps must be timezone-aware")
            return item.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return item

    return json.dumps(
        json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class Provenance(StrictModel):
    id: str
    title: str
    version: str
    url: str
    locator: str
    attribution: str


class AlwaysActive(StrictModel):
    kind: Literal["always"] = "always"


class ActivationPredicate(StrictModel):
    question_id: str = Field(min_length=1)
    accepted_answers: tuple[Answer, ...] = Field(min_length=1)


class ConditionalActivation(StrictModel):
    kind: Literal["rule"] = "rule"
    mode: Literal["any", "all"]
    predicates: tuple[ActivationPredicate, ...] = Field(min_length=1)


Activation = Annotated[AlwaysActive | ConditionalActivation, Field(discriminator="kind")]


class Question(StrictModel):
    id: str
    domain_id: str
    wording: str
    allowed_answers: tuple[Answer, ...] = tuple(Answer)
    activation: Activation = Field(default_factory=AlwaysActive)


class Domain(StrictModel):
    id: str
    question_ids: tuple[str, ...]


class ScientificPack(StrictModel):
    id: str
    version: str
    provenance: Provenance
    questions: tuple[Question, ...]
    domains: tuple[Domain, ...]
    content_hash: str

    @model_validator(mode="after")
    def activation_predicates_are_valid(self) -> ScientificPack:
        questions = {
            question.id: (position, question) for position, question in enumerate(self.questions)
        }
        for position, question in enumerate(self.questions):
            if not isinstance(question.activation, ConditionalActivation):
                continue
            for predicate in question.activation.predicates:
                predecessor_row = questions.get(predicate.question_id)
                if predecessor_row is None:
                    raise ValueError("activation predicate references an unknown question")
                predecessor_position, predecessor = predecessor_row
                if predecessor_position >= position:
                    raise ValueError("activation predicate must reference an earlier question")
                if predecessor.domain_id != question.domain_id:
                    raise ValueError("activation predicate must reference the same domain")
                if not set(predicate.accepted_answers) <= set(predecessor.allowed_answers):
                    raise ValueError("activation predicate accepts a disallowed predecessor answer")
        return self


class LexicalSeed(StrictModel):
    id: str
    terms: tuple[str, ...]


class PolicyPack(StrictModel):
    id: str
    version: str
    attribution: str
    lexical_seeds: tuple[LexicalSeed, ...]
    source_priority: tuple[str, ...]
    contradiction_checks: tuple[str, ...]
    selective_vision: tuple[str, ...]
    content_hash: str

    def seeds_for(self, identifier: str) -> tuple[str, ...]:
        """Return the deterministic lexical seeds for one policy topic."""
        for seed in self.lexical_seeds:
            if seed.id == identifier:
                return seed.terms
        raise KeyError(identifier)


class Evaluation(StrictModel):
    domain_id: str
    judgment: Judgment
    trace: tuple[str, ...] = Field(min_length=1)


class OverallEvaluation(StrictModel):
    judgment: Judgment
    trace: tuple[str, ...] = Field(min_length=1)
