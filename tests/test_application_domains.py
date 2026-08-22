from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from rob2_kit.application._state import identity, read_json, write_jsons
from rob2_kit.application.contracts import (
    RecordKind,
    RecordReference,
    ReviewAuthority,
    ValidateDomainJudgmentContinuation,
)
from rob2_kit.application.domains import (
    ApplicationWorkPacket,
    DomainAnswerInput,
    DomainDraftInput,
    DomainEvidenceUseInput,
    DomainValidationRequest,
    commit_domain_judgment,
    prepare_domain_packet,
    validate_domain_judgment,
)
from rob2_kit.application.evidence import (
    EvidenceRetrievalRequest,
    ManualSelectionRequest,
    retrieve_evidence,
)
from rob2_kit.application.intake import (
    CaptureRequest,
    IntakePlanEntry,
    SourceCriticality,
    SourceDisposition,
    acknowledge_intake,
    capture_batch,
    save_intake_plan,
)
from rob2_kit.application.preflight import AuthorizedSourceRoot, PreflightRequest, preflight_sources
from rob2_kit.judgment_models import EvidenceRelationship
from rob2_kit.models import Answer
from rob2_kit.packs import SCIENTIFIC_PACK

# ruff: noqa: E501


def _captured(tmp_path: Path) -> RecordReference:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Evidence for every signalling answer.")
    document.save(tmp_path / "article.pdf")
    document.close()
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),)),
        registry_request=lambda *_: {"status": "not_found"},
    )
    plan = save_intake_plan(
        tmp_path,
        preflight.reference,
        (
            IntakePlanEntry(
                candidate_identity=preflight.candidates[0].identity,
                role="main_article",
                disposition=SourceDisposition.INCLUDE,
                criticality=SourceCriticality.REQUIRED,
            ),
        ),
    )
    ack = acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST)
    capture_batch(tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=ack))
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


def test_domain_validation_is_repair_without_canonical_write(tmp_path: Path) -> None:
    approved = _captured(tmp_path)
    result = validate_domain_judgment(
        tmp_path,
        DomainValidationRequest(packet=approved, draft=DomainDraftInput(active_answers=())),
    )
    assert result.outcome == "repair"
    state = read_json(tmp_path, "state.json")
    assert state is not None and isinstance(state.get("work_packet_identity"), str)
    assert not list((tmp_path / ".rob2-kit").glob("domain-candidate-*.json"))


def test_approved_batch_bootstrap_is_rejected_after_domain_checkpoint(tmp_path: Path) -> None:
    approved = _captured(tmp_path)
    state = read_json(tmp_path, "state.json")
    assert state is not None
    state["domains"] = {"trial:result:domain:randomization": ["sha256:" + "2" * 64]}
    write_jsons(tmp_path, {"state.json": state})

    result = validate_domain_judgment(
        tmp_path,
        DomainValidationRequest(packet=approved, draft=DomainDraftInput(active_answers=())),
    )

    assert result.outcome == "condition"
    assert result.code == "packet_unavailable"
    assert "bootstrap" in result.detail
    updated = read_json(tmp_path, "state.json")
    assert updated == state


def test_domain_packet_binds_domain_and_is_restart_safe(tmp_path: Path) -> None:
    approved = _captured(tmp_path)
    packet = prepare_domain_packet(
        tmp_path, approved, trial_id="trial", domain_id="domain:randomization"
    )
    assert packet.kind is RecordKind.APPROVED_WORK_PACKET
    assert packet == prepare_domain_packet(
        tmp_path, approved, trial_id="trial", domain_id="domain:randomization"
    )


def test_domain_packets_expose_canonical_question_guidance(tmp_path: Path) -> None:
    approved = _captured(tmp_path)
    for index, domain in enumerate(SCIENTIFIC_PACK.domains):
        state = read_json(tmp_path, "state.json")
        assert state is not None
        state["domains"] = {
            f"trial:result:{earlier.id}": [identity({"checkpoint": earlier.id})]
            for earlier in SCIENTIFIC_PACK.domains[:index]
        }
        write_jsons(tmp_path, {"state.json": state})
        packet = prepare_domain_packet(tmp_path, approved, trial_id="trial", domain_id=domain.id)
        raw = read_json(tmp_path, f"domain-packet-{packet.identity.removeprefix('sha256:')}.json")
        assert raw is not None
        expected = tuple(
            question for question in SCIENTIFIC_PACK.questions if question.domain_id == domain.id
        )
        expected_guidance = [
            {
                "id": question.id,
                "wording": question.wording,
                "allowed_answers": [answer.value for answer in question.allowed_answers],
                "activation": question.activation.model_dump(mode="json"),
            }
            for question in expected
        ]
        assert raw["question_guidance"] == expected_guidance
        assert (
            ApplicationWorkPacket.model_validate(raw).model_dump(mode="json")["question_guidance"]
            == expected_guidance
        )
        json.dumps(raw, sort_keys=True)
        assert raw["active_question_ids"] == [question.id for question in expected]
        assert raw["allowed_question_ids"] == [question.id for question in expected]


def test_domain_packet_identity_covers_question_guidance(tmp_path: Path) -> None:
    approved = _captured(tmp_path)
    packet = prepare_domain_packet(
        tmp_path, approved, trial_id="trial", domain_id="domain:randomization"
    )
    raw = read_json(tmp_path, f"domain-packet-{packet.identity.removeprefix('sha256:')}.json")
    assert raw is not None
    changed = {**raw, "question_guidance": raw["question_guidance"][1:]}
    assert (
        identity({key: value for key, value in changed.items() if key != "identity"})
        != packet.identity
    )


def test_domain_packet_prior_hashes_use_full_pack_ordered_domain_ids(tmp_path: Path) -> None:
    approved = _captured(tmp_path)
    randomization_hash = identity({"checkpoint": "randomization"})
    deviations_hash = identity({"checkpoint": "deviations"})
    state = read_json(tmp_path, "state.json")
    assert state is not None
    # Deliberately insert these in reverse order: packet order comes from the
    # scientific pack, not from state mapping order or lexical sorting.
    state["domains"] = {
        "trial:result:domain:deviations": [deviations_hash],
        "trial:result:domain:randomization": [randomization_hash],
    }
    write_jsons(tmp_path, {"state.json": state})

    packet = prepare_domain_packet(tmp_path, approved, trial_id="trial", domain_id="domain:missing")
    raw = read_json(tmp_path, f"domain-packet-{packet.identity.removeprefix('sha256:')}.json")
    assert raw is not None
    assert raw["prior_domain_hashes"] == [
        ["domain:randomization", randomization_hash],
        ["domain:deviations", deviations_hash],
    ]


def test_domain_commit_rejects_changed_earlier_checkpoint_basis(tmp_path: Path) -> None:
    _packet, evidence, validated = _validated_randomization(tmp_path)
    first = commit_domain_judgment(tmp_path, validated.transition)
    assert isinstance(first.next_action, ValidateDomainJudgmentContinuation)
    later_packet = first.next_action.packet
    draft = DomainDraftInput(
        active_answers=tuple(
            DomainAnswerInput(
                question_id=question_id,
                answer=answer,
                rationale="The captured trial report supports this deterministic answer.",
                evidence_uses=(
                    DomainEvidenceUseInput(
                        relationship=EvidenceRelationship.SUPPORTING,
                        claim="The captured trial report supports this answer.",
                        rationale="The exact evidence record is in the trial scope.",
                        evidence=(evidence,),
                    ),
                ),
            )
            for question_id, answer in (
                ("sq:deviations:participants-aware", Answer.NO),
                ("sq:deviations:personnel-aware", Answer.NO),
                ("sq:deviations:appropriate-analysis", Answer.YES),
            )
        )
    )
    later = validate_domain_judgment(
        tmp_path, DomainValidationRequest(packet=later_packet, draft=draft)
    )
    assert later.outcome == "success"
    state = read_json(tmp_path, "state.json")
    assert state is not None
    state["domains"]["trial:result:domain:randomization"] = [identity({"checkpoint": "R2"})]
    write_jsons(tmp_path, {"state.json": state})
    state_before = read_json(tmp_path, "state.json")

    with pytest.raises(ValueError, match="concurrent_domain_conflict"):
        commit_domain_judgment(tmp_path, later.transition)

    assert read_json(tmp_path, "state.json") == state_before
    assert not list((tmp_path / ".rob2-kit").glob("domain-observation-*.json"))[1:]
    transition_raw = read_json(
        tmp_path, f"transition-{later.transition.identity.removeprefix('sha256:')}.json"
    )
    assert transition_raw is not None and not transition_raw.get("consumed")


def test_domain_packet_catalog_binds_retained_evidence(tmp_path: Path) -> None:
    approved = _captured(tmp_path)
    before = prepare_domain_packet(
        tmp_path, approved, trial_id="trial", domain_id="domain:randomization"
    )
    minted = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=0,
                    end=8,
                    quote="Evidence",
                ),
            ),
        ),
    )
    after = prepare_domain_packet(
        tmp_path, approved, trial_id="trial", domain_id="domain:randomization"
    )
    assert after != before
    raw = read_json(tmp_path, f"domain-packet-{after.identity.removeprefix('sha256:')}.json")
    assert raw is not None
    assert (
        raw["reusable_evidence"]["entries"][0]["evidence"]["identity"]
        == minted.evidence[0].identity
    )


def _validated_randomization(tmp_path: Path):
    approved = _captured(tmp_path)
    packet = prepare_domain_packet(
        tmp_path, approved, trial_id="trial", domain_id="domain:randomization"
    )
    evidence = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=0,
                    end=8,
                    quote="Evidence",
                ),
            ),
        ),
    ).evidence[0]
    draft = DomainDraftInput(
        active_answers=tuple(
            DomainAnswerInput(
                question_id=question_id,
                answer=answer,
                rationale="The captured trial report supports this deterministic answer.",
                evidence_uses=(
                    DomainEvidenceUseInput(
                        relationship=EvidenceRelationship.SUPPORTING,
                        claim="The captured trial report supports this answer.",
                        rationale="The exact evidence record is in the trial scope.",
                        evidence=(evidence,),
                    ),
                ),
            )
            for question_id, answer in (
                ("sq:randomization:sequence", Answer.YES),
                ("sq:randomization:concealment", Answer.YES),
                ("sq:randomization:baseline-imbalance", Answer.NO),
            )
        )
    )
    validated = validate_domain_judgment(
        tmp_path, DomainValidationRequest(packet=packet, draft=draft)
    )
    assert validated.outcome == "success"
    return packet, evidence, validated


def test_domain_validation_requires_pack_ordered_active_answers(tmp_path: Path) -> None:
    approved = _captured(tmp_path)
    packet = prepare_domain_packet(
        tmp_path, approved, trial_id="trial", domain_id="domain:randomization"
    )
    evidence = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=0,
                    end=8,
                    quote="Evidence",
                ),
            ),
        ),
    ).evidence[0]
    answers = tuple(
        DomainAnswerInput(
            question_id=question_id,
            answer=answer,
            rationale="The captured trial report supports this deterministic answer.",
            evidence_uses=(
                DomainEvidenceUseInput(
                    relationship=EvidenceRelationship.SUPPORTING,
                    claim="The captured trial report supports this answer.",
                    rationale="The exact evidence record is in the trial scope.",
                    evidence=(evidence,),
                ),
            ),
        )
        for question_id, answer in (
            ("sq:randomization:sequence", Answer.YES),
            ("sq:randomization:concealment", Answer.YES),
            ("sq:randomization:baseline-imbalance", Answer.NO),
        )
    )

    reversed_result = validate_domain_judgment(
        tmp_path,
        DomainValidationRequest(
            packet=packet, draft=DomainDraftInput(active_answers=tuple(reversed(answers)))
        ),
    )
    assert reversed_result.outcome == "repair"
    assert any(
        repair.pointer == "/active_answers"
        and repair.code == "order"
        and "packet/scientific-pack order" in repair.detail
        for repair in reversed_result.repairs
    )

    canonical_result = validate_domain_judgment(
        tmp_path,
        DomainValidationRequest(packet=packet, draft=DomainDraftInput(active_answers=answers)),
    )
    assert canonical_result.outcome == "success"


def test_domain_commit_rejects_corrupt_packet_before_writing_state(tmp_path: Path) -> None:
    packet, _evidence, validated = _validated_randomization(tmp_path)
    state_before = read_json(tmp_path, "state.json")
    packet_name = f"domain-packet-{packet.identity.removeprefix('sha256:')}.json"
    packet_raw = read_json(tmp_path, packet_name)
    assert packet_raw is not None
    packet_raw["prior_domain_hashes"] = [["domain:randomization", "sha256:" + "0" * 64]]
    write_jsons(tmp_path, {packet_name: packet_raw})

    with pytest.raises(ValueError, match="identity"):
        commit_domain_judgment(tmp_path, validated.transition)

    assert read_json(tmp_path, "state.json") == state_before
    assert not list((tmp_path / ".rob2-kit").glob("domain-observation-*.json"))
    assert not list((tmp_path / ".rob2-kit").glob("domain-commit-*.json"))
    transition_raw = read_json(
        tmp_path, f"transition-{validated.transition.identity.removeprefix('sha256:')}.json"
    )
    assert transition_raw is not None and not transition_raw.get("consumed")


def test_domain_commit_prebuilds_next_packet_before_consuming_transition(tmp_path: Path) -> None:
    _packet, evidence, validated = _validated_randomization(tmp_path)
    evidence_name = f"evidence-{evidence.identity.removeprefix('sha256:')}.json"
    evidence_raw = read_json(tmp_path, evidence_name)
    assert evidence_raw is not None
    evidence_raw["quote"] = "Corrupt!"
    write_jsons(tmp_path, {evidence_name: evidence_raw})

    state_before = read_json(tmp_path, "state.json")
    packets_before = sorted(
        path.name for path in (tmp_path / ".rob2-kit").glob("domain-packet-*.json")
    )
    with pytest.raises(ValueError, match="Evidence"):
        commit_domain_judgment(tmp_path, validated.transition)

    assert read_json(tmp_path, "state.json") == state_before
    assert (
        sorted(path.name for path in (tmp_path / ".rob2-kit").glob("domain-packet-*.json"))
        == packets_before
    )
    assert not list((tmp_path / ".rob2-kit").glob("domain-observation-*.json"))
    assert not list((tmp_path / ".rob2-kit").glob("domain-commit-*.json"))
    transition_raw = read_json(
        tmp_path, f"transition-{validated.transition.identity.removeprefix('sha256:')}.json"
    )
    assert transition_raw is not None and not transition_raw.get("consumed")
