"""Production regression coverage for receipt-bound reviewed Evidence."""

import json
from pathlib import Path

import pytest

from rob2_kit.application.contracts import ContinueRunRequest, EvidencePassageInput, SubmitDomainEvidenceRequest
from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.canonical import sha256_digest
from rob2_kit.domain.evidence import (
    EvidenceBundle,
    EvidenceClaim,
    EvidenceReviewRevision,
    ReviewedEvidenceFragment,
)
from rob2_kit.evidence.errors import StaleCursor, UnknownCursor
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceSearchIndex,
    ReadContextMode,
    SearchQuery,
)
from rob2_kit.ingestion.project import PageExtraction, PageTextItem, ParserResult
from tests.test_input_reconciliation import (
    DOMAINS, StructuredPassageParser, _classify_current_sources, _complete_passage_receipts,
    _config, _location_handle_for, _prepare_confirm, _result, _review_revision,
)


def _freeze(tmp_path: Path):
    trial = tmp_path / "input" / "issue151"; trial.mkdir(parents=True); (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(tmp_path, config=_config(_result("result:issue151", "trial:issue151")), parser=StructuredPassageParser())
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item; assert work
    unit = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3").read_unit(next(iter(EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3").unit_ids()))); sq = DOMAINS["domain:randomization"][0]
    _complete_passage_receipts(engine, run_id, work, unit_id=unit.unit_id)
    receipt = _location_handle_for(engine, run_id, work, sq, unit.unit_id)
    response = engine.submit_domain_evidence(SubmitDomainEvidenceRequest(contract_version="1.1.0", run_id=run_id, work_token=work.work_token, idempotency_key="idempotency:issue151", result_id="result:issue151", domain_id="domain:randomization", passages=(EvidencePassageInput(unit_id=unit.unit_id, span_start=0, span_end=len(unit.text), claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(sq,)),), review_revisions=(_review_revision(candidate_id=unit.unit_id, result_id="result:issue151", domain_id="domain:randomization", question_id=sq, location_handle=receipt, span_start=0, span_end=len(unit.text), entity_suffix="issue151"),)))
    assert response.committed
    return engine, run_id, response, sq


def _setup(tmp_path: Path, *, parser=None, suffix: str = "graph"):
    trial = tmp_path / "input" / suffix
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(b"primary")
    engine, run_id = _prepare_confirm(
        tmp_path,
        config=_config(_result(f"result:{suffix}", f"trial:{suffix}")),
        parser=parser or StructuredPassageParser(),
    )
    _classify_current_sources(engine, run_id)
    work = engine.continue_run(ContinueRunRequest(run_id=run_id)).work_item
    assert work
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    unit = index.read_unit(next(iter(index.unit_ids())))
    _complete_passage_receipts(engine, run_id, work, unit_id=unit.unit_id)
    return engine, run_id, work, unit


def _submit(
    engine, run_id: str, work, *, suffix: str, passages, reviews, **request_updates
):
    return engine.submit_domain_evidence(
        SubmitDomainEvidenceRequest(
            contract_version="1.1.0",
            run_id=run_id,
            work_token=work.work_token,
            idempotency_key=f"idempotency:issue151:{suffix}",
            result_id=f"result:{suffix}",
            domain_id="domain:randomization",
            passages=tuple(passages),
            review_revisions=tuple(reviews),
            **request_updates,
        )
    )


class _TwoQuestionParser:
    """Real parser fixture with one source-authored candidate for two SQs."""

    name = "issue151-two-question"
    version = "1"

    def parse(self, data: bytes, *, ocr_enabled: bool, target_pages=None) -> ParserResult:
        text = data.decode()
        return ParserResult(
            pages=(
                PageExtraction(
                    page_number=1,
                    width=612,
                    height=792,
                    text=text,
                    markdown=text,
                    text_items=(
                        PageTextItem(
                            text=text,
                            x=10,
                            y=20,
                            width=200,
                            height=12,
                            unit_kind="paragraph",
                            document_zone="main",
                            domain_id="domain:randomization",
                            question_ids=DOMAINS["domain:randomization"][:2],
                        ),
                    ),
                ),
            ),
            raw_output=data,
        )


def test_unlabelled_parser_reviewed_active_span_qualifies_for_answer(tmp_path: Path):
    engine, run_id, response, sq = _freeze(tmp_path)
    assert response.condition.value == "accepted"
    assert all(item.question_id != sq or item.reason.value != "unresolvable_evidence" for item in engine._evidence_insufficiencies(engine._bound_ledger(run_id), run_id, "result:issue151", {sq: "yes"}))


def test_question_bundle_contains_only_direct_authorizing_review(tmp_path: Path):
    engine, run_id, response, sq = _freeze(tmp_path); ledger = engine._bound_ledger(run_id)
    bundles = [EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash)) for ref in response.evidence_bundles]
    bundle = next(item for item in bundles if item.sq_id == sq); claim = EvidenceClaim.model_validate_json(ledger.artifacts.read(bundle.items[0].content_hash)); review = EvidenceReviewRevision.model_validate_json(ledger.artifacts.read(claim.authorizing_review.content_hash))
    assert bundle.review_revisions == (claim.authorizing_review,) and review.sq_id == sq and any(span.span_id == claim.review_span_id for span in review.spans)
    assert all(not item.review_revisions for item in bundles if item.sq_id != sq)


@pytest.mark.parametrize("tamper", ("span", "review_hash"))
def test_tampered_or_missing_review_span_binding_is_unresolvable(tmp_path: Path, monkeypatch, tamper):
    engine, run_id, response, sq = _freeze(tmp_path); ledger = engine._bound_ledger(run_id); original = ledger.artifacts.read
    claim_ref = next(ref for ref in next(bundle for bundle in [EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash)) for ref in response.evidence_bundles] if bundle.sq_id == sq).items)
    def read(hash):
        payload = original(hash)
        if hash == claim_ref.content_hash:
            data = json.loads(payload)
            if tamper == "span":
                data["review_span_id"] = "review-span:missing"
            else:
                data["authorizing_review"]["content_hash"] = "sha256:" + "0" * 64
            return json.dumps(data).encode()
        return payload
    monkeypatch.setattr(ledger.artifacts, "read", read)
    failures = engine._evidence_insufficiencies(ledger, run_id, "result:issue151", {sq: "yes"})
    assert any(item.question_id == sq and item.reason.value == "unresolvable_evidence" for item in failures)


def test_superseded_authorizing_review_is_stale_evidence_dependency(tmp_path: Path):
    engine, run_id, response, sq = _freeze(tmp_path)
    ledger = engine._bound_ledger(run_id)
    bundle = next(
        EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash))
        for ref in response.evidence_bundles
        if EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash)).sq_id == sq
    )
    claim = EvidenceClaim.model_validate_json(ledger.artifacts.read(bundle.items[0].content_hash))
    review = EvidenceReviewRevision.model_validate_json(
        ledger.artifacts.read(claim.authorizing_review.content_hash)
    )
    replacement = review.model_copy(update={"revision_id": "revision:issue151:review:2"})
    engine._commit_frozen_artifact(
        ledger,
        scope="result:issue151",
        operation="operation:test-review-supersession",
        operation_key="test:issue151:review-supersession",
        entity_id=review.entity_id,
        revision_id=replacement.revision_id,
        artifact=replacement,
        actor=replacement.actor,
    )
    failures = engine._evidence_insufficiencies(ledger, run_id, "result:issue151", {sq: "yes"})
    assert any(
        item.question_id == sq and item.reason.value == "stale_evidence_dependency"
        for item in failures
    )


def test_unrelated_newer_review_does_not_stale_authorizing_review(tmp_path: Path):
    engine, run_id, response, sq = _freeze(tmp_path)
    ledger = engine._bound_ledger(run_id)
    bundle = next(
        EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash))
        for ref in response.evidence_bundles
        if EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash)).sq_id == sq
    )
    claim = EvidenceClaim.model_validate_json(ledger.artifacts.read(bundle.items[0].content_hash))
    review = EvidenceReviewRevision.model_validate_json(
        ledger.artifacts.read(claim.authorizing_review.content_hash)
    )
    unrelated = review.model_copy(
        update={
            "entity_id": "evidence-review:issue151:unrelated",
            "revision_id": "revision:issue151:unrelated:2",
            "candidate_id": "candidate:issue151:unrelated",
        }
    )
    engine._commit_frozen_artifact(
        ledger,
        scope="result:issue151",
        operation="operation:test-unrelated-review",
        operation_key="test:issue151:unrelated-review",
        entity_id=unrelated.entity_id,
        revision_id=unrelated.revision_id,
        artifact=unrelated,
        actor=unrelated.actor,
    )
    failures = engine._evidence_insufficiencies(ledger, run_id, "result:issue151", {sq: "yes"})
    assert not any(item.question_id == sq for item in failures)


def test_one_candidate_question_can_materialize_two_active_exact_spans(tmp_path: Path):
    engine, run_id, work, unit = _setup(tmp_path, suffix="two-spans")
    sq = DOMAINS["domain:randomization"][0]
    receipt = _location_handle_for(engine, run_id, work, sq, unit.unit_id)
    first_end = 3
    review = _review_revision(
        candidate_id=unit.unit_id,
        result_id="result:two-spans",
        domain_id="domain:randomization",
        question_id=sq,
        location_handle=receipt,
        span_start=0,
        span_end=first_end,
        entity_suffix="two-spans",
    )
    review["spans"] = (
        review["spans"][0],
        {
            **review["spans"][0],
            "span_start": first_end,
            "span_end": len(unit.text),
            "rationale": "second exact span",
        },
    )
    response = _submit(
        engine,
        run_id,
        work,
        suffix="two-spans",
        passages=(
            EvidencePassageInput(unit_id=unit.unit_id, span_start=0, span_end=first_end, claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(sq,)),
            EvidencePassageInput(unit_id=unit.unit_id, span_start=first_end, span_end=len(unit.text), claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(sq,)),
        ),
        reviews=(review,),
    )
    ledger = engine._bound_ledger(run_id)
    bundle = next(
        EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash))
        for ref in response.evidence_bundles
        if EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash)).sq_id == sq
    )
    claims = [EvidenceClaim.model_validate_json(ledger.artifacts.read(ref.content_hash)) for ref in bundle.items]
    assert len(claims) == 2
    assert len({claim.review_span_id for claim in claims}) == 2
    assert {claim.authorizing_review.content_hash for claim in claims} == {bundle.review_revisions[0].content_hash}


def test_same_candidate_for_two_questions_has_isolated_reviews_claims_and_bundles(tmp_path: Path):
    engine, run_id, work, unit = _setup(tmp_path, parser=_TwoQuestionParser(), suffix="two-questions")
    first, second = DOMAINS["domain:randomization"][:2]
    first_receipt = _location_handle_for(engine, run_id, work, first, unit.unit_id)
    second_receipt = _location_handle_for(engine, run_id, work, second, unit.unit_id)
    passage = EvidencePassageInput(unit_id=unit.unit_id, span_start=0, span_end=len(unit.text), claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(first, second))
    response = _submit(
        engine,
        run_id,
        work,
        suffix="two-questions",
        passages=(passage,),
        reviews=(
            _review_revision(candidate_id=unit.unit_id, result_id="result:two-questions", domain_id="domain:randomization", question_id=first, location_handle=first_receipt, span_start=0, span_end=len(unit.text), entity_suffix="two-questions-first"),
            _review_revision(candidate_id=unit.unit_id, result_id="result:two-questions", domain_id="domain:randomization", question_id=second, location_handle=second_receipt, span_start=0, span_end=len(unit.text), entity_suffix="two-questions-second"),
        ),
    )
    ledger = engine._bound_ledger(run_id)
    bundles = [EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash)) for ref in response.evidence_bundles]
    selected = {bundle.sq_id: bundle for bundle in bundles if bundle.sq_id in {first, second}}
    assert set(selected) == {first, second}
    claims = {
        sq: EvidenceClaim.model_validate_json(ledger.artifacts.read(bundle.items[0].content_hash))
        for sq, bundle in selected.items()
    }
    assert claims[first].entity_id != claims[second].entity_id
    assert claims[first].authorizing_review != claims[second].authorizing_review
    assert selected[first].review_revisions == (claims[first].authorizing_review,)
    assert selected[second].review_revisions == (claims[second].authorizing_review,)


@pytest.mark.parametrize(
    ("attribution", "review_disposition"),
    (("other", "contextual"), ("not_explicit", "contextual"), ("unresolved", "unresolved")),
)
def test_non_authorizing_review_span_cannot_write_claim_artifacts(
    tmp_path: Path, attribution: str, review_disposition: str
):
    suffix = f"reject-{attribution}"
    engine, run_id, work, unit = _setup(tmp_path, suffix=suffix)
    sq = DOMAINS["domain:randomization"][0]
    receipt = _location_handle_for(engine, run_id, work, sq, unit.unit_id)
    review = _review_revision(candidate_id=unit.unit_id, result_id=f"result:{suffix}", domain_id="domain:randomization", question_id=sq, location_handle=receipt, span_start=0, span_end=len(unit.text), entity_suffix=suffix, disposition=review_disposition)
    review["spans"] = ({**review["spans"][0], "trial_attribution": attribution, "attribution_rationale": None},)
    before = len(engine._bound_ledger(run_id).events())
    if attribution == "unresolved":
        response = _submit(engine, run_id, work, suffix=suffix, passages=(EvidencePassageInput(unit_id=unit.unit_id, span_start=0, span_end=len(unit.text), claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(sq,)),), reviews=(review,))
        assert not response.committed
    else:
        with pytest.raises(ValueError, match="ACTIVE supporting or contradicting"):
            _submit(engine, run_id, work, suffix=suffix, passages=(EvidencePassageInput(unit_id=unit.unit_id, span_start=0, span_end=len(unit.text), claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(sq,)),), reviews=(review,))
    assert len(engine._bound_ledger(run_id).events()) == before


@pytest.mark.parametrize(
    ("attribution", "disposition"),
    (
        ("other", "out_of_scope"),
        ("not_explicit", "contextual"),
        ("unresolved", "unresolved"),
    ),
)
def test_non_substantive_standalone_review_persists_without_a_claim(
    tmp_path: Path, attribution: str, disposition: str
):
    engine, run_id, work, unit = _setup(tmp_path, suffix=f"standalone-{attribution}")
    sq = DOMAINS["domain:randomization"][0]
    receipt = _location_handle_for(engine, run_id, work, sq, unit.unit_id)
    review = _review_revision(
        candidate_id=unit.unit_id,
        result_id=f"result:standalone-{attribution}",
        domain_id="domain:randomization",
        question_id=sq,
        location_handle=receipt,
        span_start=0,
        span_end=len(unit.text),
        entity_suffix=f"standalone-{attribution}",
        disposition=disposition,
    )
    review["spans"] = (
        {
            **review["spans"][0],
            "trial_attribution": attribution,
            "attribution_rationale": None,
        },
    )
    response = _submit(
        engine,
        run_id,
        work,
        suffix=f"standalone-{attribution}",
        passages=(),
        reviews=(review,),
        coverage_state="incomplete",
        coverage_limitations=("Standalone non-substantive review retained for traceability.",),
    )
    assert response.committed
    ledger = engine._bound_ledger(run_id)
    bundle = next(
        EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash))
        for ref in response.evidence_bundles
        if EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash)).sq_id == sq
    )
    assert not bundle.items and len(bundle.review_revisions) == 1


def test_substantive_standalone_non_active_review_is_rejected(tmp_path: Path):
    engine, run_id, work, unit = _setup(tmp_path, suffix="standalone-substantive")
    sq = DOMAINS["domain:randomization"][0]
    receipt = _location_handle_for(engine, run_id, work, sq, unit.unit_id)
    review = _review_revision(
        candidate_id=unit.unit_id,
        result_id="result:standalone-substantive",
        domain_id="domain:randomization",
        question_id=sq,
        location_handle=receipt,
        span_start=0,
        span_end=len(unit.text),
        entity_suffix="standalone-substantive",
    )
    review["spans"] = (
        {
            **review["spans"][0],
            "trial_attribution": "other",
            "attribution_rationale": None,
        },
    )
    before = len(engine._bound_ledger(run_id).events())
    response = _submit(
        engine,
        run_id,
        work,
        suffix="standalone-substantive",
        passages=(),
        reviews=(review,),
    )
    assert not response.committed
    assert len(engine._bound_ledger(run_id).events()) == before


def test_duplicate_or_unmatched_substantive_review_span_is_rejected(tmp_path: Path):
    engine, run_id, work, unit = _setup(tmp_path, suffix="unmatched")
    sq = DOMAINS["domain:randomization"][0]
    receipt = _location_handle_for(engine, run_id, work, sq, unit.unit_id)
    review = _review_revision(candidate_id=unit.unit_id, result_id="result:unmatched", domain_id="domain:randomization", question_id=sq, location_handle=receipt, span_start=0, span_end=3, entity_suffix="unmatched")
    review["spans"] = (
        review["spans"][0],
        {**review["spans"][0], "span_start": 3, "span_end": len(unit.text), "rationale": "unmatched substantive span"},
    )
    before = len(engine._bound_ledger(run_id).events())
    with pytest.raises(ValueError, match="substantive review span"):
        _submit(engine, run_id, work, suffix="unmatched", passages=(EvidencePassageInput(unit_id=unit.unit_id, span_start=0, span_end=3, claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(sq,)),), reviews=(review,))
    assert len(engine._bound_ledger(run_id).events()) == before


def test_duplicate_substantive_review_bounds_are_rejected_before_writes(tmp_path: Path):
    engine, run_id, work, unit = _setup(tmp_path, suffix="duplicate")
    sq = DOMAINS["domain:randomization"][0]
    receipt = _location_handle_for(engine, run_id, work, sq, unit.unit_id)
    review = _review_revision(candidate_id=unit.unit_id, result_id="result:duplicate", domain_id="domain:randomization", question_id=sq, location_handle=receipt, span_start=0, span_end=len(unit.text), entity_suffix="duplicate")
    review["spans"] = (review["spans"][0], review["spans"][0])
    before = len(engine._bound_ledger(run_id).events())
    response = _submit(engine, run_id, work, suffix="duplicate", passages=(EvidencePassageInput(unit_id=unit.unit_id, span_start=0, span_end=len(unit.text), claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(sq,)),), reviews=(review,))
    assert not response.committed
    assert len(engine._bound_ledger(run_id).events()) == before


def test_read_view_receipt_survives_engine_restart_and_direct_index_reopen(tmp_path: Path):
    engine_a, run_id, work, unit = _setup(tmp_path, suffix="restart")
    sq = DOMAINS["domain:randomization"][0]
    receipt = _location_handle_for(engine_a, run_id, work, sq, unit.unit_id)
    reopened = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    persisted = reopened.resolve_read_view_receipt(receipt)
    assert persisted.fragments == (
        ReviewedEvidenceFragment(
            unit_id=unit.unit_id,
            source_id=unit.source_id,
            source_artifact_hash=unit.source_artifact_hash,
            parse_id=unit.parse_id,
            canonicalization_version=unit.canonicalization_version,
            unit_content_hash=sha256_digest(unit.text.encode()),
            span_start=0,
            span_end=len(unit.text),
            content_hash=sha256_digest(unit.text.encode()),
        ),
    )
    fragment = persisted.fragments[0]
    assert (
        fragment.source_id,
        fragment.source_artifact_hash,
        fragment.parse_id,
        fragment.canonicalization_version,
        fragment.unit_content_hash,
    ) == (
        unit.source_id,
        unit.source_artifact_hash,
        unit.parse_id,
        unit.canonicalization_version,
        sha256_digest(unit.text.encode()),
    )

    engine_b = RunEngine(parser=StructuredPassageParser())
    engine_b._bind(tmp_path)
    # The test replaces the process but keeps the existing writer lease's
    # identity; lease recovery itself is deliberately outside receipt scope.
    engine_b._owner_id = engine_a._owner_id
    # A fresh engine can issue the same exact view with a different ephemeral
    # location handle, but the durable receipt must converge on its immutable
    # displayed-content identity.
    assert _location_handle_for(engine_b, run_id, work, sq, unit.unit_id) == receipt
    _complete_passage_receipts(engine_b, run_id, work, unit_id=unit.unit_id)
    response = _submit(
        engine_b,
        run_id,
        work,
        suffix="restart",
        passages=(EvidencePassageInput(unit_id=unit.unit_id, span_start=0, span_end=len(unit.text), claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(sq,)),),
        reviews=(_review_revision(candidate_id=unit.unit_id, result_id="result:restart", domain_id="domain:randomization", question_id=sq, location_handle=receipt, span_start=0, span_end=len(unit.text), entity_suffix="restart"),),
    )
    assert response.committed
    ledger = engine_b._bound_ledger(run_id)
    bundle = next(
        EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash))
        for ref in response.evidence_bundles
        if EvidenceBundle.model_validate_json(ledger.artifacts.read(ref.content_hash)).sq_id == sq
    )
    claim = EvidenceClaim.model_validate_json(ledger.artifacts.read(bundle.items[0].content_hash))
    review = EvidenceReviewRevision.model_validate_json(
        ledger.artifacts.read(claim.authorizing_review.content_hash)
    )
    assert review.spans[0].reviewed_context.fragments[0] == fragment
    assert not any(
        item.question_id == sq and item.reason.value == "unresolvable_evidence"
        for item in engine_b._evidence_insufficiencies(
            ledger, run_id, "result:restart", {sq: "yes"}
        )
    )


def test_stale_or_unknown_persistent_receipt_writes_no_claim_artifacts(tmp_path: Path):
    engine, run_id, work, unit = _setup(tmp_path, suffix="stale-receipt")
    sq = DOMAINS["domain:randomization"][0]
    receipt = _location_handle_for(engine, run_id, work, sq, unit.unit_id)
    index = EvidenceSearchIndex(tmp_path / ".rob2" / "evidence.sqlite3")
    index.replace_units((unit.model_copy(update={"text": unit.text + " changed"}),))
    before = len(engine._bound_ledger(run_id).events())
    review = _review_revision(candidate_id=unit.unit_id, result_id="result:stale-receipt", domain_id="domain:randomization", question_id=sq, location_handle=receipt, span_start=0, span_end=len(unit.text), entity_suffix="stale-receipt")
    with pytest.raises(StaleCursor, match="rerun search and read") as stale:
        _submit(engine, run_id, work, suffix="stale-receipt", passages=(EvidencePassageInput(unit_id=unit.unit_id, span_start=0, span_end=len(unit.text), claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(sq,)),), reviews=(review,))
    assert stale.value.recovery == ("rerun search_evidence", "rerun read_evidence")
    assert len(engine._bound_ledger(run_id).events()) == before

    unknown_review = _review_revision(candidate_id=unit.unit_id, result_id="result:stale-receipt", domain_id="domain:randomization", question_id=sq, location_handle="read-view:not-issued", span_start=0, span_end=len(unit.text), entity_suffix="unknown-receipt")
    with pytest.raises(UnknownCursor, match="read-view receipt"):
        _submit(engine, run_id, work, suffix="stale-receipt", passages=(EvidencePassageInput(unit_id=unit.unit_id, span_start=0, span_end=len(unit.text), claim_type="claim-type:randomization", candidate_id=unit.unit_id, question_ids=(sq,)),), reviews=(unknown_review,))
    assert len(engine._bound_ledger(run_id).events()) == before


def _receipt_fragments(units, *, start=0, end=None):
    return tuple(
        ReviewedEvidenceFragment(
            unit_id=unit.unit_id,
            source_id=unit.source_id,
            source_artifact_hash=unit.source_artifact_hash,
            parse_id=unit.parse_id,
            canonicalization_version=unit.canonicalization_version,
            unit_content_hash=sha256_digest(unit.text.encode()),
            span_start=start if index == 0 else 0,
            span_end=(end if index == 0 else len(unit.text)) if end is not None else len(unit.text),
            content_hash=sha256_digest(
                unit.text[start if index == 0 else 0 : (end if index == 0 else len(unit.text)) if end is not None else len(unit.text)].encode()
            ),
        )
        for index, unit in enumerate(units)
    )


def test_persistent_receipts_capture_exact_unit_and_context_fragments(tmp_path: Path):
    index_path = tmp_path / "read-receipts.sqlite3"
    index = EvidenceSearchIndex(index_path)
    long_text = "alpha " * 3_000
    units = (
        CanonicalEvidenceUnit(unit_id="unit:receipt-long", source_id="source:receipt", source_artifact_hash="sha256:" + "1" * 64, parse_id="parse:receipt", page=1, kind=CanonicalUnitKind.PARAGRAPH, text=long_text, section_path=("section:receipt",), hierarchy_path=("heading:receipt",), reading_order=0),
        CanonicalEvidenceUnit(unit_id="unit:receipt-neighbor", source_id="source:receipt", source_artifact_hash="sha256:" + "1" * 64, parse_id="parse:receipt", page=1, kind=CanonicalUnitKind.PARAGRAPH, text="neighbor", section_path=("section:receipt",), hierarchy_path=("heading:receipt",), reading_order=1),
        CanonicalEvidenceUnit(unit_id="unit:receipt-section", source_id="source:receipt", source_artifact_hash="sha256:" + "1" * 64, parse_id="parse:receipt", page=1, kind=CanonicalUnitKind.PARAGRAPH, text="section", section_path=("section:receipt",), hierarchy_path=("heading:receipt",), reading_order=2),
    )
    index.replace_units(units)
    hit = next(hit for hit in index.search(SearchQuery(terms=("alpha",))).hits if hit.unit.unit_id == units[0].unit_id)
    first = index.read_location(hit.location_handle, character_target=16_000)
    first_fragments = _receipt_fragments((first.unit,), start=first.start, end=first.end)
    first_receipt = index.issue_read_view_receipt(snapshot_hash=first.snapshot_hash, requested_mode=ReadContextMode.UNIT, applied_mode=ReadContextMode.UNIT, continuation_input=None, continuation=first.continuation_cursor, fragments=first_fragments, displayed_units=(first.unit,))
    continued = index.read_location(hit.location_handle, character_target=16_000, cursor=first.continuation_cursor)
    continued_receipt = index.issue_read_view_receipt(snapshot_hash=continued.snapshot_hash, requested_mode=ReadContextMode.UNIT, applied_mode=ReadContextMode.UNIT, continuation_input=first.continuation_cursor, continuation=continued.continuation_cursor, fragments=_receipt_fragments((continued.unit,), start=continued.start, end=continued.end), displayed_units=(continued.unit,))
    assert index.resolve_read_view_receipt(first_receipt).fragments[0].span_end == 16_000
    assert index.resolve_read_view_receipt(continued_receipt).continuation_input == first.continuation_cursor
    assert index.resolve_read_view_receipt(continued_receipt).fragments[0].span_start == 16_000

    short = EvidenceSearchIndex(tmp_path / "context-receipts.sqlite3")
    short.replace_units(units[1:])
    target = units[1]
    for mode in (ReadContextMode.NEIGHBORS, ReadContextMode.SECTION):
        context = short.read_context(target.unit_id, mode=mode)
        fragments = _receipt_fragments(context.all_units)
        receipt = short.issue_read_view_receipt(snapshot_hash=context.snapshot_hash, requested_mode=mode, applied_mode=context.mode, continuation_input=None, continuation=context.continuation_cursor, fragments=fragments, displayed_units=context.all_units)
        resolved = EvidenceSearchIndex(short.path).resolve_read_view_receipt(receipt)
        assert resolved.applied_mode == mode.value
        assert resolved.fragments == fragments
