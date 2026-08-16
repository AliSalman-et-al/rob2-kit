from __future__ import annotations

import sqlite3
from pathlib import Path

import pymupdf
import pytest

from rob2_kit.assessment import captured_batch_hash
from rob2_kit.ingestion import (
    ingest_batch,
    publish_captured_batch,
    read_captured_batch,
)
from rob2_kit.registry import RegistryCandidateRecord, RegistryMatch, RegistryStatus
from rob2_kit.sources import SourceInput, SourceRole, TrialInput
from rob2_kit.storage import ContractVersionError, save_state, transaction
from rob2_kit.text_projection import (
    build_fts_index,
    materialize_projection,
    projection_database_path,
    verified_pages,
)


def _pdf(path: Path, text: str = "first page") -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _source(workspace: Path):
    _pdf(workspace / "main.pdf", "Unicode café page")
    return (
        ingest_batch(
            workspace,
            (
                TrialInput(
                    id="trial",
                    label="Trial",
                    sources=(
                        SourceInput(role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main"),
                    ),
                ),
            ),
        )
        .trials[0]
        .sources[0]
    )


def test_ingestion_extracts_each_local_textual_source_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import rob2_kit.ingestion.service as service

    calls = 0
    original = service._extract_pages

    def counted(data: bytes, media_type: str) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        return original(data, media_type)

    monkeypatch.setattr(service, "_extract_pages", counted)
    _source(tmp_path)
    assert calls == 1


def test_projection_identity_survives_restart_and_fts_is_derivative(tmp_path: Path) -> None:
    source = _source(tmp_path)
    identity = materialize_projection(tmp_path, source)
    assert identity.page_count == source.page_count
    assert projection_database_path(tmp_path).is_file()
    assert verified_pages(tmp_path, source, identity)[0].startswith("Unicode café")

    build_fts_index(tmp_path)
    connection = sqlite3.connect(projection_database_path(tmp_path))
    try:
        assert connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM pages_fts").fetchone()[0] == 1
    finally:
        connection.close()


def test_corrupt_derivative_is_rebuilt_once_to_frozen_identity(tmp_path: Path) -> None:
    source = _source(tmp_path)
    identity = materialize_projection(tmp_path, source)
    connection = sqlite3.connect(projection_database_path(tmp_path))
    try:
        connection.execute("UPDATE pages SET text='corrupt'")
        connection.commit()
    finally:
        connection.close()

    repaired = verified_pages(tmp_path, source, identity)
    assert repaired[0].startswith("Unicode café")
    assert verified_pages(tmp_path, source, identity) == repaired


def test_captured_batch_publishes_only_after_registry_outcome_and_is_content_addressed(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    result = ingest_batch(
        tmp_path,
        (
            TrialInput(
                id="trial",
                label="Trial",
                sources=(SourceInput(role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main"),),
            ),
        ),
    )
    registry = RegistryCandidateRecord(
        trial_id="trial", match=RegistryMatch(status=RegistryStatus.NOT_FOUND)
    )
    captured = publish_captured_batch(
        tmp_path,
        (
            TrialInput(
                id="trial",
                label="Trial",
                sources=(SourceInput(role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main"),),
            ),
        ),
        result,
        {"trial": registry},
    )
    assert captured.content_hash == captured_batch_hash(captured)
    assert read_captured_batch(tmp_path) == captured
    assert source.sha256 == captured.trials[0].sources[0].sha256


def test_legacy_or_unsupported_contract_fails_before_mutation(tmp_path: Path) -> None:
    with transaction(tmp_path) as connection:
        connection.execute(
            "UPDATE runtime_meta SET payload=? WHERE name='runtime_contract_version'", (b"1",)
        )
    path = tmp_path / ".rob2-kit" / "active-batch.sqlite3"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with pytest.raises(ContractVersionError, match="contract_version_unsupported"):
        save_state(tmp_path, b"must-not-write")
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_missing_contract_marker_fails_without_touching_database(tmp_path: Path) -> None:
    with transaction(tmp_path) as connection:
        connection.execute("DELETE FROM runtime_meta WHERE name='runtime_contract_version'")
    path = tmp_path / ".rob2-kit" / "active-batch.sqlite3"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with pytest.raises(ContractVersionError, match="contract_version_unsupported"):
        save_state(tmp_path, b"must-not-write")
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
