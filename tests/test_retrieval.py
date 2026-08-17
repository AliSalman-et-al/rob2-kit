from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import pymupdf
import pytest

from rob2_kit.ingestion import ingest_batch, publish_captured_batch
from rob2_kit.registry import RegistryCandidateRecord, RegistryMatch, RegistryStatus
from rob2_kit.retrieval import (
    EvidenceRetrievalBatch,
    LexicalMode,
    PageOperation,
    PageResult,
    RetrievalConditionCode,
    SearchOperation,
    SearchResult,
    TextQuoteSelection,
    TextSelectionResult,
    TextSpanSelection,
    VisualRegionSelection,
    VisualSelectionResult,
    WindowOperation,
    _search_hit,
    build_retrieval_snapshot,
    resolve_evidence_handle,
    retrieve_batch,
)
from rob2_kit.sources import SourceInput, SourceRole, TrialInput
from rob2_kit.text_projection import materialize_projection, unicode61_tokens


def _workspace(tmp_path: Path):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Alpha beta gamma")
    page = document.new_page()
    page.insert_text((72, 72), "Alpha delta gamma")
    document.save(tmp_path / "main.pdf")
    document.close()
    trial = TrialInput(
        id="trial",
        label="Trial",
        sources=(SourceInput(role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main"),),
    )
    ingested = ingest_batch(tmp_path, (trial,))
    captured = publish_captured_batch(
        tmp_path,
        (trial,),
        ingested,
        {
            "trial": RegistryCandidateRecord(
                trial_id="trial", match=RegistryMatch(status=RegistryStatus.NOT_FOUND)
            )
        },
    )
    return captured.trials[0].sources


def test_forged_complete_derivative_rebuilds_from_canonical_projection(tmp_path: Path) -> None:
    sources = _workspace(tmp_path)
    source = sources[0]
    materialize_projection(tmp_path, source, ("forged derivative text", "forged page two"))

    result = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(PageOperation(caller_id="page", source_id=source.id, page_number=1),),
        ),
        sources,
    )

    page = result.operations[0].result
    assert isinstance(page, PageResult)
    assert page.text.startswith("Alpha beta gamma")
    assert "forged" not in page.text


def test_visible_spans_use_fts_token_boundaries_phrase_and_prefix(tmp_path: Path) -> None:
    source = _workspace(tmp_path)[0]
    text = "TRIALS; trial. Alpha—BETA café CAFÉTERIA"
    exact = _search_hit(source, 1, text, LexicalMode.EXACT_PHRASE, ("alpha", "beta"), 1)
    assert tuple(span.text for span in exact.match_spans) == ("Alpha—BETA",)
    term = _search_hit(source, 1, text, LexicalMode.ALL_TERMS, ("trial",), 1)
    assert tuple(span.text for span in term.match_spans) == ("trial",)
    prefix = _search_hit(source, 1, text, LexicalMode.PREFIX_TERMS, ("café",), 1)
    assert tuple(span.text for span in prefix.match_spans) == ("café", "CAFÉTERIA")


def test_unicode61_tokenizer_handles_separators_cjk_and_combining_marks() -> None:
    text = "foo_bar foo-bar can't 中文測試 Cafe\u0301"
    assert tuple(token for _, _, token in unicode61_tokens(text)) == (
        "foo",
        "bar",
        "foo",
        "bar",
        "can",
        "t",
        "中文測試",
        "cafe\u0301",
    )
    assert unicode61_tokens("straße STRASSE")[-2:] == (
        (0, 6, "straße"),
        (7, 14, "strasse"),
    )


def test_visible_span_omitted_count_uses_token_matches(tmp_path: Path) -> None:
    source = _workspace(tmp_path)[0]
    hit = _search_hit(
        source,
        1,
        "trial " + "x" * 300 + " trial trials",
        LexicalMode.ALL_TERMS,
        ("trial",),
        1,
    )
    assert tuple(span.text for span in hit.match_spans) == ("trial",)
    assert hit.omitted_match_count == 1


def test_modes_ordering_windows_and_opaque_cursor(tmp_path: Path) -> None:
    sources = _workspace(tmp_path)
    first = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(
                SearchOperation(caller_id="all", query="alpha gamma", mode=LexicalMode.ALL_TERMS),
                SearchOperation(
                    caller_id="phrase", query="Alpha beta", mode=LexicalMode.EXACT_PHRASE
                ),
                SearchOperation(caller_id="prefix", query="alp", mode=LexicalMode.PREFIX_TERMS),
                WindowOperation(
                    caller_id="window",
                    source_id=sources[0].id,
                    page_number=1,
                    start=0,
                    end=5,
                ),
            ),
        ),
        sources,
    )
    assert [item.status for item in first.operations] == ["succeeded"] * 4
    all_terms = cast(SearchResult, first.operations[0].result)
    phrase = cast(SearchResult, first.operations[1].result)
    prefix = cast(SearchResult, first.operations[2].result)
    window = first.operations[3].result
    assert len(all_terms.hits) == 2
    assert phrase.hits[0].page_number == 1
    assert prefix.hits[0].match_spans[0].text == "Alpha"
    assert window is not None and window.kind == "window" and window.text == "Alpha"

    page = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(
                SearchOperation(
                    caller_id="page", query="gamma", mode=LexicalMode.ANY_TERMS, limit=1
                ),
            ),
        ),
        sources,
    )
    search = cast(SearchResult, page.operations[0].result)
    assert search.next_cursor
    continuation = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(
                SearchOperation(
                    caller_id="page2",
                    query="gamma",
                    mode=LexicalMode.ANY_TERMS,
                    limit=1,
                    cursor=search.next_cursor,
                ),
            ),
        ),
        sources,
    )
    continued = cast(SearchResult, continuation.operations[0].result)
    assert continued.hits[0].page_number == 2

    other = tmp_path / "other"
    other.mkdir()
    other_sources = _workspace(other)
    invalid = ("not-base64", search.next_cursor[:-1] + "A", search.next_cursor)
    bases = (sources, sources, other_sources)
    roots = (tmp_path, tmp_path, other)
    for index, (cursor, basis, root) in enumerate(zip(invalid, bases, roots, strict=True)):
        outcome = retrieve_batch(
            root,
            EvidenceRetrievalBatch(
                trial_id="trial",
                operations=(
                    SearchOperation(
                        caller_id=f"bad-{index}",
                        query="gamma",
                        mode=LexicalMode.ANY_TERMS,
                        cursor=cursor,
                    ),
                ),
            ),
            basis,
        ).operations[0]
        assert outcome.status == "condition"
        assert outcome.condition is not None
        assert outcome.condition.code == RetrievalConditionCode.CURSOR_INVALID


def test_conditions_are_attributed_without_dropping_successes(tmp_path: Path) -> None:
    sources = _workspace(tmp_path)
    result = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(
                SearchOperation(caller_id="none", query="absent", mode=LexicalMode.ALL_TERMS),
                PageOperation(caller_id="page", source_id=sources[0].id, page_number=1),
            ),
        ),
        sources,
    )
    assert result.operations[0].status == "condition"
    assert result.operations[0].condition is not None
    assert result.operations[0].condition.code is RetrievalConditionCode.NO_HITS
    assert result.operations[1].status == "succeeded"


def test_lexical_retrieval_reuses_and_rebuilds_persistent_fts(tmp_path: Path) -> None:
    sources = _workspace(tmp_path)
    operation = EvidenceRetrievalBatch(
        trial_id="trial",
        operations=(SearchOperation(caller_id="search", query="alpha", mode="all_terms"),),
    )
    first = retrieve_batch(tmp_path, operation, sources)
    assert first.operations[0].status == "succeeded"
    path = tmp_path / ".rob2-kit" / "text-projections.sqlite3"
    with sqlite3.connect(path) as connection:
        basis = connection.execute("SELECT value FROM metadata WHERE key='fts_basis'").fetchone()[0]
    second = retrieve_batch(tmp_path, operation, sources)
    assert second == first
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT value FROM metadata WHERE key='fts_basis'").fetchone()[0]
            == basis
        )
        connection.execute("UPDATE pages_fts SET text='forged-only text'")
        connection.commit()
    repaired = retrieve_batch(tmp_path, operation, sources)
    assert repaired == first
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE pages_fts")
    rebuilt = retrieve_batch(tmp_path, operation, sources)
    assert rebuilt == first


def test_shared_fts_failure_rejects_entire_batch_without_partial_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = _workspace(tmp_path)
    from rob2_kit import retrieval
    from rob2_kit.retrieval import RetrievalBatchCondition

    def unavailable(*_args, **_kwargs):
        raise sqlite3.DatabaseError("corrupt FTS basis")

    monkeypatch.setattr(retrieval, "search_fts_pages", unavailable)
    handles_before = dict(retrieval._HANDLE_CACHE)
    events = []
    result = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(
                TextSpanSelection(
                    caller_id="selection",
                    source_id=sources[0].id,
                    page_number=1,
                    start=0,
                    end=5,
                    quote="Alpha",
                ),
                SearchOperation(caller_id="search", query="alpha", mode="all_terms"),
                PageOperation(caller_id="page", source_id=sources[0].id, page_number=1),
            ),
        ),
        sources,
        event_sink=events.append,
    )
    assert isinstance(result, RetrievalBatchCondition)
    assert result.code == "basis_unavailable"
    assert "operations" not in result.model_dump()
    assert retrieval._HANDLE_CACHE == handles_before
    assert not any(getattr(event, "event_type", None) == "retrieval" for event in events)


@pytest.mark.parametrize("payload", [b"not-json", b'{"status":"no_active"}'])
def test_present_invalid_active_state_never_falls_back_to_captured_scope(
    tmp_path: Path, payload: bytes
) -> None:
    sources = _workspace(tmp_path)
    from rob2_kit import retrieval
    from rob2_kit.retrieval import RetrievalBatchCondition
    from rob2_kit.storage import transaction

    with transaction(tmp_path) as connection:
        connection.execute(
            "INSERT INTO records(name,payload) VALUES('active_batch',?) "
            "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
            (payload,),
        )
    handles_before = dict(retrieval._HANDLE_CACHE)
    result = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(PageOperation(caller_id="page", source_id=sources[0].id, page_number=1),),
        ),
        sources,
    )
    assert isinstance(result, RetrievalBatchCondition)
    assert result.code == "basis_unavailable"
    assert "operations" not in result.model_dump()
    assert retrieval._HANDLE_CACHE == handles_before


def test_mismatched_approved_scope_hash_rejects_entire_retrieval(tmp_path: Path) -> None:
    from v2_helpers import approved_workspace

    workspace, source = approved_workspace(tmp_path)
    from rob2_kit.retrieval import RetrievalBatchCondition
    from rob2_kit.storage import transaction

    with transaction(workspace) as connection:
        row = connection.execute("SELECT payload FROM records WHERE name='active_batch'").fetchone()
        assert row is not None
        import json

        payload = json.loads(bytes(row[0]))
        payload["frozen_hash"] = "sha256:" + "0" * 64
        connection.execute(
            "UPDATE records SET payload=? WHERE name='active_batch'",
            (json.dumps(payload).encode(),),
        )
    result = retrieve_batch(
        workspace,
        EvidenceRetrievalBatch(
            trial_id="t",
            operations=(PageOperation(caller_id="page", source_id=source.id, page_number=1),),
        ),
        (source,),
    )
    assert isinstance(result, RetrievalBatchCondition)
    assert result.code == "basis_unavailable"


def test_rehashed_active_approval_must_equal_immutable_detail(tmp_path: Path) -> None:
    from v2_helpers import approved_workspace

    workspace, source = approved_workspace(tmp_path)
    from rob2_kit.batch import ApprovedBatch, frozen_batch_hash
    from rob2_kit.models import canonical_json_bytes
    from rob2_kit.retrieval import RetrievalBatchCondition
    from rob2_kit.storage import transaction

    with transaction(workspace) as connection:
        row = connection.execute("SELECT payload FROM records WHERE name='active_batch'").fetchone()
        assert row is not None
        approved = ApprovedBatch.model_validate_json(bytes(row[0]))
        request = approved.proposal.request.model_copy(
            update={
                "outcome_target": approved.proposal.request.outcome_target.model_copy(
                    update={"label": "coherently forged"}
                )
            }
        )
        proposal = approved.proposal.model_copy(update={"request": request})
        forged = approved.model_copy(
            update={
                "proposal": proposal,
                "frozen_hash": frozen_batch_hash(proposal, approved.pack_identities),
            }
        )
        connection.execute(
            "UPDATE records SET payload=? WHERE name='active_batch'",
            (canonical_json_bytes(forged),),
        )
    result = retrieve_batch(
        workspace,
        EvidenceRetrievalBatch(
            trial_id="t",
            operations=(PageOperation(caller_id="page", source_id=source.id, page_number=1),),
        ),
        (source,),
    )
    assert isinstance(result, RetrievalBatchCondition)
    assert result.code == "basis_unavailable"


def test_selection_classifies_page_before_coordinates_and_region(tmp_path: Path) -> None:
    sources = _workspace(tmp_path)
    result = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch.model_construct(
            trial_id="trial",
            operations=(
                TextSpanSelection(
                    caller_id="text-page",
                    source_id=sources[0].id,
                    page_number=3,
                    start=999,
                    end=1004,
                    quote="wrong",
                ),
                VisualRegionSelection(
                    caller_id="visual-page",
                    source_id=sources[0].id,
                    page_number=3,
                    region=(0.1, 0.1, 0.5, 0.5),
                    transcription="figure",
                ),
                VisualRegionSelection.model_construct(
                    caller_id="visual-region",
                    source_id=sources[0].id,
                    page_number=1,
                    region=(0.8, 0.8, 0.2, 0.2),
                    transcription="figure",
                ),
            ),
        ),
        sources,
    )
    conditions = tuple(item.condition for item in result.operations)
    assert all(item is not None for item in conditions)
    assert tuple(item.code for item in conditions if item is not None) == (
        "page_out_of_range",
        "page_out_of_range",
        "region_invalid",
    )


def test_text_selection_is_ambiguous_until_exact_and_handle_is_scope_bound(
    tmp_path: Path,
) -> None:
    sources = _workspace(tmp_path)
    ambiguous = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(
                TextQuoteSelection(caller_id="quote", source_id=sources[0].id, quote="Alpha"),
            ),
        ),
        sources,
    )
    assert ambiguous.operations[0].condition is not None
    assert ambiguous.operations[0].condition.code is RetrievalConditionCode.AMBIGUOUS_QUOTE
    selected = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(
                TextSpanSelection(
                    caller_id="span",
                    source_id=sources[0].id,
                    page_number=1,
                    start=0,
                    end=5,
                    quote="Alpha",
                ),
            ),
        ),
        sources,
    )
    handle = cast(TextSelectionResult, selected.operations[0].result).handle
    repeated = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(
                TextSpanSelection(
                    caller_id="retry",
                    source_id=sources[0].id,
                    page_number=1,
                    start=0,
                    end=5,
                    quote="Alpha",
                ),
            ),
        ),
        sources,
    )
    repeated_handle = cast(TextSelectionResult, repeated.operations[0].result).handle
    assert repeated_handle.token == handle.token
    context = build_retrieval_snapshot(tmp_path, "trial", sources)
    assert context.snapshot == selected.snapshot
    resolved = resolve_evidence_handle(context, handle)
    assert resolved.kind == "text" and resolved.quote == "Alpha"
    forged = handle.model_copy(update={"token": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="integrity"):
        resolve_evidence_handle(context, forged)


def test_visual_selection_binds_host_transcription_to_verified_region(tmp_path: Path) -> None:
    sources = _workspace(tmp_path)
    selected = retrieve_batch(
        tmp_path,
        EvidenceRetrievalBatch(
            trial_id="trial",
            operations=(
                VisualRegionSelection(
                    caller_id="visual",
                    source_id=sources[0].id,
                    page_number=1,
                    region=(0.0, 0.0, 1.0, 1.0),
                    transcription="Host transcription absent from extracted text.",
                ),
            ),
        ),
        sources,
    )
    result = cast(VisualSelectionResult, selected.operations[0].result)
    context = build_retrieval_snapshot(tmp_path, "trial", sources)
    assert context.snapshot == selected.snapshot
    resolved = resolve_evidence_handle(context, result.handle)
    assert resolved.kind == "visual"
    assert resolved.transcription == "Host transcription absent from extracted text."
