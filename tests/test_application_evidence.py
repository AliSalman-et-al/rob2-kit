from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from rob2_kit.application._state import identity, read_json, write_json
from rob2_kit.application.contracts import EvidenceReference, RenderReference, ReviewAuthority
from rob2_kit.application.evidence import (
    EvidenceCatalogRequest,
    EvidenceRetrievalRequest,
    LexicalMode,
    ManualSelectionRequest,
    NormalSelectionRequest,
    PageReadRequest,
    SearchContinuation,
    SearchRequest,
    TextEvidenceCatalogEntry,
    TextEvidenceRecord,
    VisualEvidenceCatalogEntry,
    VisualEvidenceRecord,
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
    font_size: float = 11,
) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), first_page_text, fontsize=font_size)
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
                SearchRequest(kind="search", query="alpha", mode=LexicalMode.ANY_TERMS, limit=1),
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
            continuations=(SearchContinuation(kind="continuation", cursor=continuation),),
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
                    source_alias="s1",
                    page=1,
                    start=0,
                    end=5,
                    quote="Alpha",
                ),
            ),
        ),
    )
    assert len(manual.evidence) == 1
    resolved_manual = resolve_evidence(tmp_path, manual.evidence[0])
    assert isinstance(resolved_manual, TextEvidenceRecord)
    assert resolved_manual.quote == "Alpha"

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
    resolved_visual = resolve_evidence(tmp_path, visual.evidence[0])
    assert isinstance(resolved_visual, VisualEvidenceRecord)
    assert resolved_visual.region == (0.0, 0.0, 0.5, 0.5)
    catalog = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(trial_id="trial", catalog=EvidenceCatalogRequest(kind="catalog")),
    )
    assert catalog.catalog is not None
    visual_entry = next(
        item for item in catalog.catalog.entries if item.evidence == visual.evidence[0]
    )
    assert isinstance(visual_entry, VisualEvidenceCatalogEntry)
    assert visual_entry.preview == "the visual region"


def test_visual_evidence_rejects_a_rehashed_render_source_hash_mismatch(tmp_path: Path) -> None:
    _workspace(tmp_path)
    from rob2_kit.application.evidence import source_records
    from rob2_kit.rendering import RenderedPage, render_page

    rendered = render_page(tmp_path, source_records(tmp_path, "trial")[0], 1, (0, 0, 0.5, 0.5))
    assert isinstance(rendered, RenderedPage)
    response = retrieve_evidence(
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
    reference = response.evidence[0]
    raw = read_json(tmp_path, f"evidence-{reference.identity.removeprefix('sha256:')}.json")
    assert raw is not None
    raw["source_sha256"] = "sha256:" + "f" * 64
    raw["identity"] = identity({key: value for key, value in raw.items() if key != "identity"})
    write_json(tmp_path, f"evidence-{raw['identity'].removeprefix('sha256:')}.json", raw)

    with pytest.raises(ValueError, match="visual Evidence render source hash is outside its scope"):
        resolve_evidence(tmp_path, EvidenceReference(kind="evidence", identity=raw["identity"]))


def test_visual_transcription_rejects_whitespace_only_at_runtime_boundaries() -> None:
    render_identity = "sha256:" + "a" * 64
    render = RenderReference(
        identity=render_identity,
        uri=f"rob2://render/{render_identity}",
    )
    with pytest.raises(ValueError, match="non-whitespace"):
        VisualSelectionRequest(
            kind="visual_selection",
            render=render,
            transcription=" \n\t",
        )
    with pytest.raises(ValueError, match="non-whitespace"):
        VisualEvidenceRecord(
            kind="visual",
            identity="sha256:" + "a" * 64,
            trial_id="trial",
            snapshot="sha256:" + "a" * 64,
            source_id="source",
            source_sha256="sha256:" + "a" * 64,
            projection_hash="sha256:" + "a" * 64,
            page=1,
            render=render,
            transcription=" \n\t",
        )
    entry = VisualEvidenceCatalogEntry(
        evidence=EvidenceReference(kind="evidence", identity=render_identity),
        source_id="source",
        source_alias="s1",
        page=1,
        region=None,
        preview=" ",
        truncated=False,
    )
    assert entry.preview == " "


def test_search_rejects_duplicate_source_aliases() -> None:
    with pytest.raises(ValueError, match="source aliases must be unique"):
        SearchRequest(
            kind="search",
            query="alpha",
            mode=LexicalMode.ANY_TERMS,
            source_aliases=("s1", "s1"),
        )


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
    assert [
        (span.start, span.end, span.text)
        for span in _spans("Straße plan", "strasse plan", LexicalMode.EXACT_PHRASE)
    ] == [(0, 11, "Straße plan")]
    assert [
        (span.start, span.end, span.text) for span in _spans("ß", "s", LexicalMode.EXACT_PHRASE)
    ] == [(0, 1, "ß")]
    assert [
        (span.start, span.end, span.text) for span in _spans("ßs", "s", LexicalMode.EXACT_PHRASE)
    ] == [(0, 1, "ß"), (1, 2, "s")]
    assert [
        (span.start, span.end, span.text)
        for span in _spans("Radio-\r\ngraphic", "radiographic", LexicalMode.EXACT_PHRASE)
    ] == [(0, 15, "Radio-\r\ngraphic")]


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
    assert isinstance(evidence, TextEvidenceRecord)
    assert evidence.quote == "Radio-\ngraphic findings"
    assert evidence.quote == searched.hits[0].preview[span.start : span.end]


def test_normal_selection_from_casefold_expansion_is_not_ambiguous(tmp_path: Path) -> None:
    _workspace(tmp_path, "ß", include_second_paragraph=False)
    searched = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            searches=(SearchRequest(kind="search", query="s", mode=LexicalMode.EXACT_PHRASE),),
        ),
    )
    assert len(searched.hits) == 1
    assert [(span.start, span.end, span.text) for span in searched.hits[0].spans] == [(0, 1, "ß")]
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
    resolved = resolve_evidence(tmp_path, selected.evidence[0])
    assert isinstance(resolved, TextEvidenceRecord)
    assert resolved.quote == "ß"


def test_forged_researcher_fields_are_not_an_evidence_input(tmp_path: Path) -> None:
    _workspace(tmp_path)
    with pytest.raises(ValueError):
        SearchRequest.model_validate(
            {"query": "alpha", "mode": LexicalMode.ANY_TERMS, "authority": "researcher"}
        )


def test_catalog_is_restart_safe_and_retrieval_is_bounded(tmp_path: Path) -> None:
    _workspace(tmp_path)
    minted = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=0,
                    end=5,
                    quote="Alpha",
                ),
            ),
        ),
    )
    response = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(trial_id="trial", catalog=EvidenceCatalogRequest(kind="catalog")),
    )
    assert "sources" not in response.model_dump()
    assert response.catalog is not None
    assert response.catalog.entries[0].evidence == minted.evidence[0]
    assert isinstance(response.catalog.entries[0], TextEvidenceCatalogEntry)
    assert response.catalog.entries[0].preview == "Alpha"
    assert SearchRequest(kind="search", query="alpha", mode=LexicalMode.ANY_TERMS).limit == 5
    with pytest.raises(ValueError, match="at most 8"):
        EvidenceRetrievalRequest(
            trial_id="trial",
            searches=tuple(
                SearchRequest(kind="search", query="alpha", mode=LexicalMode.ANY_TERMS)
                for _ in range(8)
            ),
            catalog=EvidenceCatalogRequest(kind="catalog"),
        )
    with pytest.raises(ValueError):
        SearchRequest(kind="search", query="alpha", mode=LexicalMode.ANY_TERMS, limit=21)
    write_json(
        tmp_path,
        f"evidence-{minted.evidence[0].identity.removeprefix('sha256:')}.json",
        {"identity": minted.evidence[0].identity},
    )
    with pytest.raises(ValueError):
        retrieve_evidence(
            tmp_path,
            EvidenceRetrievalRequest(
                trial_id="trial", catalog=EvidenceCatalogRequest(kind="catalog")
            ),
        )


def test_catalog_pages_are_bounded_content_addressed_and_restart_safe(tmp_path: Path) -> None:
    _workspace(
        tmp_path,
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" * 8,
        include_second_paragraph=False,
        font_size=4,
    )
    page = (
        retrieve_evidence(
            tmp_path,
            EvidenceRetrievalRequest(
                trial_id="trial",
                page_reads=(PageReadRequest(kind="page_read", source_alias="s1", page=1),),
            ),
        )
        .page_reads[0]
        .text
    )
    minted = []
    for offset in range(33):
        minted.extend(
            retrieve_evidence(
                tmp_path,
                EvidenceRetrievalRequest(
                    trial_id="trial",
                    manual_selections=(
                        ManualSelectionRequest(
                            kind="manual_selection",
                            source_alias="s1",
                            page=1,
                            start=offset,
                            end=offset + 1,
                            quote=page[offset : offset + 1],
                        ),
                    ),
                ),
            ).evidence
        )
    long_end = min(len(page), 180)
    assert long_end > 160
    long_evidence = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=0,
                    end=long_end,
                    quote=page[:long_end],
                ),
            ),
        ),
    ).evidence[0]
    first = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(trial_id="trial", catalog=EvidenceCatalogRequest(kind="catalog")),
    ).catalog
    assert first is not None and len(first.entries) == 32 and first.has_more
    assert first.next_after == first.entries[-1].evidence
    assert all(len(entry.preview) <= 160 for entry in first.entries)
    assert page[:long_end] not in first.model_dump_json()
    assert len(first.model_dump_json()) < 16_000
    second = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            catalog=EvidenceCatalogRequest(
                kind="catalog", basis=first.basis, after=first.next_after
            ),
        ),
    ).catalog
    assert second is not None and not second.has_more
    assert [entry.evidence.identity for entry in (*first.entries, *second.entries)] == sorted(
        item.identity for item in (*minted, long_evidence)
    )
    retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=34,
                    end=35,
                    quote=page[34:35],
                ),
            ),
        ),
    )
    stale = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="trial",
            catalog=EvidenceCatalogRequest(
                kind="catalog", basis=first.basis, after=first.next_after
            ),
        ),
    )
    assert stale.catalog is None and stale.conditions[0].code == "stale_catalog"
