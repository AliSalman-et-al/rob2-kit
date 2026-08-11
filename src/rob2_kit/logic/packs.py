"""Validated, immutable Logic and Guidance pack sources."""

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from rob2_kit.domain.assessment import JudgmentLevel, SQAnswerCategory
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.evidence.obligations import EvidenceSearchObligation, compile_guidance_obligations


class ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Provenance(ImmutableModel):
    """A durable citation for material included in a pack release.

    ``kind`` distinguishes the legal/scientific origin of a citation.  A
    release can therefore contain official wording alongside copied or
    adapted material without collapsing the provenance into one free-text
    note.  Existing pack sources may omit ``id`` and ``kind`` while migrating
    to the richer release format; loaded objects still receive deterministic
    defaults.
    """

    id: str = ""
    kind: Literal["official", "copied", "adapted", "maintainer_authored"] = "official"
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    license: str = Field(min_length=1)
    attribution: str = ""


class Condition(ImmutableModel):
    op: Literal[
        "all",
        "any",
        "answer_in",
        "domain_all",
        "domain_any",
        "domain_count",
        "input_equals",
    ]
    question_id: str | None = None
    answers: tuple[SQAnswerCategory, ...] = ()
    conditions: tuple["Condition", ...] = ()
    judgments: tuple[JudgmentLevel, ...] = ()
    judgment: JudgmentLevel | None = None
    minimum: int | None = Field(default=None, ge=0)
    input_id: str | None = None
    value: bool | None = None

    @model_validator(mode="after")
    def validate_operands(self) -> "Condition":
        required = {
            "answer_in": self.question_id is not None and bool(self.answers),
            "all": bool(self.conditions),
            "any": bool(self.conditions),
            "domain_all": bool(self.judgments),
            "domain_any": bool(self.judgments),
            "domain_count": self.judgment is not None and self.minimum is not None,
            "input_equals": self.input_id is not None and self.value is not None,
        }
        if not required[self.op]:
            raise ValueError(f"invalid operands for closed rule operator {self.op!r}")
        return self


class Question(ImmutableModel):
    id: str = Field(pattern=r"^sq:[a-z0-9:-]+$")
    active_if: Condition | None = None
    allowed_answers: tuple[SQAnswerCategory, ...] = tuple(SQAnswerCategory)

    @model_validator(mode="after")
    def validate_allowed_answers(self) -> "Question":
        if not self.allowed_answers:
            raise ValueError("a signaling question must allow at least one answer")
        canonical = tuple(SQAnswerCategory)
        if len(set(self.allowed_answers)) != len(self.allowed_answers):
            raise ValueError("question allowed_answers must not contain duplicates")
        if any(answer not in canonical for answer in self.allowed_answers):
            raise ValueError("question allowed_answers contains an unknown answer")
        return self


class JudgmentRule(ImmutableModel):
    id: str = Field(pattern=r"^rule:[a-z0-9:-]+$")
    when: Condition
    judgment: JudgmentLevel


class Domain(ImmutableModel):
    id: str = Field(pattern=r"^domain:[a-z0-9:-]+$")
    question_ids: tuple[str, ...]
    judgment_rules: tuple[JudgmentRule, ...]


class AssessorInput(ImmutableModel):
    id: str = Field(pattern=r"^input:[a-z0-9:-]+$")
    value_type: Literal["boolean"]
    required_if: Condition


class LogicPack(ImmutableModel):
    schema_version: Literal["1.0.0"]
    required_schema_version: Literal["1.0.0"]
    family_id: str
    release_id: str
    authors: tuple[str, ...] = Field(min_length=1)
    instrument: Literal["rob2"]
    trial_design: Literal["individually_randomized_parallel_group"]
    effect_of_interest: Literal["assignment"]
    allowed_answers: tuple[SQAnswerCategory, ...]
    questions: tuple[Question, ...]
    domains: tuple[Domain, ...]
    assessor_inputs: tuple[AssessorInput, ...]
    overall_rules: tuple[JudgmentRule, ...]
    inventory: tuple[str, ...]
    provenance: tuple[Provenance, ...]
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_pack(self) -> "LogicPack":
        expected_answers = tuple(SQAnswerCategory)
        if self.allowed_answers != expected_answers:
            raise ValueError("allowed_answers must be the canonical closed vocabulary")
        question_ids = [question.id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Logic question IDs must be globally unique")
        domain_ids = [domain.id for domain in self.domains]
        input_ids = [item.id for item in self.assessor_inputs]
        rule_ids = [rule.id for domain in self.domains for rule in domain.judgment_rules] + [
            rule.id for rule in self.overall_rules
        ]
        all_element_ids = question_ids + domain_ids + input_ids + rule_ids
        if len(all_element_ids) != len(set(all_element_ids)):
            raise ValueError("Logic element IDs must be globally unique")
        if set(self.inventory) != set(all_element_ids) or len(self.inventory) != len(
            all_element_ids
        ):
            raise ValueError("Logic release inventory must contain every element exactly once")
        domain_question_ids = [
            question_id for domain in self.domains for question_id in domain.question_ids
        ]
        if sorted(question_ids) != sorted(domain_question_ids):
            raise ValueError("each question must belong to exactly one declared domain")
        conditions = (
            [
                condition
                for question in self.questions
                if question.active_if is not None
                for condition in _walk_conditions(question.active_if)
            ]
            + [
                condition
                for rule in (
                    [rule for domain in self.domains for rule in domain.judgment_rules]
                    + list(self.overall_rules)
                )
                for condition in _walk_conditions(rule.when)
            ]
            + [
                condition
                for item in self.assessor_inputs
                for condition in _walk_conditions(item.required_if)
            ]
        )
        unknown_question_refs = {
            condition.question_id
            for condition in conditions
            if condition.question_id is not None and condition.question_id not in question_ids
        }
        unknown_input_refs = {
            condition.input_id
            for condition in conditions
            if condition.input_id is not None and condition.input_id not in input_ids
        }
        if unknown_question_refs or unknown_input_refs:
            raise ValueError(
                "conditions reference undeclared Logic elements: "
                f"{sorted(unknown_question_refs | unknown_input_refs)}"
            )
        # Keep each question's answer vocabulary explicit and deterministic.
        # The global vocabulary remains available as a release-level contract,
        # while official exceptions (for example Q3.2) can opt out of
        # ``no_information`` without changing the semantic question ID.
        allowed = {question.id: set(question.allowed_answers) for question in self.questions}
        for condition in conditions:
            if condition.question_id is None:
                continue
            unknown_answers = set(condition.answers) - allowed[condition.question_id]
            if unknown_answers:
                raise ValueError(
                    f"condition for {condition.question_id} uses answers outside its vocabulary: "
                    f"{sorted(unknown_answers)}"
                )
        calculated = canonical_hash(self.model_dump(exclude={"content_hash"}))
        if self.content_hash and self.content_hash != calculated:
            raise ValueError("declared Logic pack content hash does not match canonical content")
        object.__setattr__(self, "content_hash", calculated)
        return self


def _walk_conditions(condition: Condition) -> tuple[Condition, ...]:
    return (condition,) + tuple(
        nested for child in condition.conditions for nested in _walk_conditions(child)
    )


class GuidanceItem(ImmutableModel):
    logic_element_id: str
    content_origin: Literal["official", "copied", "adapted", "maintainer_authored", "rob2_kit"]
    text: str = Field(min_length=1)
    affected_change: Literal["decision_relevant", "presentation_only"]
    # Interpretation remains separate from normative Logic.  These fields are
    # deliberately structured so active-domain context can disclose only the
    # evidence and inference guidance needed for one question.
    provenance_refs: tuple[str, ...] = ()
    evidence_targets: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()
    inference_boundaries: tuple[str, ...] = ()
    no_information_rule: str = ""
    recurring_traps: tuple[str, ...] = ()


class GuidancePack(ImmutableModel):
    schema_version: Literal["1.0.0"]
    required_schema_version: Literal["1.0.0"]
    family_id: str
    release_id: str
    authors: tuple[str, ...] = Field(min_length=1)
    language: str
    compatible_logic_hashes: tuple[str, ...]
    items: tuple[GuidanceItem, ...]
    obligations: tuple[EvidenceSearchObligation, ...] = Field(min_length=1)
    inventory: tuple[str, ...]
    provenance: tuple[Provenance, ...]
    # Pack-wide interpretation boundaries are disclosed alongside the
    # question-specific items.  They make the scientific contract inspectable
    # even when an agent requests a narrowly sliced active-domain context.
    evidence_targets: tuple[str, ...] = ()
    counter_evidence: tuple[str, ...] = ()
    inference_boundaries: tuple[str, ...] = ()
    no_information_rule: str = ""
    recurring_traps: tuple[str, ...] = ()
    content_hash: str = ""

    @model_validator(mode="after")
    def calculate_hash(self) -> "GuidancePack":
        item_ids = [item.logic_element_id for item in self.items]
        if set(self.inventory) != set(item_ids) or len(self.inventory) != len(item_ids):
            raise ValueError("Guidance release inventory must contain every item exactly once")
        if not self.evidence_targets or not self.counter_evidence:
            raise ValueError("Guidance release must state evidence and counter-evidence targets")
        if not self.inference_boundaries or not self.no_information_rule:
            raise ValueError("Guidance release must state inference and No-information boundaries")
        if not self.recurring_traps:
            raise ValueError("Guidance release must record recurring interpretation traps")
        provenance_ids = {item.id for item in self.provenance if item.id}
        enriched: list[GuidanceItem] = []
        for item in self.items:
            updates: dict[str, Any] = {
                "evidence_targets": item.evidence_targets or self.evidence_targets,
                "counter_evidence": item.counter_evidence or self.counter_evidence,
                "inference_boundaries": item.inference_boundaries or self.inference_boundaries,
                "no_information_rule": item.no_information_rule or self.no_information_rule,
                "recurring_traps": item.recurring_traps or self.recurring_traps,
            }
            if not item.provenance_refs:
                if item.content_origin in {"maintainer_authored", "rob2_kit"}:
                    updates["provenance_refs"] = ("provenance:rob2-kit-guidance",)
                elif "provenance:rob2-kit-guidance" in provenance_ids:
                    # Official wording and maintainer interpretation coexist
                    # in one item; retain both citations rather than implying
                    # that authored boundaries were copied from the source.
                    updates["provenance_refs"] = (
                        "provenance:rob2-official",
                        "provenance:rob2-kit-guidance",
                    )
                else:
                    updates["provenance_refs"] = ("provenance:rob2-official",)
            resolved = item.model_copy(update=updates)
            unknown_refs = set(resolved.provenance_refs) - provenance_ids
            if unknown_refs:
                raise ValueError(
                    f"Guidance item {item.logic_element_id} references unknown provenance: "
                    f"{sorted(unknown_refs)}"
                )
            enriched.append(resolved)
        object.__setattr__(self, "items", tuple(enriched))
        calculated = canonical_hash(self.model_dump(exclude={"content_hash"}))
        if self.content_hash and self.content_hash != calculated:
            raise ValueError("declared Guidance pack content hash does not match canonical content")
        object.__setattr__(self, "content_hash", calculated)
        return self


class _PackSafeLoader(yaml.SafeLoader):
    """Safe YAML 1.2-style booleans, preserving RoB answers `yes` and `no`."""


_PackSafeLoader.yaml_implicit_resolvers = {
    key: [resolver for resolver in resolvers if resolver[0] != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_PackSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return yaml.load(source, Loader=_PackSafeLoader)


def parse_pack_yaml(content: bytes) -> Any:
    """Parse pinned pack bytes with the same safe YAML 1.2 rules as live packs."""
    return yaml.load(content, Loader=_PackSafeLoader)


def load_logic_pack(path: Path) -> LogicPack:
    """Safely parse and schema-validate a reviewable Logic pack source."""
    return LogicPack.model_validate(_load_yaml(path))


def load_guidance_pack(path: Path) -> GuidancePack:
    """Safely parse and schema-validate a reviewable Guidance pack source."""
    return GuidancePack.model_validate(_load_yaml(path))


def validate_guidance_compatibility(logic: LogicPack, guidance: GuidancePack) -> None:
    """Require an exact hash pin and a complete, non-duplicated Logic-element inventory."""
    if logic.content_hash not in guidance.compatible_logic_hashes:
        raise ValueError("Guidance pack is not compatible with this exact Logic release")
    expected_ids = {question.id for question in logic.questions} | {
        item.id for item in logic.assessor_inputs
    }
    actual_ids = [item.logic_element_id for item in guidance.items]
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
        raise ValueError("Guidance inventory must cover each Logic element exactly once")
    compile_guidance_obligations(logic, guidance)
