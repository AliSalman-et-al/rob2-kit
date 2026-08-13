"""Strict, canonical data shared by the RoB 2 packs and evaluator."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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


class Question(StrictModel):
    id: str
    domain_id: str
    wording: str
    allowed_answers: tuple[Answer, ...] = tuple(Answer)
    active_when: str | None = None


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
