from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from rob2_kit.application.contracts import COUNTERS
from rob2_kit.application.evidence import _evidence_for_handles, search_sources
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
