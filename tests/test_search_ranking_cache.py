from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from rob2_kit.application._state import _SEARCH_DERIVATIVE_VERSION, _SEARCH_PROFILE
from rob2_kit.application.contracts import COUNTERS
from rob2_kit.application.evidence import (
    _SEARCH_CORPUS_CACHE_MAX,
    _SEARCH_CORPUS_LEASES,
    _evidence_for_handles,
    _recomputed_search_projection,
    _release_search_corpus,
    _search_continuation,
    _search_corpus,
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


def test_warm_search_reuses_complete_ranking_and_evidence_identity(tmp_path: Path) -> None:
    workspace, source_id = _workspace(
        tmp_path,
        "alpha beta one\nunrelated\nalpha beta two\nunrelated\nalpha beta three\n",
    )
    _reset_search_counters()
    leases_before = _SEARCH_CORPUS_LEASES.copy()

    cold = search_sources(workspace, "trial", "alpha beta", mode="any", limit=1)
    cold_evidence = _evidence_for_handles(workspace, {cold["hits"][0]["passage_ref"]})
    cold_identity = next(iter(cold_evidence.values()))["identity"]
    after_cold = COUNTERS.copy()
    warm = search_sources(workspace, "trial", "alpha beta", mode="any", limit=1)
    warm_evidence = _evidence_for_handles(workspace, {warm["hits"][0]["passage_ref"]})

    assert warm["search_receipt"]["identity"] == cold["search_receipt"]["identity"]
    assert (
        warm["search_receipt"]["returned_candidates"]
        == cold["search_receipt"]["returned_candidates"]
    )
    assert warm["hits"][0]["source_id"] == cold["hits"][0]["source_id"] == source_id
    assert next(iter(warm_evidence.values()))["identity"] == cold_identity
    assert COUNTERS["search_ranking_builds"] == after_cold["search_ranking_builds"] == 1
    assert COUNTERS["search_ranking_cache_writes"] == after_cold["search_ranking_cache_writes"] == 1
    assert after_cold["search_ranking_validations"] == 0
    assert COUNTERS["search_ranking_validations"] == 1
    assert COUNTERS["search_cache_writes"] == after_cold["search_cache_writes"]
    assert after_cold["source_projection_verifications"] == 2
    assert COUNTERS["source_projection_verifications"] == 4
    assert _SEARCH_CORPUS_LEASES == leases_before


def test_cursor_continuation_and_restart_use_frozen_ranking(tmp_path: Path) -> None:
    workspace, _ = _workspace(
        tmp_path,
        "alpha beta one\nunrelated\nalpha beta two\nunrelated\nalpha beta three\n",
    )
    _reset_search_counters()

    first = search_sources(workspace, "trial", "alpha beta", mode="any", limit=1)
    after_cold_writes = COUNTERS["search_cache_writes"]
    continuation = search_sources(
        workspace,
        "trial",
        "alpha beta",
        mode="any",
        limit=1,
        cursor=first["next_cursor"],
    )
    final = search_sources(
        workspace,
        "trial",
        "alpha beta",
        mode="any",
        limit=1,
        cursor=continuation["next_cursor"],
    )
    after_continuation_writes = COUNTERS["search_cache_writes"]
    restarted = search_sources(workspace, "trial", "alpha beta", mode="any", limit=1)

    assert [
        first["hits"][0]["rank"],
        continuation["hits"][0]["rank"],
        final["hits"][0]["rank"],
    ] == [1, 2, 3]
    assert final["exhausted"] is True
    assert restarted["hits"][0]["rank"] == 1
    assert first["session_id"] == continuation["session_id"] == restarted["session_id"]
    assert COUNTERS["search_ranking_builds"] == 1
    assert COUNTERS["search_ranking_cache_writes"] == 1
    assert COUNTERS["search_ranking_validations"] == 3
    assert after_continuation_writes > after_cold_writes
    assert after_continuation_writes == COUNTERS["search_cache_writes"]


def test_zero_hit_ranking_is_cached(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path, "alpha beta one\n")
    _reset_search_counters()

    cold = search_sources(workspace, "trial", "missing term", mode="all")
    warm = search_sources(workspace, "trial", "missing term", mode="all")

    assert cold["hits"] == warm["hits"] == []
    assert cold["total_matches"] == warm["total_matches"] == 0
    assert cold["search_receipt"]["identity"] == warm["search_receipt"]["identity"]
    assert COUNTERS["search_ranking_builds"] == 1
    assert COUNTERS["search_ranking_cache_writes"] == 1
    assert COUNTERS["search_ranking_validations"] == 1


def test_warm_ranking_still_rejects_mutated_source_bytes(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path, "alpha beta one\n")
    _reset_search_counters()
    search_sources(workspace, "trial", "alpha beta")

    source_path = next((workspace / ".rob2-kit" / "sources" / "trial").glob("*.bin"))
    source_path.write_bytes(b"changed source bytes\n")
    with pytest.raises(ValueError, match="Source bytes do not match Canonical identity"):
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


def test_stale_search_projection_is_rebuilt_into_the_current_porter_shape(
    tmp_path: Path,
) -> None:
    workspace, source_id = _workspace(tmp_path, "Allocation was concealed.")
    database = workspace / ".rob2-kit" / "derivative.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute("DROP TABLE pages_fts")
            connection.execute(
                "CREATE VIRTUAL TABLE pages_fts USING fts5(source_id, page UNINDEXED, raw_text)"
            )
            connection.execute(
                "INSERT INTO pages_fts VALUES (?,?,?)",
                (source_id, 1, "stale search text"),
            )
            connection.execute(
                "UPDATE search_projection_meta SET value='legacy' "
                "WHERE name IN ('version', 'profile')"
            )

    result = search_sources(workspace, "trial", "concealment", mode="any")

    assert result["hits"][0]["source_id"] == source_id
    with closing(sqlite3.connect(database)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(pages_fts)").fetchall()}
        assert columns == {"source_id", "page", "raw_text", "normalized_text"}
        assert (
            connection.execute(
                "SELECT value FROM search_projection_meta WHERE name='version'"
            ).fetchone()[0]
            == _SEARCH_DERIVATIVE_VERSION
        )
        assert (
            connection.execute(
                "SELECT value FROM search_projection_meta WHERE name='profile'"
            ).fetchone()[0]
            == _SEARCH_PROFILE
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE name IN ('pages_fts_rebuild', 'pages_fts_previous')"
            ).fetchall()
            == []
        )


def test_evicted_fts_corpus_stays_open_until_its_query_releases_it(tmp_path: Path) -> None:
    pages: dict[str, tuple[str, ...]] = {"source-0": ("alpha",)}
    sources = [{"id": "source-0", "projection_hash": "sha256:" + "0" * 64}]
    _key, in_use = _search_corpus(tmp_path, sources, pages)

    for index in range(_SEARCH_CORPUS_CACHE_MAX + 1):
        source_id = f"source-{index + 1}"
        other_sources = [{"id": source_id, "projection_hash": "sha256:" + f"{index + 1:064d}"}]
        _other_key, other = _search_corpus(tmp_path, other_sources, {source_id: ("alpha",)})
        _release_search_corpus(other)

    pairs, _term_pages = _recomputed_search_projection(
        pages,
        "alpha",
        "any",
        ["source-0"],
        (),
        connection=in_use,
    )

    assert pairs == [("source-0", 1)]
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        in_use.execute("SELECT 1")


def test_domain_continuation_preserves_an_unambiguous_question_purpose(tmp_path: Path) -> None:
    workspace, _ = _workspace(
        tmp_path,
        "alpha one\nnoise\nnoise\nalpha two\nnoise\nnoise\nalpha three\n",
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


def test_spelling_feedback_is_source_grounded_and_keeps_the_original_search_unchanged(
    tmp_path: Path,
) -> None:
    workspace, _ = _workspace(tmp_path, "Allocation concealment was documented.\n")

    result = search_sources(workspace, "trial", "concealmet", mode="any")

    assert result["total_matches"] == 0
    assert result["spelling_suggestions"][0]["query_unit"] == "concealmet"
    assert result["spelling_suggestions"][0]["query_unit_index"] == 0
    assert result["spelling_suggestions"][0]["suggested_term"] == "concealment"
    assert result["spelling_suggestions"][0]["next_action"]["query"] == "concealment"
    assert result["spelling_suggestions"][0]["example"]["page"] == 1
    assert result["spelling_suggestions"][0]["example"]["start_line"] == 1
    assert result["search_receipt"]["query"] == "concealmet"


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


def test_spelling_feedback_is_disabled_for_uppercase_prefix_and_literal_search(
    tmp_path: Path,
) -> None:
    workspace, _ = _workspace(tmp_path, "Allocation concealment was documented.\n")

    uppercase = search_sources(workspace, "trial", "CONCEALMET", mode="any")
    prefix = search_sources(workspace, "trial", "concealmet", mode="prefix")
    literal = search_sources(workspace, "trial", "concealmet", mode="literal")

    assert uppercase["spelling_suggestions"] == []
    assert prefix["spelling_suggestions"] == []
    assert literal["spelling_suggestions"] == []


@pytest.mark.parametrize("mode", ("any", "prefix", "literal"))
def test_search_ignores_unlocatable_dehyphenated_catalogue_fragments(
    tmp_path: Path, mode: str
) -> None:
    workspace, _ = _workspace(tmp_path, "Allocation conceal-\nment was documented.\n")

    result = search_sources(workspace, "trial", "concealmet", mode=mode)

    assert result["outcome"] == "success"
