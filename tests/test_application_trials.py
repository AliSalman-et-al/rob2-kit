from __future__ import annotations

from pathlib import Path

import pytest

from rob2_kit.application._state import identity, read_json, write_jsons
from rob2_kit.application.contracts import (
    RecordKind,
    RecordReference,
    ReviewAuthority,
    TrialDisposition,
)
from rob2_kit.application.trials import (
    TrialFinishCandidate,
    TrialFinishRequest,
    acknowledge_trial_finish,
    finish_trial,
    prepare_trial_finish,
)
from rob2_kit.models import Judgment
from rob2_kit.packs import SCIENTIFIC_PACK

# ruff: noqa: E501


def _approved(tmp_path: Path) -> RecordReference:
    approved_identity = identity(
        {"review": "review", "acknowledgment": "ack", "dispositions": (("trial", "pending"),)}
    )
    write_jsons(
        tmp_path,
        {
            "approved_batch.json": {
                "kind": "approved_batch",
                "identity": approved_identity,
                "review": "review",
                "acknowledgment": "ack",
                "dispositions": [["trial", "pending"]],
            },
            "state.json": {"phase": "assessment", "domains": {}},
        },
    )
    return RecordReference(
        kind=RecordKind.APPROVED_BATCH,
        identity=approved_identity,
        uri=f"rob2://detail/approved_batch/{approved_identity}",
    )


def test_prepare_requires_all_verified_domain_observations(tmp_path: Path) -> None:
    approved = _approved(tmp_path)
    result = prepare_trial_finish(
        tmp_path, approved, TrialFinishCandidate(disposition=TrialDisposition.ASSESSED)
    )
    assert result.outcome.value == "condition"
    assert len(result.missing_domains) == 5


def test_terminal_researcher_disposition_and_exact_replay(tmp_path: Path) -> None:
    approved = _approved(tmp_path)
    state = {"phase": "assessment", "domains": {}}
    for domain in SCIENTIFIC_PACK.domains:
        candidate = {
            "kind": "domain_candidate",
            "packet": approved.model_dump(mode="json"),
            "trial_id": "trial",
            "result_id": "result",
            "domain_id": domain.id,
            "draft": {"active_answers": [], "limitations": [], "override": None},
            "proposed_judgment": Judgment.LOW.value,
            "inactive_questions": [],
            "scientific_pack": SCIENTIFIC_PACK.content_hash,
            "policy_pack": "policy",
        }
        candidate_identity = identity(candidate)
        active_hash = identity({"candidate": candidate_identity, "revision": 1})
        observation = {
            **candidate,
            "identity": candidate_identity,
            "active_hash": active_hash,
            "active_revision": 1,
            "caller": "host",
        }
        write_jsons(
            tmp_path,
            {f"domain-observation-{active_hash.removeprefix('sha256:')}.json": observation},
        )
        state["domains"][f"trial:result:{domain.id}"] = [active_hash]
    write_jsons(tmp_path, {"state.json": state})
    prepared = prepare_trial_finish(
        tmp_path,
        approved,
        TrialFinishCandidate(
            disposition=TrialDisposition.NEEDS_INPUT,
            reason="source_evidence_insufficient",
            missing_facts=("A complete source report is unavailable",),
        ),
        caller="cli:test",
        authority=ReviewAuthority.RESEARCHER,
    )
    assert prepared.synthesis is not None
    assert prepared.transition is not None
    with pytest.raises(ValueError):
        TrialFinishRequest.model_validate({"transition": prepared.transition.model_dump()})
    acknowledgment = acknowledge_trial_finish(tmp_path, prepared.transition, caller="cli:test")
    first = finish_trial(
        tmp_path,
        TrialFinishRequest(transition=prepared.transition, acknowledgment=acknowledgment),
        caller="cli:test",
    )
    second = finish_trial(
        tmp_path,
        TrialFinishRequest(transition=prepared.transition, acknowledgment=acknowledgment),
        caller="cli:test",
    )
    assert second.outcome_ref == first.outcome_ref


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("authority", "host"),
        ("purpose", "proposal"),
        (
            "record",
            {
                "kind": "proposal_review",
                "identity": "sha256:" + "0" * 64,
                "uri": "rob2://detail/proposal_review/sha256:" + "0" * 64,
            },
        ),
        ("caller", "worker:test"),
        ("observed_at", "not-a-time"),
        ("identity", "sha256:" + "0" * 64),
        ("uri", "rob2://detail/review_ack/sha256:" + "0" * 64),
    ),
)
def test_trial_finish_rejects_every_corrupt_ack_field(
    tmp_path: Path, field: str, value: object
) -> None:
    approved = _approved(tmp_path)
    state = {"phase": "assessment", "domains": {}}
    for domain in SCIENTIFIC_PACK.domains:
        candidate = {
            "kind": "domain_candidate",
            "packet": approved.model_dump(mode="json"),
            "trial_id": "trial",
            "result_id": "result",
            "domain_id": domain.id,
            "draft": {"active_answers": [], "limitations": [], "override": None},
            "proposed_judgment": Judgment.LOW.value,
            "inactive_questions": [],
            "scientific_pack": SCIENTIFIC_PACK.content_hash,
            "policy_pack": "policy",
        }
        candidate_identity = identity(candidate)
        active_hash = identity({"candidate": candidate_identity, "revision": 1})
        write_jsons(
            tmp_path,
            {
                f"domain-observation-{active_hash.removeprefix('sha256:')}.json": {
                    **candidate,
                    "identity": candidate_identity,
                    "active_hash": active_hash,
                    "active_revision": 1,
                    "caller": "host",
                }
            },
        )
        state["domains"][f"trial:result:{domain.id}"] = [active_hash]
    write_jsons(tmp_path, {"state.json": state})
    prepared = prepare_trial_finish(
        tmp_path,
        approved,
        TrialFinishCandidate(
            disposition=TrialDisposition.NEEDS_INPUT,
            reason="source_evidence_insufficient",
            missing_facts=("source",),
        ),
        caller="cli:test",
        authority=ReviewAuthority.RESEARCHER,
    )
    assert prepared.transition is not None
    acknowledgment = acknowledge_trial_finish(tmp_path, prepared.transition, caller="cli:test")
    name = f"trial-finish-ack-{acknowledgment.identity.removeprefix('sha256:')}.json"
    raw = read_json(tmp_path, name)
    assert raw is not None
    raw[field] = value
    write_jsons(tmp_path, {name: raw})
    with pytest.raises(ValueError):
        finish_trial(
            tmp_path,
            TrialFinishRequest(transition=prepared.transition, acknowledgment=acknowledgment),
            caller="cli:test",
        )
    transition = read_json(
        tmp_path, f"transition-{prepared.transition.identity.removeprefix('sha256:')}.json"
    )
    assert transition is not None and not transition.get("consumed")
