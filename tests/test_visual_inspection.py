from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

from rob2_kit.evidence import (
    CropBox,
    DecisionCriticalContent,
    VisualCandidate,
    VisualCandidateDisposition,
    VisualCandidateDispositionKind,
    VisualCandidateKind,
    VisualInspectionManifest,
    VisualInspectionPolicy,
    VisualInspectionQueue,
    VisualInspectionResult,
    VisualNominationBasis,
    VisualRenderMode,
    submit_visual_inspection,
)

FIXTURE_DIR = Path(__file__).parent / "visual_fixtures"


def candidate(
    suffix: str,
    *,
    kind: VisualCandidateKind = VisualCandidateKind.TABLE,
    basis: VisualNominationBasis = VisualNominationBasis.RETRIEVED_REFERENCE,
    reason: str = "The active SQ depends on the reported analysis population.",
    crop: CropBox = CropBox(left=40, top=60, right=520, bottom=700),
    context_inside_crop: bool = True,
    small_type: bool = False,
    parse_render_discrepancy: bool = False,
    decision_critical: tuple[DecisionCriticalContent, ...] = (),
) -> VisualCandidate:
    return VisualCandidate(
        candidate_id=f"visual:{suffix}",
        source_id="source:primary-report",
        source_artifact_hash="sha256:" + "a" * 64,
        sq_id="sq:3.2",
        page=7,
        kind=kind,
        nomination_basis=basis,
        relevance_reason=reason,
        initial_crop=crop,
        context_inside_crop=context_inside_crop,
        small_type=small_type,
        parse_render_discrepancy=parse_render_discrepancy,
        decision_critical=decision_critical,
    )


def test_only_decision_relevant_regions_can_be_nominated() -> None:
    with pytest.raises(ValueError, match="complexity alone"):
        candidate(
            "irrelevant-figure",
            kind=VisualCandidateKind.FIGURE,
            basis=VisualNominationBasis.AGENT_REASON,
            reason="This is a complex figure.",
        )

    nominated = candidate(
        "irrelevant-looking-but-relevant",
        kind=VisualCandidateKind.FIGURE,
        basis=VisualNominationBasis.AGENT_REASON,
        reason="The active SQ may depend on exclusions displayed only in this figure.",
    )
    assert nominated.nomination_basis is VisualNominationBasis.AGENT_REASON


def test_candidate_queue_has_stable_snapshot_bound_cursors_and_no_total_cap() -> None:
    queue = VisualInspectionQueue(tuple(candidate(f"table-{number:03}") for number in range(30)))

    first = queue.page(limit=7)
    second = queue.page(limit=7)
    assert first == second
    assert len(first.candidates) == 7
    assert first.next_cursor is not None

    all_ids: list[str] = []
    cursor = None
    while True:
        page = queue.page(limit=7, cursor=cursor)
        all_ids.extend(item.candidate_id for item in page.candidates)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert all_ids == [f"visual:table-{number:03}" for number in range(30)]

    changed = VisualInspectionQueue((candidate("replacement"),))
    with pytest.raises(ValueError, match="snapshot"):
        changed.page(cursor=first.next_cursor)


@pytest.mark.parametrize(
    ("fixture", "kind", "context_inside_crop"),
    [
        ("baseline-table", VisualCandidateKind.TABLE, True),
        ("consort-flowchart", VisualCandidateKind.FLOWCHART, False),
        ("outside-crop-footnote", VisualCandidateKind.TABLE, False),
    ],
)
def test_crop_first_rendering_expands_when_context_crosses_crop(
    fixture: str,
    kind: VisualCandidateKind,
    context_inside_crop: bool,
) -> None:
    ElementTree.parse(FIXTURE_DIR / f"{fixture}.svg")
    item = candidate(fixture, kind=kind, context_inside_crop=context_inside_crop)
    request = VisualInspectionPolicy().initial_request(item)

    assert request.dpi == 144
    assert request.mode is VisualRenderMode.CROP
    assert request.crop == item.initial_crop
    if not context_inside_crop:
        expanded = VisualInspectionPolicy().escalate(item, request, still_ambiguous=True)
        assert expanded is not None
        assert expanded.mode is VisualRenderMode.FULL_PAGE
        assert expanded.crop is None
        assert expanded.dpi == 144


def test_small_type_escalates_144_to_180_to_216_then_becomes_limited() -> None:
    item = candidate("small-type", small_type=True)
    policy = VisualInspectionPolicy()

    at_144 = policy.initial_request(item)
    at_180 = policy.escalate(item, at_144, still_ambiguous=True)
    assert at_180 is not None
    at_216 = policy.escalate(item, at_180, still_ambiguous=True)
    assert at_216 is not None
    assert (at_144.dpi, at_180.dpi, at_216.dpi) == (144, 180, 216)
    assert policy.escalate(item, at_216, still_ambiguous=True) is None


def test_legible_visual_transcription_preserves_crop_provenance_and_review_requirement() -> None:
    item = candidate(
        "parse-render-discrepancy",
        parse_render_discrepancy=True,
        decision_critical=(
            DecisionCriticalContent.DENOMINATOR,
            DecisionCriticalContent.ANALYSIS_POPULATION,
        ),
    )
    render = VisualInspectionPolicy().initial_request(item)
    outcome = submit_visual_inspection(
        candidate=item,
        render=render,
        disposition=VisualCandidateDispositionKind.TRANSCRIBED,
        transcription="42 of 51 randomized participants were analysed.",
    )

    assert isinstance(outcome, VisualInspectionResult)
    assert outcome.transcription is not None
    assert outcome.transcription.verification_status == "visual_only"
    assert outcome.transcription.review_required is True
    assert outcome.transcription.render == render
    assert outcome.transcription.decision_critical == item.decision_critical


def test_ambiguous_region_is_limited_coverage_and_cannot_support_no_information() -> None:
    item = candidate("ambiguous-region")
    render = VisualInspectionPolicy().initial_request(item)
    result = submit_visual_inspection(
        candidate=item,
        render=render,
        disposition=VisualCandidateDispositionKind.AMBIGUOUS,
        limitation="The denominator remains illegible at the maximum automatic resolution.",
    )

    assert result.disposition == VisualCandidateDisposition(
        candidate_id=item.candidate_id,
        kind=VisualCandidateDispositionKind.AMBIGUOUS,
        limitation="The denominator remains illegible at the maximum automatic resolution.",
    )
    assert result.coverage_limited is True
    assert result.establishes_no_information_basis() is False
    with pytest.raises(ValueError, match="coverage_limited"):
        VisualInspectionResult(disposition=result.disposition, coverage_limited=False)


def test_render_provenance_must_match_candidate() -> None:
    item = candidate("provenance")
    render = (
        VisualInspectionPolicy().initial_request(item).model_copy(update={"page": item.page + 1})
    )
    with pytest.raises(ValueError, match="provenance"):
        submit_visual_inspection(
            candidate=item,
            render=render,
            disposition=VisualCandidateDispositionKind.INSPECTED_IRRELEVANT,
        )


def test_every_nominated_candidate_requires_exactly_one_disposition() -> None:
    items = (candidate("baseline-table"), candidate("irrelevant-figure"))
    queue = VisualInspectionQueue(items)
    first_render = VisualInspectionPolicy().initial_request(items[0])
    first_result = submit_visual_inspection(
        candidate=items[0],
        render=first_render,
        disposition=VisualCandidateDispositionKind.INSPECTED_IRRELEVANT,
    )

    with pytest.raises(ValueError, match="every nominated"):
        VisualInspectionManifest.complete(queue=queue, results=(first_result,))
    with pytest.raises(ValueError, match="every nominated"):
        VisualInspectionManifest.complete(queue=queue, results=(first_result, first_result))


def test_distributable_visual_fixtures_cover_all_required_cases() -> None:
    assert {path.stem for path in FIXTURE_DIR.glob("*.svg")} == {
        "ambiguous-region",
        "baseline-table",
        "consort-flowchart",
        "irrelevant-figure",
        "outside-crop-footnote",
        "parse-render-discrepancy",
        "small-type",
    }
    for path in FIXTURE_DIR.glob("*.svg"):
        assert ElementTree.parse(path).getroot().tag.endswith("svg")
