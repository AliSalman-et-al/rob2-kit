from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from rob2_kit.application.run_engine import RunEngine
from rob2_kit.domain.canonical import sha256_digest
from rob2_kit.domain.evidence import (
    EvidenceBundle,
    EvidenceClaim,
    EvidenceReviewDisposition,
    EvidenceReviewRevision,
    EvidenceReviewSpan,
    ReviewedEvidenceContext,
    ReviewedEvidenceFragment,
    TrialAttribution,
    VerificationStatus,
)
from rob2_kit.domain.revisions import Actor, ActorKind, Dependency, RecordReference
from rob2_kit.evidence.search import CanonicalEvidenceUnit, CanonicalUnitKind

ACTOR = Actor(kind=ActorKind.SYSTEM, actor_id="actor:issue-61", display_name="Issue 61 tests")
HASH = "sha256:" + "a" * 64


def _reference(name: str, digest: str | None = None) -> RecordReference:
    digest = digest or ("sha256:" + (name.encode().hex() * 64)[:64])
    return RecordReference(
        entity_id=f"entity:{name}", revision_id=f"revision:{name}-1", content_hash=digest
    )


def _claim_and_bundle(*, spatial: tuple[float, float, float, float] | None):
    unit = CanonicalEvidenceUnit(
        unit_id="unit:report-p2-b1",
        source_id="source:report",
        source_artifact_hash=HASH,
        parse_id="parse:report-initial",
        page=2,
        kind=CanonicalUnitKind.PARAGRAPH,
        text="Allocation was concealed using numbered envelopes.",
        spatial=spatial,
    )
    unit_ref = _reference("unit")
    source_ref = _reference("source")
    review = EvidenceReviewRevision(
        entity_id="entity:review", revision_id="revision:review-1", actor=ACTOR,
        observed_at=datetime(2026, 8, 1, tzinfo=UTC), candidate_id="candidate:claim",
        result_id="result:one", domain_id="domain:one", sq_id="sq:one",
        spans=(EvidenceReviewSpan(
            span_id="review-span:claim", span_start=0, span_end=10,
            trial_attribution=TrialAttribution.ACTIVE,
            disposition=EvidenceReviewDisposition.SUPPORTING,
            rationale="Exact source passage reviewed.",
            attribution_rationale="Bounded context identifies the active Result.",
            reviewed_context=ReviewedEvidenceContext(
                receipt_hash=HASH, snapshot_hash=HASH, requested_mode="unit", applied_mode="unit",
                fragments=(ReviewedEvidenceFragment(
                    unit_id=unit.unit_id,
                    source_id=unit.source_id,
                    source_artifact_hash=unit.source_artifact_hash,
                    parse_id=unit.parse_id,
                    canonicalization_version=unit.canonicalization_version,
                    unit_content_hash=sha256_digest(unit.text.encode()),
                    span_start=0, span_end=10,
                    content_hash=sha256_digest(unit.text[:10].encode()),
                ),),
            ),
        ),),
    )
    review_ref = _reference("review", digest=sha256_digest(review.model_dump_json().encode()))
    claim = EvidenceClaim(
        entity_id="entity:claim",
        revision_id="revision:claim-1",
        dependencies=(
            Dependency(**unit_ref.model_dump(), role="dependency:canonical-unit"),
            Dependency(**source_ref.model_dump(), role="dependency:source"),
            Dependency(**review_ref.model_dump(), role="dependency:evidence-review"),
        ),
        actor=ACTOR,
        observed_at=datetime(2026, 8, 1, tzinfo=UTC),
        canonical_unit=unit_ref,
        source=source_ref,
        authorizing_review=review_ref,
        review_span_id="review-span:claim",
        candidate_id="candidate:claim",
        span_start=0,
        span_end=10,
        quoted_text_hash=sha256_digest(unit.text[:10].encode()),
        claim_type="claim:allocation",
        verification_status=VerificationStatus.MACHINE_VERIFIED,
    )
    claim_ref = _reference("claim")
    bundle = EvidenceBundle(
        entity_id="entity:bundle",
        revision_id="revision:bundle-1",
        dependencies=(
            Dependency(**_reference("result-spec").model_dump(), role="dependency:result-spec"),
            Dependency(
                **_reference("disposition").model_dump(), role="dependency:evidence-disposition"
            ),
            Dependency(**claim_ref.model_dump(), role="dependency:evidence-item"),
            Dependency(**review_ref.model_dump(), role="dependency:evidence-review"),
        ),
        actor=ACTOR,
        observed_at=datetime(2026, 8, 1, tzinfo=UTC),
        result_spec=_reference("result-spec"),
        disposition=_reference("disposition"),
        items=(claim_ref,),
        frozen_content_hash=HASH,
        review_revisions=(review_ref,),
    )
    bundle_ref = _reference("bundle")
    artifacts = {
        bundle_ref.content_hash: bundle.model_dump_json().encode(),
        claim_ref.content_hash: claim.model_dump_json().encode(),
        unit_ref.content_hash: unit.model_dump_json().encode(),
        review_ref.content_hash: review.model_dump_json().encode(),
    }
    ledger = SimpleNamespace(artifacts=SimpleNamespace(read=artifacts.__getitem__))
    return ledger, bundle_ref


def test_accepted_spatial_canonical_claim_projects_to_deterministic_visual_citation() -> None:
    ledger, bundle_ref = _claim_and_bundle(spatial=(72.0, 100.0, 420.0, 130.0))

    first = RunEngine._visual_citations(ledger, (bundle_ref,))
    second = RunEngine._visual_citations(ledger, (bundle_ref,))

    assert first == second
    assert len(first) == 1
    citation = first[0]
    assert citation.citation_id.startswith("visual-citation:")
    assert citation.region == (72.0, 100.0, 420.0, 130.0)
    assert citation.exact_phrase == "Allocation"
    assert "parse:report-initial" in citation.render_provenance


def test_canonical_claim_without_spatial_geometry_has_no_fabricated_visual_citation() -> None:
    ledger, bundle_ref = _claim_and_bundle(spatial=None)

    assert RunEngine._visual_citations(ledger, (bundle_ref,)) == ()
