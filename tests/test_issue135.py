"""review_revisions/passages freeze regression (#135).

`submit_domain_evidence`'s retained-candidate check for `review_revisions`
was computed from `request.passages` at every call site, but that field is
zeroed before the check runs -- once deliberately in the pre-check pass, and
permanently once `_resolve_evidence_passages` materializes claims. This made
the append-only review-then-freeze contract described in the tool's own
docstring unsatisfiable for any input. See ADR-0012 for the accompanying
legacy-shape removal.
"""

import hashlib
from pathlib import Path

from rob2_kit.application.contracts import (
    ContinueRunRequest,
    SubmitDomainEvidenceRequest,
    WorkflowCondition,
)
from rob2_kit.evidence.search import EvidenceSearchIndex
from tests.test_input_reconciliation import (
    StructuredPassageParser,
    _classify_current_sources,
    _config,
    _location_handle_for,
    _prepare_confirm,
    _result,
    _review_revision,
)
from tests.test_issue127 import _complete_real_search
from tests.test_mcp_tracer import DOMAINS


def _claim_id(
    run_id: str,
    result_id: str,
    domain_id: str,
    question_id: str,
    candidate_id: str,
    unit_id: str,
    span_start: int,
    span_end: int,
    claim_type: str,
) -> str:
    """Mirror RunEngine._resolve_evidence_passages' deterministic claim identity.

    A caller must precompute this to link a passage's SUPERSEDED disposition
    to a sibling passage's claim within the same submission, since neither
    claim exists yet when the request is built.
    """
    suffix = hashlib.sha256(
        "|".join(
            (
                run_id,
                result_id,
                domain_id,
                question_id,
                candidate_id,
                unit_id,
                str(span_start),
                str(span_end),
                claim_type,
            )
        ).encode()
    ).hexdigest()[:24]
    return f"evidence-claim:{suffix}"


def test_review_revisions_plus_matching_passages_freeze_is_accepted(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "issue135-rr"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:issue135-rr", "trial:issue135-rr")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit_id = next(iter(index.unit_ids()))
    unit = index.read_unit(unit_id)

    _complete_real_search(engine, run_id, work, DOMAINS["domain:randomization"])
    question_id = DOMAINS["domain:randomization"][0]
    location_handle = _location_handle_for(engine, run_id, work, question_id, unit_id)

    response = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue135-review-revisions",
            result_id=work.result_id,
            domain_id="domain:randomization",
            passages=(
                {
                    "unit_id": unit_id,
                    "span_start": 0,
                    "span_end": len(unit.text),
                    "claim_type": "claim-type:randomization-method",
                    "question_ids": (question_id,),
                },
            ),
            review_revisions=(
                _review_revision(
                    candidate_id=unit_id,
                    result_id=work.result_id,
                    domain_id="domain:randomization",
                    question_id=question_id,
                    location_handle=location_handle,
                    span_start=0,
                    span_end=len(unit.text),
                    entity_suffix="issue135-1",
                ),
            ),
        )
    )
    assert response.condition is WorkflowCondition.ACCEPTED, response.error


def test_review_revisions_alone_without_passages_is_rejected_for_missing_candidates(
    tmp_path: Path,
) -> None:
    """review_revisions with no passages at all still requires a retained candidate."""
    trial = tmp_path / "input" / "issue135-rr-alone"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:issue135-rr-alone", "trial:issue135-rr-alone")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit_id = next(iter(index.unit_ids()))
    unit = index.read_unit(unit_id)

    _complete_real_search(engine, run_id, work, DOMAINS["domain:randomization"])
    question_id = DOMAINS["domain:randomization"][0]

    response = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue135-review-revisions-alone",
            result_id=work.result_id,
            domain_id="domain:randomization",
            review_revisions=(
                _review_revision(
                    candidate_id=unit_id,
                    result_id=work.result_id,
                    domain_id="domain:randomization",
                    question_id=question_id,
                    location_handle=unit_id,
                    span_start=0,
                    span_end=len(unit.text),
                    entity_suffix="issue135-2",
                ),
            ),
        )
    )
    assert response.condition is WorkflowCondition.RUN_BLOCKED
    assert response.error is not None
    detail = response.error.detail
    assert unit_id in detail


def test_passages_based_superseded_disposition_with_matching_conflicts_is_accepted(
    tmp_path: Path,
) -> None:
    """A passages submission can carry a SUPERSEDED disposition linked via conflicts.

    Regression for the gap flagged in ADR-0012: `passages` and `conflicts`
    used to be mutually exclusive, which made a SUPERSEDED disposition
    structurally unreachable from the passages path -- only the legacy
    items/candidate_dispositions branch could supply conflicts.
    """
    trial = tmp_path / "input" / "issue135-superseded"
    trial.mkdir(parents=True)
    text = (
        "primary randomization sequence generation was computer implemented for "
        "allocation. randomization concealment used sealed opaque sequentially "
        "numbered envelopes prepared offsite."
    )
    (trial / "report.pdf").write_bytes(text.encode())
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result("result:issue135-superseded", "trial:issue135-superseded")),
        parser=StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work is not None
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit_id = next(iter(index.unit_ids()))
    unit = index.read_unit(unit_id)

    _complete_real_search(engine, run_id, work, DOMAINS["domain:randomization"])
    question_id = DOMAINS["domain:randomization"][0]
    location_handle = _location_handle_for(engine, run_id, work, question_id, unit_id)

    domain_id = "domain:randomization"
    mid = len(unit.text) // 2
    replacement_span = (0, mid)
    superseded_span = (mid, len(unit.text))
    replacement_claim_type = "claim-type:randomization-method"
    superseded_claim_type = "claim-type:randomization-method"

    replacement_claim_id = _claim_id(
        run_id,
        work.result_id,
        domain_id,
        question_id,
        "candidate:issue135-superseded-replacement",
        unit_id,
        *replacement_span,
        replacement_claim_type,
    )
    superseded_claim_id = _claim_id(
        run_id,
        work.result_id,
        domain_id,
        question_id,
        "candidate:issue135-superseded-original",
        unit_id,
        *superseded_span,
        superseded_claim_type,
    )

    response = engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="2.0.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key="idempotency:issue135-superseded",
            result_id=work.result_id,
            domain_id=domain_id,
            passages=(
                {
                    "unit_id": unit_id,
                    "span_start": replacement_span[0],
                    "span_end": replacement_span[1],
                    "claim_type": replacement_claim_type,
                    "candidate_id": "candidate:issue135-superseded-replacement",
                    "question_ids": (question_id,),
                },
                {
                    "unit_id": unit_id,
                    "span_start": superseded_span[0],
                    "span_end": superseded_span[1],
                    "claim_type": superseded_claim_type,
                    "candidate_id": "candidate:issue135-superseded-original",
                    "question_ids": (question_id,),
                    "disposition": "superseded",
                    "basis": "later passage supersedes this earlier phrasing",
                    "superseded_by": replacement_claim_id,
                },
            ),
            conflicts=((replacement_claim_id, superseded_claim_id),),
            review_revisions=(
                _review_revision(
                    candidate_id="candidate:issue135-superseded-replacement",
                    result_id=work.result_id,
                    domain_id=domain_id,
                    question_id=question_id,
                    location_handle=location_handle,
                    span_start=replacement_span[0],
                    span_end=replacement_span[1],
                    entity_suffix="issue135-superseded-replacement",
                ),
                _review_revision(
                    candidate_id="candidate:issue135-superseded-original",
                    result_id=work.result_id,
                    domain_id=domain_id,
                    question_id=question_id,
                    location_handle=location_handle,
                    span_start=superseded_span[0],
                    span_end=superseded_span[1],
                    entity_suffix="issue135-superseded-original",
                ),
            ),
        )
    )
    assert response.condition is WorkflowCondition.ACCEPTED, response.error
