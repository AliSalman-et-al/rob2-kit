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
    _spans,
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


def _workspace(
    tmp_path: Path,
    first_page_text: str = "Alpha beta gamma. Alpha appears again.",
    include_second_paragraph: bool = True,
) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), first_page_text)
    if include_second_paragraph:
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


def test_exact_phrase_projects_whitespace_hyphenation_and_original_spans() -> None:
    text = "Alpha \n\t beta. Radio-\ngraphic study. long-term study. word- next. Alpha beta."

    whitespace = _spans(text, "alpha beta", LexicalMode.EXACT_PHRASE)
    assert [(span.start, span.end, span.text) for span in whitespace] == [
        (0, 13, "Alpha \n\t beta"),
        (66, 76, "Alpha beta"),
    ]
    hyphenated = _spans(text, "radiographic study", LexicalMode.EXACT_PHRASE)
    assert [(span.start, span.end, span.text) for span in hyphenated] == [
        (15, 35, "Radio-\ngraphic study")
    ]
    assert _spans(text, "long term", LexicalMode.EXACT_PHRASE) == ()
    assert _spans(text, "word next", LexicalMode.EXACT_PHRASE) == ()
    assert _spans(text, "wordnext", LexicalMode.EXACT_PHRASE) == ()
    assert [span.text for span in _spans(text, "alpha", LexicalMode.ANY_TERMS)] == [
        "Alpha",
        "Alpha",
    ]
    assert [(span.start, span.end, span.text) for span in _spans(
        "Straße plan", "strasse plan", LexicalMode.EXACT_PHRASE
    )] == [(0, 11, "Straße plan")]
    assert [(span.start, span.end, span.text) for span in _spans(
        "ß", "s", LexicalMode.EXACT_PHRASE
    )] == [(0, 1, "ß")]
    assert [(span.start, span.end, span.text) for span in _spans(
        "ßs", "s", LexicalMode.EXACT_PHRASE
    )] == [(0, 1, "ß"), (1, 2, "s")]
    assert [(span.start, span.end, span.text) for span in _spans(
        "Radio-\r\ngraphic", "radiographic", LexicalMode.EXACT_PHRASE
    )] == [(0, 15, "Radio-\r\ngraphic")]


def test_normal_selection_from_projected_phrase_mints_exact_evidence(tmp_path: Path) -> None:
    _workspace(tmp_path, "Radio-\ngraphic findings.")
    searched = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            searches=(
                SearchRequest(
                    kind="search",
                    query="radiographic findings",
                    mode=LexicalMode.EXACT_PHRASE,
                ),
            ),
        ),
    )
    assert len(searched.hits) == 1
    span = searched.hits[0].spans[0]
    selected = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            normal_selections=(
                NormalSelectionRequest(
                    kind="normal_selection", hit=searched.hits[0].identity, extent="match"
                ),
            ),
        ),
    )
    assert len(selected.evidence) == 1
    evidence = resolve_evidence(tmp_path, selected.evidence[0])
    assert evidence.quote == "Radio-\ngraphic findings"
    assert evidence.quote == searched.hits[0].preview[span.start : span.end]


def test_normal_selection_from_casefold_expansion_is_not_ambiguous(tmp_path: Path) -> None:
    _workspace(tmp_path, "ß", include_second_paragraph=False)
    searched = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            searches=(
                SearchRequest(kind="search", query="s", mode=LexicalMode.EXACT_PHRASE),
            ),
        ),
    )
    assert len(searched.hits) == 1
    assert [(span.start, span.end, span.text) for span in searched.hits[0].spans] == [
        (0, 1, "ß")
    ]
    selected = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            normal_selections=(
                NormalSelectionRequest(
                    kind="normal_selection", hit=searched.hits[0].identity, extent="match"
                ),
            ),
        ),
    )
    assert len(selected.evidence) == 1
    assert resolve_evidence(tmp_path, selected.evidence[0]).quote == "ß"


def test_forged_researcher_fields_are_not_an_evidence_input(tmp_path: Path) -> None:
    _workspace(tmp_path)
    with pytest.raises(ValueError):
        SearchRequest.model_validate(
            {"query": "alpha", "mode": LexicalMode.ANY_TERMS, "authority": "researcher"}
        )
