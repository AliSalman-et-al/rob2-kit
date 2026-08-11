from __future__ import annotations

import pytest

import rob2_kit.evidence as public_evidence
from rob2_kit.application.evidence_navigation import (
    EVIDENCE_NAVIGATION_STATE_VERSION,
    EvidenceNavigationState,
    IncompatibleEvidenceNavigationState,
    decode_v2_historical_navigation_state,
)
from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes
from rob2_kit.evidence.workflow import V2EvidenceWorkflowState


def _historical_state() -> EvidenceNavigationState:
    workflow = V2EvidenceWorkflowState(
        result_id="result:historical",
        domain_id="domain:historical",
        snapshot_hash=canonical_hash({"snapshot": "historical"}),
        search_policy_id="policy:historical-search",
        search_policy_hash=canonical_hash({"policy": "historical-search"}),
    )
    unsigned = EvidenceNavigationState.model_construct(
        state_version=EVIDENCE_NAVIGATION_STATE_VERSION,
        contract_version="2.0.0",
        run_id="run:historical",
        result_id=workflow.result_id,
        domain_id=workflow.domain_id,
        snapshot_hash=workflow.snapshot_hash,
        search_policy_id=workflow.search_policy_id,
        search_policy_hash=workflow.search_policy_hash,
        read_policy_id="policy:historical-read",
        read_policy_hash=canonical_hash({"policy": "historical-read"}),
        workflow=workflow,
        content_hash="",
    )
    payload = unsigned.model_dump(mode="json")
    payload["content_hash"] = None
    return EvidenceNavigationState.model_validate(
        payload | {"content_hash": canonical_hash(payload)}
    )


def test_historical_v2_navigation_decodes_without_upgrading() -> None:
    state = _historical_state()

    decoded = decode_v2_historical_navigation_state(canonical_json_bytes(state))

    assert decoded == state
    assert decoded.state_version == EVIDENCE_NAVIGATION_STATE_VERSION
    assert decoded.contract_version == "2.0.0"


def test_historical_decoder_rejects_tampered_content() -> None:
    state = _historical_state().model_dump(mode="json")
    state["snapshot_hash"] = canonical_hash({"snapshot": "tampered"})

    with pytest.raises(IncompatibleEvidenceNavigationState):
        decode_v2_historical_navigation_state(canonical_json_bytes(state))


def test_historical_v2_workflow_types_are_not_public_evidence_exports() -> None:
    assert "SearchPassKind" not in public_evidence.__all__
    assert not hasattr(public_evidence, "SearchPassKind")
