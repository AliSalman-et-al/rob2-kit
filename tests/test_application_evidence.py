from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from rob2_kit.application.contracts import ReviewAuthority
from rob2_kit.application.evidence import (
    EvidenceRetrievalRequest,
    LexicalMode,
    ManualSelectionRequest,
    NormalSelectionRequest,
    SearchContinuation,
    SearchRequest,
    VisualSelectionRequest,
    list_sources,
    resolve_evidence,
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


def _workspace(tmp_path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Alpha beta gamma. Alpha appears again.")
    page.insert_text((72, 110), "A second paragraph.")
    page = document.new_page()
    page.insert_text((72, 72), "Alpha on another page.")
    document.save(tmp_path / "main.pdf")
    document.close()
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(
            roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),),
        ),
        registry_request=lambda *_: {"status": "not_found"},
    )
    candidate = preflight.candidates[0]
    plan = save_intake_plan(
        tmp_path,
        preflight.reference,
        (
            IntakePlanEntry(
                candidate_identity=candidate.identity,
                role="main_article",
                disposition=SourceDisposition.INCLUDE,
                criticality=SourceCriticality.REQUIRED,
            ),
        ),
    )
    acknowledgment = acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST)
    capture_batch(tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=acknowledgment))


def test_navigation_cursor_and_evidence_survive_a_new_call(tmp_path: Path) -> None:
    _workspace(tmp_path)
    assert [source.alias for source in list_sources(tmp_path, "trial")] == ["s1"]
    first = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            searches=(
                SearchRequest(
                    kind="search", query="alpha", mode=LexicalMode.ANY_TERMS, limit=1
                ),
            ),
        ),
    )
    assert len(first.hits) == 1 and first.hits[0].next_cursor
    continuation = first.hits[0].next_cursor
    assert continuation is not None
    second = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            continuations=(
                SearchContinuation(kind="continuation", cursor=continuation),
            ),
        ),
    )
    assert second.hits and second.hits[0].snapshot == first.snapshot

    manual = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1", page=1, start=0, end=5, quote="Alpha"
                ),
            ),
        ),
    )
    assert len(manual.evidence) == 1
    assert resolve_evidence(tmp_path, manual.evidence[0]).quote == "Alpha"

    from rob2_kit.application.contracts import RenderReference
    from rob2_kit.application.evidence import source_records
    from rob2_kit.rendering import RenderedPage, render_page

    rendered = render_page(tmp_path, source_records(tmp_path, "trial")[0], 1, (0, 0, 0.5, 0.5))
    assert isinstance(rendered, RenderedPage)
    visual = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            visual_selections=(
                VisualSelectionRequest(
                    kind="visual_selection",
                    render=RenderReference(
                        identity=rendered.render_identity,
                        uri=f"rob2://render/{rendered.render_identity}",
                    ),
                    transcription="the visual region",
                ),
            ),
        ),
    )
    assert len(visual.evidence) == 1
    assert resolve_evidence(tmp_path, visual.evidence[0]).region == (0.0, 0.0, 0.5, 0.5)


def test_normal_selection_requires_an_unambiguous_extent(tmp_path: Path) -> None:
    _workspace(tmp_path)
    result = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            searches=(SearchRequest(kind="search", query="alpha", mode=LexicalMode.ANY_TERMS),),
        ),
    )
    condition = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            normal_selections=(
                NormalSelectionRequest(
                    kind="normal_selection", hit=result.hits[0].identity, extent="match"
                ),
            ),
        ),
    )
    assert condition.evidence == ()
    assert any(item.code == "ambiguous" for item in condition.conditions)


def test_forged_researcher_fields_are_not_an_evidence_input(tmp_path: Path) -> None:
    _workspace(tmp_path)
    with pytest.raises(ValueError):
        SearchRequest.model_validate(
            {"query": "alpha", "mode": LexicalMode.ANY_TERMS, "authority": "researcher"}
        )
