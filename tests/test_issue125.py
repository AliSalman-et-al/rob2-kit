"""Regressions for GitHub #125: evidence tool schemas are not self-discoverable.

Covers the query envelope/seed_family placement papercut, batched validation
across the retrieval and submission boundaries, and the retired
signed-cursor codec (ADR-0011). See docs/adr/0011-*.md for the design.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from rob2_kit.application.contracts import (
    ContinueRunRequest,
    RunProposalSelection,
    SearchEvidenceRequest,
    SearchQuery,
    SubmitDomainEvidenceRequest,
    SubmitSourceRoleReviewRequest,
    WorkflowCondition,
)
from rob2_kit.evidence.errors import (
    FieldViolation,
    invalid_request_from_validation,
)
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    DocumentZone,
)

HASH = "sha256:" + "1" * 64


def _unit(unit_id: str, text: str) -> CanonicalEvidenceUnit:
    return CanonicalEvidenceUnit(
        unit_id=unit_id,
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report",
        page=1,
        kind=CanonicalUnitKind.PARAGRAPH,
        text=text,
        spatial=(10, 10, 200, 30),
        document_zone=DocumentZone.METHODS,
    )



def test_seed_family_nested_in_query_gets_a_top_level_field_hint() -> None:
    with pytest.raises(ValidationError) as excinfo:
        SearchQuery.model_validate({"terms": ["allocation"], "seed_family": "seed:a"})

    failure = invalid_request_from_validation(excinfo.value, sibling_model=SearchEvidenceRequest)

    assert failure.field == "seed_family"
    assert "did you mean the top-level `seed_family` field" in failure.message


def test_hint_is_absent_without_a_matching_sibling_field() -> None:
    with pytest.raises(ValidationError) as excinfo:
        SearchQuery.model_validate({"terms": ["allocation"], "bogus_field": "x"})

    failure = invalid_request_from_validation(excinfo.value, sibling_model=SearchEvidenceRequest)

    assert "did you mean" not in failure.message


def test_multiple_pydantic_errors_are_all_reported_not_just_the_first() -> None:
    with pytest.raises(ValidationError) as excinfo:
        SearchEvidenceRequest.model_validate(
            {
                "run_id": "",
                "work_token": "not-a-work-token",
                "query": {"terms": ["allocation"]},
                "sq_id": "",
            }
        )

    failure = invalid_request_from_validation(excinfo.value, sibling_model=SearchEvidenceRequest)

    assert len(failure.violations) > 1
    assert all(isinstance(violation, FieldViolation) for violation in failure.violations)


def test_source_role_review_reports_unissued_and_missing_sources_together(
    tmp_path: Path,
) -> None:
    """A single bad submission surfaces both mistakes, not one-at-a-time (#125)."""
    from rob2_kit.application.contracts import ContinueRunRequest, PrepareRunRequest, RunOperation
    from rob2_kit.application.run_engine import RunEngine
    from tests.test_input_reconciliation import _config, _result
    from tests.test_run_proposal import StubParser

    trial_dir = tmp_path / "input" / "trial-a"
    trial_dir.mkdir(parents=True)
    (trial_dir / "report.pdf").write_bytes(b"report text mentions randomization")
    (trial_dir / "protocol.pdf").write_bytes(b"protocol text mentions randomization")

    import yaml

    config = _config(_result("result:trial-a-mortality", "trial:trial-a"))
    (tmp_path / "rob2.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    engine = RunEngine(parser=StubParser())
    prepared = engine.prepare_run(PrepareRunRequest(project_root=tmp_path, authorized=True))
    assert prepared.proposal is not None
    review_work = engine.continue_run(ContinueRunRequest(run_id=prepared.run_id)).work_item
    assert review_work is not None
    assert review_work.operation is RunOperation.SUBMIT_SOURCE_ROLE_REVIEW
    candidates = prepared.proposal.source_role_candidates
    assert len(candidates) >= 2

    # Omit one issued source (missing) and include one that was never issued
    # (unissued) in the same submission.
    kept = candidates[:-1]
    response = engine.submit_source_role_review(
        SubmitSourceRoleReviewRequest(
            contract_version="1.0.0",
            run_id=prepared.run_id,
            work_token=review_work.work_token,
            idempotency_key="idempotency:issue125-source-review",
            selections=tuple(
                RunProposalSelection(
                    trial_id=candidate.trial_id, source_id=candidate.source_id, accepted=True
                )
                for candidate in kept
            )
            + (
                RunProposalSelection(
                    trial_id=kept[0].trial_id, source_id="source:never-issued", accepted=True
                ),
            ),
        )
    )

    assert response.condition is WorkflowCondition.RUN_BLOCKED
    assert response.error is not None
    codes_and_details = {violation.detail for violation in response.error.violations}
    assert any("unissued" in detail for detail in codes_and_details)
    assert any("every inventory-ready source" in detail for detail in codes_and_details)
    assert len(response.error.violations) == 2


def test_domain_evidence_submission_reports_every_violation_together(tmp_path: Path) -> None:
    """Two independent request-shape mistakes surface in one response (#125)."""
    from tests.test_input_reconciliation import _config, _prepare_confirm, _result

    trial = tmp_path / "input" / "issue125-domain-evidence"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report text mentions randomization")

    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(
            _result("result:issue125-domain-evidence", "trial:issue125-domain-evidence")
        ),
    )
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None

    # Two independent mistakes at once: coverage_limitations only makes sense
    # with complete_with_limitations/incomplete (not complete), and an
    # otherwise-empty submission fails the non-empty requirement too.
    response = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue125-domain-evidence",
            result_id=work.result_id,
            domain_id=work.domain_id,
            coverage_state="complete",
            coverage_limitations=["a residual limitation"],
        )
    )

    assert response.condition is WorkflowCondition.RUN_BLOCKED
    assert response.error is not None
    assert len(response.error.violations) >= 2
    details = {violation.detail for violation in response.error.violations}
    assert any("coverage limitations require" in detail for detail in details)
    assert any("must include real passages" in detail for detail in details)


def test_domain_evidence_conflicts_are_still_validated_after_batching(tmp_path: Path) -> None:
    """Regression: batching must not turn the trailing conflicts checks into dead code."""
    from tests.test_input_reconciliation import _config, _prepare_confirm, _result

    trial = tmp_path / "input" / "issue125-conflicts"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"report text mentions randomization")

    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:issue125-conflicts", "trial:issue125-conflicts")),
    )
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None

    response = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue125-conflicts",
            result_id=work.result_id,
            domain_id=work.domain_id,
            coverage_state="incomplete",
            coverage_limitations=["a residual limitation"],
            conflicts=[["claim:only-one-item"]],
        )
    )

    assert response.condition is WorkflowCondition.RUN_BLOCKED
    assert response.error is not None
    details = {violation.detail for violation in response.error.violations}
    assert any("source conflicts must bind at least two" in detail for detail in details)
