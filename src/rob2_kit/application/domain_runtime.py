"""Server-owned signalling-question activation and evidence admissibility."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from rob2_kit.logic.evaluator import active_questions

from ._state import identity, read_json, write_json
from .admissibility import validate_domain_answers
from .contracts import RecordReference
from .domains import (
    DomainDraftInput,
    DomainValidationRequest,
    _packet_record,
    validate_domain_judgment,
)
from .evidence import TextEvidenceRecord, VisualEvidenceRecord, resolve_evidence
from .transport import validation_repairs


def _state_name(packet: RecordReference) -> str:
    return f"domain-draft-{packet.identity.removeprefix('sha256:')}.json"


def _stored(workspace: str | Path, packet: RecordReference) -> dict[str, object]:
    raw = read_json(workspace, _state_name(packet))
    if not isinstance(raw, dict):
        return {
            "kind": "domain_draft",
            "packet": packet.model_dump(mode="json"),
            "answers": {},
            "limitations": [],
            "override": None,
        }
    if raw.get("packet") != packet.model_dump(mode="json") or not isinstance(
        raw.get("answers"), dict
    ):
        raise ValueError("persisted Domain draft is stale or corrupt")
    return raw


def _save(workspace: str | Path, packet: RecordReference, state: dict[str, object]) -> None:
    payload = {
        "kind": "domain_draft",
        "packet": packet.model_dump(mode="json"),
        "answers": state["answers"],
        "limitations": state.get("limitations", []),
        "override": state.get("override"),
    }
    write_json(workspace, _state_name(packet), {**payload, "identity": identity(payload)})


def _answer_rows(raw: Mapping[str, Any]) -> list[dict[str, object]]:
    values = raw.get("active_answers", ())
    if not isinstance(values, Sequence) or isinstance(values, str | bytes | bytearray):
        raise TypeError("draft.active_answers must be an array")
    rows: list[dict[str, object]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise TypeError("each active answer must be an object")
        row = dict(value)
        if not isinstance(row.get("question_id"), str):
            raise TypeError("each active answer requires question_id")
        rows.append(row)
    return rows


def _evidence_texts(
    workspace: str | Path, answers: Sequence[Mapping[str, object]]
) -> dict[str, str]:
    result: dict[str, str] = {}
    for answer in answers:
        uses = answer.get("evidence_uses", ())
        if not isinstance(uses, Sequence) or isinstance(uses, str | bytes | bytearray):
            continue
        for use in uses:
            if not isinstance(use, Mapping):
                continue
            refs = use.get("evidence", ())
            if not isinstance(refs, Sequence) or isinstance(refs, str | bytes | bytearray):
                continue
            for raw_ref in refs:
                try:
                    from .contracts import EvidenceReference

                    reference = EvidenceReference.model_validate(raw_ref)
                    record = resolve_evidence(workspace, reference)
                    text = (
                        record.quote
                        if isinstance(record, TextEvidenceRecord)
                        else record.transcription
                        if isinstance(record, VisualEvidenceRecord)
                        else ""
                    )
                    result[reference.identity] = text
                except (TypeError, ValueError):
                    continue
    return result


def _core_answer(row: Mapping[str, object]) -> dict[str, object]:
    uses: list[dict[str, object]] = []
    raw_uses = row.get("evidence_uses", ())
    if not isinstance(raw_uses, Sequence) or isinstance(raw_uses, str | bytes | bytearray):
        raise TypeError("evidence_uses must be an array")
    for use in raw_uses:
        if not isinstance(use, Mapping):
            raise TypeError("each evidence use must be an object")
        source_fact = use.get("source_fact")
        inference = use.get("inference")
        claim = (
            source_fact
            if isinstance(source_fact, str) and source_fact.strip()
            else use.get("claim")
        )
        rationale = (
            inference if isinstance(inference, str) and inference.strip() else use.get("rationale")
        )
        uses.append(
            {
                "relationship": use.get("relationship"),
                "claim": claim,
                "rationale": rationale,
                "evidence": use.get("evidence"),
            }
        )
    return {
        "question_id": row.get("question_id"),
        "answer": row.get("answer"),
        "rationale": row.get("rationale"),
        "evidence_uses": uses,
    }


def validate_domain_runtime(
    workspace: str | Path,
    packet_value: object,
    raw_draft: Mapping[str, Any],
) -> object:
    try:
        packet = RecordReference.model_validate(packet_value)
        packet_data = _packet_record(workspace, packet)
        incoming = _answer_rows(raw_draft)
        state = _stored(workspace, packet)
    except ValidationError as error:
        return validation_repairs(error)
    except (TypeError, ValueError) as error:
        return {
            "outcome": "repair",
            "repairs": [{"pointer": "", "code": "invalid", "detail": str(error)}],
        }

    answers = dict(state["answers"])
    for row in incoming:
        answers[str(row["question_id"])] = row
    state["answers"] = answers
    if "limitations" in raw_draft:
        state["limitations"] = list(raw_draft.get("limitations") or [])
    if "override" in raw_draft:
        state["override"] = raw_draft.get("override")

    guidance = list(packet_data.get("question_guidance", ()))
    order = [str(item["id"]) for item in guidance if isinstance(item, dict)]
    allowed = set(str(item) for item in packet_data.get("allowed_question_ids", order))
    answer_tokens = {
        question_id: str(row.get("answer"))
        for question_id, row in answers.items()
        if isinstance(row, Mapping) and row.get("answer") is not None
    }
    try:
        active = tuple(
            question_id for question_id in active_questions(answer_tokens) if question_id in allowed
        )
    except ValueError as error:
        return {
            "outcome": "repair",
            "repairs": [
                {
                    "pointer": "/active_answers",
                    "code": "invalid",
                    "detail": str(error),
                }
            ],
        }
    extras = sorted(set(answers) - set(active))
    if extras:
        return {
            "outcome": "repair",
            "repairs": [
                {
                    "pointer": "/active_answers",
                    "code": "inactive_questions",
                    "detail": f"remove answers for inactive questions: {extras!r}",
                }
            ],
        }
    missing = [question_id for question_id in active if question_id not in answers]
    if missing:
        _save(workspace, packet, state)
        by_id = {str(item["id"]): item for item in guidance if isinstance(item, dict)}
        return {
            "outcome": "condition",
            "code": "answer_question_wave",
            "detail": "answer every question in the server-derived current wave",
            "question_wave": [by_id[item] for item in missing],
            "accumulated_answer_ids": [item for item in order if item in answers],
            "next_action": {
                "operation": "validate_domain_judgment",
                "authority": "host",
                "packet": packet.model_dump(mode="json"),
                "draft": None,
            },
        }

    ordered_rows = [answers[item] for item in order if item in active]
    evidence_texts = _evidence_texts(workspace, ordered_rows)
    admissibility = validate_domain_answers(ordered_rows, evidence_texts)
    if admissibility:
        _save(workspace, packet, state)
        return {
            "outcome": "repair",
            "repairs": [item.model_dump(mode="json") for item in admissibility],
            "next_action": "correct_evidence_or_use_no_information",
        }

    try:
        draft = DomainDraftInput.model_validate(
            {
                "active_answers": [_core_answer(row) for row in ordered_rows],
                "limitations": state.get("limitations", []),
                "override": state.get("override"),
            }
        )
    except (TypeError, ValidationError) as error:
        if isinstance(error, ValidationError):
            return validation_repairs(error, prefix="/draft")
        return {
            "outcome": "repair",
            "repairs": [{"pointer": "/draft", "code": "wrong_type", "detail": str(error)}],
        }
    result = validate_domain_judgment(
        workspace, DomainValidationRequest(packet=packet, draft=draft)
    )
    payload = result.model_dump(mode="json", exclude_none=True)
    candidate = payload.get("candidate")
    if isinstance(candidate, Mapping) and isinstance(candidate.get("identity"), str):
        audit = {
            "kind": "domain_scientific_draft",
            "candidate": dict(candidate),
            "packet": packet.model_dump(mode="json"),
            "answers": ordered_rows,
            "limitations": state.get("limitations", []),
            "override": state.get("override"),
        }
        audit["identity"] = identity(audit)
        write_json(
            workspace,
            f"domain-scientific-{str(candidate['identity']).removeprefix('sha256:')}.json",
            audit,
        )
        payload["scientific_draft"] = {
            "identity": audit["identity"],
            "kind": audit["kind"],
        }
    return payload
