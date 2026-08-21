from __future__ import annotations

from pathlib import Path

import pymupdf

from rob2_kit.application._state import identity, write_jsons
from rob2_kit.application.contracts import RecordKind, RecordReference, ReviewAuthority
from rob2_kit.application.domains import (
    DomainDraftInput,
    DomainValidationRequest,
    prepare_domain_packet,
    validate_domain_judgment,
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

# ruff: noqa: E501


def _captured(tmp_path: Path) -> RecordReference:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Evidence for every signalling answer.")
    document.save(tmp_path / "article.pdf")
    document.close()
    preflight = preflight_sources(tmp_path, PreflightRequest(roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),)), registry_request=lambda *_: {"status": "not_found"})
    plan = save_intake_plan(tmp_path, preflight.reference, (IntakePlanEntry(candidate_identity=preflight.candidates[0].identity, role="main_article", disposition=SourceDisposition.INCLUDE, criticality=SourceCriticality.REQUIRED),))
    ack = acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST)
    capture_batch(tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=ack))
    approved_identity = identity({"review": "review", "acknowledgment": "ack", "dispositions": (("trial", "pending"),)})
    write_jsons(tmp_path, {"approved_batch.json": {"kind": "approved_batch", "identity": approved_identity, "review": "review", "acknowledgment": "ack", "dispositions": [["trial", "pending"]]}, "state.json": {"phase": "assessment", "domains": {}}})
    return RecordReference(kind=RecordKind.APPROVED_BATCH, identity=approved_identity, uri=f"rob2://detail/approved_batch/{approved_identity}")


def test_domain_validation_is_repair_without_canonical_write(tmp_path: Path) -> None:
    approved = _captured(tmp_path)
    result = validate_domain_judgment(tmp_path, DomainValidationRequest(packet=approved, draft=DomainDraftInput(active_answers=())))
    assert result.outcome == "repair"
    assert not list((tmp_path / ".rob2-kit").glob("domain-candidate-*.json"))


def test_domain_packet_binds_domain_and_is_restart_safe(tmp_path: Path) -> None:
    approved = _captured(tmp_path)
    packet = prepare_domain_packet(tmp_path, approved, trial_id="trial", domain_id="domain:randomization")
    assert packet.kind is RecordKind.APPROVED_WORK_PACKET
    assert packet == prepare_domain_packet(tmp_path, approved, trial_id="trial", domain_id="domain:randomization")
