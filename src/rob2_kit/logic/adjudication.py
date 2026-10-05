"""Bound domain judgment departures; scientific rationale remains host-owned."""

import json
from typing import Any

from pydantic import ValidationError

from ..workflow_models import DomainDecision
from .evaluator import evaluate_domain

DOMAIN_JUDGMENT_CONTRACT = "rob2-kit.domain.reasoned-adjudication.v1"
LEGACY_DOMAIN_JUDGMENT_CONTRACT = "rob2-kit.domain.algorithm-only.v1"


# The existing stable context header is indivisible. Reserve 16 KiB for the
# native typed envelope, page/cursor metadata and wrapper headroom; count every
# other stable field and the entire canonical decision in UTF-8, not characters.
DOMAIN_CONTEXT_MAX_BYTES = 131_072
ADJUDICATION_CONTEXT_METADATA_RESERVE = 16_384


def adjudication_context_header_bytes(context: dict[str, Any], record: dict[str, Any]) -> int:
    header = {
        key: value
        for key, value in context.items()
        if key not in {"primary_report", "questions", "evidence", "comparison_cards"}
    }
    header.update(decision=record["decision"], current_checkpoint=record["identity"])
    envelope = {"content": [], "structured_content": header}
    return len(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def require_current_adjudication_pack(state: dict[str, Any], pack_identity: str) -> None:
    """Mixed-pack adjudication history has no supported migration; never rewrite it."""
    for history in state.get("domain_history_records", {}).values():
        for record in history:
            adjudication = (record.get("decision") or {}).get("adjudication")
            if adjudication and adjudication.get("pack_identity") != pack_identity:
                raise ValueError(
                    "adjudication_pack_migration_unsupported: preserve this workspace and "
                    "continue with its pinned prior pack, or start a fresh assessment workspace; "
                    "mixed-pack adjudication history cannot be exported under the current pack"
                )


def domain_evidence_ids(record: object) -> set[str]:
    if not isinstance(record, dict) or not isinstance(record.get("answers"), list):
        return set()
    answer_basis_ids = {
        basis.get("evidence")
        for answer in record["answers"]
        if isinstance(answer, dict) and isinstance(answer.get("bases"), list)
        for basis in answer["bases"]
        if isinstance(basis, dict) and isinstance(basis.get("evidence"), str)
    }
    missing_data_ids = {
        evidence_identity
        for answer in record["answers"]
        if isinstance(answer, dict)
        for row in (answer.get("missing_data") or {}).get("rows", [])
        if isinstance(row, dict) and isinstance(row.get("basis"), list)
        for evidence_identity in row["basis"]
        if isinstance(evidence_identity, str)
    }
    nested_ids = {
        value
        for answer in record["answers"]
        for basis in answer.get("bases", [])
        for value in (basis.get("working_observation", {}).get("count_evidence") or {}).values()
    }
    return answer_basis_ids | missing_data_ids | nested_ids


def valid_domain_decision(
    record: dict[str, Any],
    proposed: str,
    history: dict[str, Any],
    evidence: dict[str, Any],
    pack_identity: str,
) -> bool:
    """Verify explicit adoption against the exact unchanged ancestor assessment."""
    if "decision" not in record:
        return record.get("judgment") == proposed
    try:
        decision = DomainDecision.model_validate(record["decision"]).model_dump(mode="json")
    except (ValidationError, TypeError):
        return False
    if decision != record["decision"] or decision["proposed"] != proposed:
        return False
    try:
        evaluation = evaluate_domain(
            record["domain_id"], {item["question_id"]: item["answer"] for item in record["answers"]}
        )
    except (KeyError, TypeError, ValueError):
        return False
    if record.get("trace") != list(evaluation.trace) or record.get("driver_questions") != list(
        evaluation.driver_questions
    ):
        return False
    adopted = decision["adopted"]
    if record.get("judgment") != adopted:
        return False
    adjudication = decision["adjudication"]
    if adjudication is None:
        return decision["authority"] == "algorithm" and adopted == proposed
    parent = history.get(adjudication["checkpoint_identity"])
    if not isinstance(parent, dict):
        return False
    parent_evidence = domain_evidence_ids(parent)
    return (
        decision["authority"] == "host"
        and adopted != proposed
        and adjudication["judgment"] == adopted
        and adjudication["result_identity"] == record.get("result_identity")
        and adjudication["domain_id"] == record.get("domain_id")
        and adjudication["pack_identity"] == pack_identity
        and isinstance(parent, dict)
        and parent.get("identity")
        == record.get("supersedes")
        == adjudication["checkpoint_identity"]
        and parent.get("trial_id") == record.get("trial_id")
        and parent.get("domain_id") == record.get("domain_id")
        and parent.get("result_identity") == record.get("result_identity")
        and parent.get("answers") == record.get("answers")
        and len(set(adjudication["evidence"])) == len(adjudication["evidence"])
        and all(
            item in parent_evidence
            and evidence.get(item, {}).get("trial_id") == record.get("trial_id")
            for item in [
                *adjudication["evidence"],
                *(point["evidence"] for point in adjudication["counterevidence"]),
            ]
        )
    )


def valid_domain_contract(canonical: dict[str, Any]) -> bool:
    records = canonical.get("domain_history_records")
    if not isinstance(records, dict) or any(
        not isinstance(items, list) for items in records.values()
    ):
        return False
    flattened = [item for items in records.values() for item in items if isinstance(item, dict)]
    if (
        canonical.get("scientific_pack", {}).get("domain_judgment_contract")
        == DOMAIN_JUDGMENT_CONTRACT
    ):
        return canonical.get("legacy_domain_checkpoints") == {
            "contract": LEGACY_DOMAIN_JUDGMENT_CONTRACT,
            "identities": sorted(
                {item["identity"] for item in flattened if "decision" not in item}
            ),
        }
    return "legacy_domain_checkpoints" not in canonical and all(
        "decision" not in item for item in flattened
    )
