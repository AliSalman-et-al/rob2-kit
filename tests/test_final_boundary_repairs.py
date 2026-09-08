from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _workspace,
)
from test_assessment_review_gate import _complete_assessment

from rob2_kit.application._state import _commit_records, _identity, _state
from rob2_kit.application.intake import discard_workspace
from rob2_kit.application.trials import request_trial_terminal
from rob2_kit.interfaces.mcp.contracts import (
    SearchHit,
    SearchReceipt,
    output_schema,
)
from rob2_kit.workflow_models import (
    AbandonmentTerminalRequest,
    DomainId,
    DomainLimitationBasis,
    EvidenceHandle,
    Identity,
    NeedsInputTerminalRequest,
    QuestionId,
    SelfCorrectionRevision,
    SourceId,
    TerminalRequestEnvelope,
    TrialDeclaration,
    TrialId,
)


def _all_schema_objects(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    objects: list[dict[str, Any]] = []
    if value.get("type") == "object":
        objects.append(value)
    for child in value.values():
        if isinstance(child, dict):
            objects.extend(_all_schema_objects(child))
        elif isinstance(child, list):
            for item in child:
                objects.extend(_all_schema_objects(item))
    return objects


def test_public_discriminator_tags_are_required() -> None:
    for tool in (
        "prepare_batch",
        "get_status",
        "save_proposal",
        "get_domain_context",
        "save_domain_judgment",
        "request_trial_terminal",
        "finalize_batch",
    ):
        for definition in _all_schema_objects(output_schema(tool)):
            required = set(definition.get("required", ()))
            properties = definition.get("properties", {})
            for tag in ("kind", "form", "disposition"):
                if tag in properties:
                    assert tag in required, (tool, tag, definition)


@pytest.mark.parametrize(
    ("annotation", "valid", "invalid"),
    (
        (Identity, "sha256:" + "a" * 64, "xsha256:" + "a" * 64),
        (SourceId, "source_" + "a" * 64, "source_" + "a" * 64 + "junk"),
        (EvidenceHandle, "eh_" + "a" * 16, "eh_" + "a" * 16 + "junk"),
        (TrialId, "trial_1", "trial/path"),
        (DomainId, "domain:randomization", "domain:randomization/path"),
        (QuestionId, "sq:randomization:sequence", "sq:randomization:sequence/path"),
    ),
)
def test_workflow_identifiers_are_full_string_anchored(
    annotation: Any, valid: str, invalid: str
) -> None:
    assert TypeAdapter(annotation).validate_python(valid) == valid
    with pytest.raises(ValidationError):
        TypeAdapter(annotation).validate_python(invalid)


def test_domain_id_is_closed_to_the_five_canonical_domains() -> None:
    canonical = (
        "domain:randomization",
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    )
    adapter = TypeAdapter(DomainId)
    assert adapter.json_schema()["enum"] == list(canonical)
    for domain_id in canonical:
        assert adapter.validate_python(domain_id) == domain_id
    for domain_id in ("randomization", "domain:unknown"):
        with pytest.raises(ValidationError):
            adapter.validate_python(domain_id)


def test_public_identifier_patterns_are_full_string_anchored() -> None:
    with pytest.raises(ValidationError):
        SearchHit.model_validate(
            {
                "source_id": "xsource_" + "a" * 64,
                "page": 1,
                "preview": "text",
            }
        )
    with pytest.raises(ValidationError):
        SearchReceipt.model_validate(
            {
                "identity": "sha256:" + "a" * 64,
                "handle": "sr_" + "a" * 16 + "junk",
                "trial_id": "trial",
                "query": "term",
                "mode": "all",
            }
        )


@pytest.mark.parametrize("trial_field", ("label", "requested_outcome"))
@pytest.mark.parametrize(
    "model",
    (
        TrialDeclaration,
        DomainLimitationBasis,
        SelfCorrectionRevision,
        NeedsInputTerminalRequest,
        AbandonmentTerminalRequest,
    ),
)
def test_public_mutation_models_reject_whitespace_only_text(model: Any, trial_field: str) -> None:
    if model is TrialDeclaration:
        payload = {
            "id": "trial",
            "label": "Trial",
            "requested_outcome": "outcome",
        }
        payload[trial_field] = " "
    elif model is DomainLimitationBasis:
        payload = {"kind": "limitation", "text": "\t"}
    elif model is SelfCorrectionRevision:
        payload = {"kind": "self_correction", "rationale": "\n"}
    elif model is NeedsInputTerminalRequest:
        payload = {
            "disposition": "needs_input",
            "trial_id": "trial",
            "reason": "reason",
            "missing_facts": ["  "],
        }
    else:
        payload = {
            "disposition": "failed",
            "trial_id": "trial",
            "reason": "reason",
            "facts": ["\t"],
        }
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_terminal_request_cannot_mutate_before_proposal_gate(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    prepared = _call(
        workspace,
        "prepare_batch",
        {
            "requested_outcome": "requested outcome",
            "expected_revision": 0,
        },
    )
    envelope = TerminalRequestEnvelope(
        request=NeedsInputTerminalRequest(
            disposition="needs_input",
            trial_id="trial",
            reason="A required fact is unavailable.",
            missing_facts=("The required fact.",),
        ),
        expected_revision=prepared["head"]["state_revision"],
    )
    with pytest.raises(ValueError, match="approved Proposal Review"):
        request_trial_terminal(workspace, envelope)
    state = _state(workspace)
    assert state["phase"] == "proposal"
    assert state["trial_dispositions"] == {"trial": "pending"}
    assert state.get("terminals", {}) == {}


def test_terminal_request_rejects_rehashed_acknowledgment_basis_tampering(
    tmp_path: Path,
) -> None:
    workspace, _evidence, revision = _assessment_workspace(tmp_path)
    state = _state(workspace)
    acknowledgment = dict(state["proposal_acknowledgment"])
    acknowledgment["workflow_basis"] = int(acknowledgment["workflow_basis"]) + 1
    acknowledgment["identity"] = _identity(
        {key: value for key, value in acknowledgment.items() if key != "identity"}
    )
    state["proposal_acknowledgment"] = acknowledgment
    committed = _commit_records(workspace, state, revision, {})
    envelope = TerminalRequestEnvelope(
        request=NeedsInputTerminalRequest(
            disposition="needs_input",
            trial_id="trial",
            reason="A required fact is unavailable.",
            missing_facts=("The required fact.",),
        ),
        expected_revision=committed["revision"],
    )
    with pytest.raises(ValueError, match="approved Proposal Review"):
        request_trial_terminal(workspace, envelope)
    assert _state(workspace).get("terminals", {}) == {}


def test_new_terminal_request_cannot_replace_ready_assessment(tmp_path: Path) -> None:
    workspace, _evidence, revision = _complete_assessment(tmp_path)
    before = _state(workspace)
    envelope = TerminalRequestEnvelope(
        request=NeedsInputTerminalRequest(
            disposition="needs_input",
            trial_id="trial",
            reason="A required fact is unavailable.",
            missing_facts=("The required fact.",),
        ),
        expected_revision=revision,
    )

    with pytest.raises(ValueError, match="not the current operation"):
        request_trial_terminal(workspace, envelope)
    assert _state(workspace) == before


def test_discarded_identical_run_reuses_domain_checkpoint_content(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    domain_id = "domain:randomization"
    first = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", domain_id, revision, evidence),
    )
    assert first["outcome"] == "success", first
    first_checkpoint = first["data"]["checkpoint"]

    discard_workspace(workspace)
    revision = int(_state(workspace)["revision"])
    prepared = _call(
        workspace,
        "prepare_batch",
        {
            "requested_outcome": "requested outcome",
            "expected_revision": revision,
        },
    )
    assert prepared["outcome"] == "success", prepared
    _read_required_main_reports(workspace)
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    from support.rob2 import _review

    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    second = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", domain_id, revision, evidence),
    )
    assert second["outcome"] == "success", second
    assert second["data"]["checkpoint"] == first_checkpoint
