"""Single-process, transactional capture of explicit local Trial Sources.

The active batch has one owning process.  This code detects observable path
redirection immediately before and after publication; it cannot make hostile
concurrent filesystem mutation safe without a broader ownership mechanism.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from rob2_kit.sources import (
    ExpectedCondition,
    IngestBatchResult,
    IngestedTrial,
    Source,
    SourceInput,
    SourceRole,
    TrialInput,
    _extract_pages,
    _media_type,
    _under,
    extraction_warnings,
    list_sources,
    sha256_bytes,
)


@dataclass(frozen=True)
class _PreparedSource:
    source: Source
    data: bytes


def ingest_batch(workspace: str | Path, trial_inputs: tuple[TrialInput, ...]) -> IngestBatchResult:
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir() or not trial_inputs:
        raise ValueError("workspace must be a directory and include at least one TrialInput")
    if len({trial.id for trial in trial_inputs}) != len(trial_inputs):
        raise ValueError("TrialInput ids must be unique")
    return IngestBatchResult(trials=tuple(_ingest_trial(root, trial) for trial in trial_inputs))


def _ingest_trial(root: Path, trial: TrialInput) -> IngestedTrial:
    mains = [item for item in trial.sources if item.role is SourceRole.MAIN_ARTICLE]
    if len(mains) != 1:
        return IngestedTrial(
            trial_id=trial.id,
            condition=ExpectedCondition(
                code="main_article_required" if not mains else "main_article_ambiguous",
                trial_id=trial.id,
                detail="exactly one source with role main_article is required",
            ),
        )
    main_path = _under(root, mains[0].path)
    if not main_path.is_file():
        raise ValueError(f"source is not a file: {mains[0].path}")
    main_data = main_path.read_bytes()
    try:
        if _media_type(main_path, main_data) != "application/pdf":
            raise ValueError
        _extract_pages(main_data, "application/pdf")
    except (ValueError, pymupdf.FileDataError):
        return _main_article_pdf_condition(trial.id)
    prepared = _prepare_all(root, trial)
    _publish_trial(root, trial.id, prepared)
    return IngestedTrial(
        trial_id=trial.id, sources=list_sources([item.source for item in prepared])
    )


def _main_article_pdf_condition(trial_id: str) -> IngestedTrial:
    return IngestedTrial(
        trial_id=trial_id,
        condition=ExpectedCondition(
            code="main_article_must_be_pdf",
            trial_id=trial_id,
            detail="the designated main_article must contain a valid PDF",
        ),
    )


def _prepare_all(root: Path, trial: TrialInput) -> tuple[_PreparedSource, ...]:
    raw = tuple(_read_source(root, trial.id, item) for item in trial.sources)
    occurrences: Counter[str] = Counter()
    prepared: list[_PreparedSource] = []
    for source_input, data, media_type, pages, fingerprint in raw:
        occurrence = occurrences[fingerprint]
        occurrences[fingerprint] += 1
        source_id = "source_" + hashlib.sha256(f"{fingerprint}\0{occurrence}".encode()).hexdigest()
        suffix = {"application/pdf": ".pdf", "text/plain": ".txt", "application/json": ".json"}[
            media_type
        ]
        relative = Path(".rob2-kit") / "sources" / trial.id / f"{source_id}{suffix}"
        prepared.append(
            _PreparedSource(
                Source(
                    id=source_id,
                    trial_id=trial.id,
                    role=source_input.role,
                    label=source_input.label,
                    sha256=sha256_bytes(data),
                    media_type=media_type,
                    page_count=len(pages),
                    extraction_warnings=extraction_warnings(media_type, pages),
                    captured_path=relative.as_posix(),
                ),
                data,
            )
        )
    return tuple(prepared)


def _read_source(
    root: Path, trial_id: str, item: SourceInput
) -> tuple[SourceInput, bytes, str, tuple[str, ...], str]:
    path = _under(root, item.path)
    if not path.is_file():
        raise ValueError(f"source is not a file: {item.path}")
    data = path.read_bytes()
    media_type = _media_type(path, data)
    if media_type not in {"application/pdf", "text/plain", "application/json"}:
        raise ValueError(f"unsupported source media type: {item.path}")
    try:
        pages = _extract_pages(data, media_type)
    except (UnicodeDecodeError, ValueError, pymupdf.FileDataError) as error:
        raise ValueError(f"unable to extract source: {item.path}") from error
    normalized = Path(item.path).as_posix()
    fingerprint = hashlib.sha256(
        "\0".join((trial_id, str(item.role), normalized, item.label, sha256_bytes(data))).encode()
    ).hexdigest()
    return item, data, media_type, pages, fingerprint


def _publish_trial(root: Path, trial_id: str, prepared: tuple[_PreparedSource, ...]) -> None:
    sources_root = _safe_dir(root, (".rob2-kit", "sources"))
    staging_root = _safe_dir(root, (".rob2-kit", "capture-staging"))
    destination = sources_root / trial_id
    _verify_under(sources_root, destination.parent)
    if destination.exists():
        _verify_existing(destination, prepared)
        return
    staging = Path(tempfile.mkdtemp(prefix="trial-", dir=staging_root))
    published = False
    try:
        _verify_under(staging_root, staging)
        for item in prepared:
            _write_capture(staging / Path(item.source.captured_path).name, item.data)
        _verify_under(staging_root, staging)
        _verify_under(sources_root, destination.parent)
        if destination.exists():
            _verify_existing(destination, prepared)
            return
        os.replace(staging, destination)
        published = True
        _verify_under(sources_root, destination)
        _verify_existing(destination, prepared)
    except Exception:
        if staging.exists():
            _remove_verified(staging, staging_root)
        if published and destination.exists() and _published_matches(destination, prepared):
            _remove_verified(destination, sources_root)
        raise


def _safe_dir(root: Path, parts: tuple[str, ...]) -> Path:
    current = root
    for part in parts:
        current /= part
        if current.exists():
            if _is_link_or_reparse(current) or not current.is_dir():
                raise ValueError("capture path is redirected or not a directory")
        else:
            current.mkdir()
        _verify_under(root, current)
    return current


def _verify_under(root: Path, path: Path) -> None:
    if _is_link_or_reparse(path) or not path.resolve(strict=True).is_relative_to(
        root.resolve(strict=True)
    ):
        raise ValueError("capture path escapes workspace or is redirected")


def _is_link_or_reparse(path: Path) -> bool:
    metadata = os.lstat(path)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _write_capture(target: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(data)


def _verify_existing(directory: Path, prepared: tuple[_PreparedSource, ...]) -> None:
    if (
        _is_link_or_reparse(directory)
        or not directory.is_dir()
        or not _published_matches(directory, prepared)
    ):
        raise ValueError("existing trial capture is incomplete or conflicts")


def _published_matches(directory: Path, prepared: tuple[_PreparedSource, ...]) -> bool:
    expected = {Path(item.source.captured_path).name: item.data for item in prepared}
    try:
        entries = {entry.name: entry for entry in directory.iterdir()}
        return set(entries) == set(expected) and all(
            not _is_link_or_reparse(entries[name])
            and entries[name].is_file()
            and entries[name].read_bytes() == data
            for name, data in expected.items()
        )
    except OSError:
        return False


def _remove_verified(path: Path, root: Path) -> None:
    _verify_under(root, path)
    shutil.rmtree(path)
