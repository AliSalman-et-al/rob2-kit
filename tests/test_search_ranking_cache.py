from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import rob2_kit.application.evidence as evidence
from rob2_kit.application._state import _SEARCH_PROFILE
from rob2_kit.application.contracts import COUNTERS
from rob2_kit.application.evidence import (
    _SEARCH_CORPUS_CACHE_MAX,
    _SEARCH_CORPUS_RETIRED,
    EvidenceIntegrityError,
    _release_search_corpus,
    _search_continuation,
    reset_search_caches,
    search_sources,
)
from rob2_kit.application.intake import prepare_batch
from rob2_kit.models import canonical_json_bytes
from rob2_kit.workflow_models import TrialDeclaration


def _workspace(tmp_path: Path, text: str) -> tuple[Path, str]:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text(text, encoding="utf-8")
    prepared = prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="trial outcome")],
        expected_revision=0,
    )
    return tmp_path, prepared["trials"][0]["sources"][0]["id"]


def _reset_search_counters() -> None:
    COUNTERS["search_ranking_builds"] = 0
    COUNTERS["search_ranking_cache_writes"] = 0
    COUNTERS["search_ranking_validations"] = 0
    COUNTERS["search_cache_writes"] = 0
    COUNTERS["source_projection_verifications"] = 0
    COUNTERS["search_spelling_catalogue_builds"] = 0
    COUNTERS["search_spelling_catalogue_cache_hits"] = 0


def test_warm_ranking_still_rejects_mutated_source_bytes(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path, "alpha beta one\n")
    _reset_search_counters()
    search_sources(workspace, "trial", "alpha beta")

    source_path = next((workspace / ".rob2-kit" / "sources" / "trial").glob("*.bin"))
    source_path.write_bytes(b"changed source bytes\n")
    with pytest.raises(
        EvidenceIntegrityError, match="Source bytes do not match Canonical identity"
    ):
        search_sources(workspace, "trial", "alpha beta")

    assert COUNTERS["search_ranking_builds"] == 1


def test_warm_search_rejects_candidate_moved_off_its_source_match(tmp_path: Path) -> None:
    text = "alpha beta one\nunrelated\nalpha beta two\n"
    workspace, _ = _workspace(tmp_path, text)
    first = search_sources(workspace, "trial", "alpha beta", mode="any", limit=1)
    session_id = first["session_id"]
    database = workspace / ".rob2-kit" / "derivative.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            row = connection.execute(
                "SELECT rank,payload FROM search_candidates "
                "WHERE session_identity=? ORDER BY rank LIMIT 1",
                (session_id,),
            ).fetchone()
            assert row is not None
            candidate = json.loads(bytes(row[1]))
            start = text.index("unrelated")
            candidate.update(
                {
                    "start_line": 2,
                    "end_line": 2,
                    "start": start,
                    "end": start + len("unrelated"),
                }
            )
            connection.execute(
                "UPDATE search_candidates SET payload=? WHERE session_identity=? AND rank=?",
                (canonical_json_bytes(candidate), session_id, row[0]),
            )

    with pytest.raises(ValueError, match="search session candidates are stale or corrupt"):
        search_sources(workspace, "trial", "alpha beta", mode="any", limit=1)


def test_warm_search_rejects_incomplete_cached_ranking(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path, "alpha beta one\nunrelated\nalpha beta two\n")
    first = search_sources(workspace, "trial", "alpha beta", mode="any", limit=1)
    session_id = first["session_id"]
    database = workspace / ".rob2-kit" / "derivative.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            row = connection.execute(
                "SELECT payload FROM search_sessions WHERE identity=?", (session_id,)
            ).fetchone()
            assert row is not None
            session = json.loads(bytes(row[0]))
            session.update({"matching_page_count": 0, "candidate_count": 0, "ranked_pages": []})
            connection.execute(
                "UPDATE search_sessions SET payload=? WHERE identity=?",
                (canonical_json_bytes(session), session_id),
            )
            connection.execute(
                "DELETE FROM search_candidates WHERE session_identity=?", (session_id,)
            )

    with pytest.raises(ValueError, match="search session ranking is stale or corrupt"):
        search_sources(workspace, "trial", "alpha beta", mode="any", limit=1)


def test_search_releases_retired_corpus_after_ranking_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, source_id = _workspace(tmp_path, "alpha beta\n")
    reset_search_caches()
    original_search_corpus = evidence._search_corpus
    original_search_expression = evidence._search_expression
    acquired: list[sqlite3.Connection] = []
    retired_during_ranking: list[int] = []

    def track_search_corpus(
        root: Path,
        sources: list[dict[str, object]],
        pages: dict[str, tuple[str, ...]],
        profile: str = _SEARCH_PROFILE,
    ) -> tuple[object, sqlite3.Connection]:
        key, connection = original_search_corpus(root, sources, pages, profile)
        if any(source.get("id") == source_id for source in sources):
            acquired.append(connection)
        return key, connection

    def evict_during_ranking(query: str, mode: str) -> str:
        if not retired_during_ranking:
            for index in range(_SEARCH_CORPUS_CACHE_MAX):
                other_id = f"eviction-source-{index}"
                _key, connection = original_search_corpus(
                    workspace,
                    [{"id": other_id, "projection_hash": "sha256:" + f"{index + 1:064x}"}],
                    {other_id: ("alpha",)},
                )
                _release_search_corpus(connection)
            retired_during_ranking.append(len(_SEARCH_CORPUS_RETIRED))
        return original_search_expression(query, mode)

    monkeypatch.setattr(evidence, "_search_corpus", track_search_corpus)
    monkeypatch.setattr(evidence, "_search_expression", evict_during_ranking)

    try:
        result = search_sources(workspace, "trial", "alpha", mode="any")

        assert result["hits"]
        assert retired_during_ranking == [1]
        assert _SEARCH_CORPUS_RETIRED == {}
        assert acquired
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            acquired[0].execute("SELECT 1")
    finally:
        reset_search_caches()


def test_domain_continuation_preserves_an_unambiguous_question_purpose(tmp_path: Path) -> None:
    workspace, _ = _workspace(
        tmp_path,
        "alpha one\n" + "noise\n" * 200 + "alpha two\n" + "noise\n" * 200 + "alpha three\n",
    )
    result = search_sources(
        workspace,
        "trial",
        "alpha",
        mode="any",
        limit=1,
        purpose_domain_id="domain:randomization",
        purpose_question_id="sq:randomization:sequence",
    )

    actions = _search_continuation(
        workspace,
        "trial",
        "domain:randomization",
        {(result["session_id"], 1)},
        1,
    )

    assert actions[0]["purpose_domain_id"] == "domain:randomization"
    assert actions[0]["purpose_question_id"] == "sq:randomization:sequence"


def test_spelling_alternatives_replace_one_repeated_query_unit(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path, "Allocation concealment was documented.\n")

    result = search_sources(workspace, "trial", "concealmet and concealmet", mode="any")

    queries = {
        item["next_action"]["query"]
        for item in result["spelling_suggestions"]
        if item["suggested_term"] == "concealment"
    }
    assert queries == {
        "concealment and concealmet",
        "concealmet and concealment",
    }


@pytest.mark.parametrize("mode", ("any", "prefix", "literal"))
def test_search_ignores_unlocatable_dehyphenated_catalogue_fragments(
    tmp_path: Path, mode: str
) -> None:
    workspace, _ = _workspace(tmp_path, "Allocation conceal-\nment was documented.\n")

    result = search_sources(workspace, "trial", "concealmet", mode=mode)

    assert result["outcome"] == "success"
