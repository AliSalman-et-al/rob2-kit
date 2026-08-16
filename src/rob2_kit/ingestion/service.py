"""Single-process, transactional capture of explicit local Trial Sources.

The active batch has one owning process.  This code detects observable path
redirection immediately before and after publication; it cannot make hostile
concurrent filesystem mutation safe without a broader ownership mechanism.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pymupdf

from rob2_kit.assessment import (
    CapturedBatch,
    CapturedRegistryOutcome,
    CapturedTrial,
    LocalSourceRecord,
    captured_batch_hash,
)
from rob2_kit.models import canonical_json_bytes, sha256
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
    local_source_id,
    sha256_bytes,
)
from rob2_kit.storage import ensure_contract_version, read_only_transaction, transaction
from rob2_kit.telemetry import NO_OP_EVENT_SINK, EventSinkLike
from rob2_kit.text_projection import (
    TextProjectionIdentity,
    VerifiedProjection,
    canonical_projection_identity,
    materialize_projection,
    projection_identity,
    verified_pages,
)


@dataclass(frozen=True)
class _PreparedSource:
    source: Source
    data: bytes
    pages: tuple[str, ...]
    input_path: str
    occurrence: int


_REGISTRY_MANIFEST = "registry-sources.json"
_REGISTRY_SCHEMA = "rob2-kit.registry-sources.v1"
_LOCAL_MANIFEST = "local-sources.json"
_LOCAL_SCHEMA = "rob2-kit.local-sources.v1"


def ingest_batch(workspace: str | Path, trial_inputs: tuple[TrialInput, ...]) -> IngestBatchResult:
    ensure_contract_version(workspace)
    with read_only_transaction(workspace) as connection:
        if connection is not None and (
            connection.execute(
                "SELECT 1 FROM runtime_meta WHERE name='active_proposal_version'"
            ).fetchone()
            or connection.execute(
                "SELECT 1 FROM records WHERE name='active_batch' OR name LIKE 'terminal_trial:%' "
                "OR name LIKE 'batch_summary:%' LIMIT 1"
            ).fetchone()
        ):
            raise ValueError("captured intake is frozen after Proposal creation")
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir() or not trial_inputs:
        raise ValueError("workspace must be a directory and include at least one TrialInput")
    if len({trial.id for trial in trial_inputs}) != len(trial_inputs):
        raise ValueError("TrialInput ids must be unique")
    return IngestBatchResult(trials=tuple(_ingest_trial(root, trial) for trial in trial_inputs))


def publish_captured_batch(
    workspace: str | Path,
    trial_inputs: tuple[TrialInput, ...],
    result: IngestBatchResult,
    registry_outcomes: Mapping[str, object],
    *,
    event_sink: EventSinkLike = NO_OP_EVENT_SINK,
) -> CapturedBatch:
    """Freeze one complete intake after local and registry work has finished."""

    ensure_contract_version(workspace)
    with read_only_transaction(workspace) as connection:
        if connection is not None and (
            connection.execute(
                "SELECT 1 FROM runtime_meta WHERE name='active_proposal_version'"
            ).fetchone()
            or connection.execute(
                "SELECT 1 FROM records WHERE name='active_batch' OR name LIKE 'terminal_trial:%' "
                "OR name LIKE 'batch_summary:%' LIMIT 1"
            ).fetchone()
        ):
            raise ValueError("Captured Batch is frozen after Proposal creation")
    if len(result.trials) != len(trial_inputs):
        raise ValueError("ingestion result does not cover every Trial declaration")
    captured_trials: list[CapturedTrial] = []
    for declaration, captured in zip(trial_inputs, result.trials, strict=True):
        registry_record = None
        registry_source_record = None
        if captured.trial_id != declaration.id:
            raise ValueError("ingestion result Trial order does not match declarations")
        if captured.condition is not None:
            registry = CapturedRegistryOutcome(
                trial_id=declaration.id,
                status="not_attempted",
            )
            sources: tuple[Source, ...] = ()
        else:
            sources = tuple(captured.sources)
            registry_record = registry_outcomes.get(declaration.id)
            if registry_record is None:
                raise ValueError("registry outcomes are incomplete")
            registry = _registry_outcome(declaration.id, registry_record)
            registry_source_record = registry_record.__getattribute__("captured_source")
            if registry_source_record is not None:
                sources += (registry_source_record,)
            sources = list_sources(sources)
        local_pages = {
            source.id: pages
            for source, pages in zip(captured.sources, captured.projection_pages, strict=True)
        }
        if registry_source_record is not None:
            local_pages[registry_source_record.id] = tuple(
                cast(Any, registry_record).projection_pages
            )
        projections = []
        for source in sources:
            pages = local_pages.get(source.id)
            if not pages:
                raise ValueError("fresh Source projection pages are unavailable")
            expected_identity = projection_identity(source, pages)
            verified_pages(
                workspace,
                source,
                expected_identity,
                event_sink=event_sink,
            )
            projections.append(expected_identity)
        captured_trials.append(
            CapturedTrial(
                trial_input=declaration,
                sources=sources,
                source_inventory_hash=sha256(sources),
                projections=tuple(projections),
                registry=registry,
            )
        )
    draft = CapturedBatch(trial_inputs=trial_inputs, trials=tuple(captured_trials), content_hash="")
    captured = draft.model_copy(update={"content_hash": captured_batch_hash(draft)})
    payload = canonical_json_bytes(captured)
    key = f"captured_batch:{captured.content_hash}"
    with transaction(workspace) as connection:
        if (
            connection.execute(
                "SELECT 1 FROM runtime_meta WHERE name='active_proposal_version'"
            ).fetchone()
            or connection.execute(
                "SELECT 1 FROM records WHERE name='active_batch' OR name LIKE 'terminal_trial:%' "
                "OR name LIKE 'batch_summary:%' LIMIT 1"
            ).fetchone()
        ):
            raise ValueError("Captured Batch is frozen after Proposal creation")
        head = connection.execute(
            "SELECT payload FROM runtime_meta WHERE name='captured_batch_hash'"
        ).fetchone()
        if head is not None:
            current_hash = bytes(head[0]).decode()
            if current_hash != captured.content_hash:
                raise ValueError("completed Captured Batch is immutable until explicit discard")
            current = connection.execute(
                "SELECT payload FROM records WHERE name=?",
                (f"captured_batch:{current_hash}",),
            ).fetchone()
            if current is None or bytes(current[0]) != payload:
                raise ValueError("Captured Batch head is corrupt")
            return captured
        existing = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        if existing is not None and bytes(existing[0]) != payload:
            raise ValueError("Captured Batch identity conflicts with stored bytes")
        if existing is None:
            connection.execute("INSERT INTO records(name,payload) VALUES(?,?)", (key, payload))
        detail_key = f"detail:batch:{captured.content_hash}"
        detail = connection.execute(
            "SELECT payload FROM records WHERE name=?", (detail_key,)
        ).fetchone()
        if detail is not None and bytes(detail[0]) != payload:
            raise ValueError("Captured Batch Detail identity conflicts with stored bytes")
        if detail is None:
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)", (detail_key, payload)
            )
        connection.execute(
            "INSERT INTO runtime_meta(name,payload) VALUES('captured_batch_hash',?) "
            "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
            (captured.content_hash.encode(),),
        )
    return captured


def _registry_outcome(trial_id: str, record: object) -> CapturedRegistryOutcome:
    typed_record = cast(Any, record)
    match = typed_record.match
    status = match.status.value
    captured_source = typed_record.captured_source
    return CapturedRegistryOutcome(
        trial_id=trial_id,
        status=status,
        record_hash=sha256(typed_record.model_dump(mode="json")),
        captured_source_sha256=None if captured_source is None else captured_source.sha256,
    )


def read_captured_batch(workspace: str | Path) -> CapturedBatch | None:
    """Read and verify the immutable Captured Batch head, if intake completed."""

    with read_only_transaction(workspace) as connection:
        if connection is None:
            return None
        try:
            pointer = connection.execute(
                "SELECT payload FROM runtime_meta WHERE name='captured_batch_hash'"
            ).fetchone()
        except Exception as error:
            raise ValueError("Captured Batch identity is unavailable") from error
        if pointer is None:
            return None
        content_hash = bytes(pointer[0]).decode()
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?", (f"captured_batch:{content_hash}",)
        ).fetchone()
        if row is None:
            raise ValueError("Captured Batch record is unavailable")
        captured = CapturedBatch.model_validate_json(bytes(row[0]))
        if captured.content_hash != content_hash or captured_batch_hash(captured) != content_hash:
            raise ValueError("Captured Batch identity is corrupt")
        return captured


def capture_source_bytes(
    workspace: str | Path,
    trial_id: str,
    role: SourceRole,
    label: str,
    data: bytes,
) -> Source:
    """Append one generated immutable Source to an already captured Trial."""
    ensure_contract_version(workspace)
    root = Path(workspace).resolve(strict=True)
    sources_root = _safe_dir(root, (".rob2-kit", "sources"))
    destination = sources_root / trial_id
    _verify_under(sources_root, destination)
    if not destination.is_dir() or _is_link_or_reparse(destination):
        raise ValueError("trial has no safe captured source directory")
    media_type = _media_type(Path("record.json"), data)
    if media_type != "application/json":
        raise ValueError("generated registry source must be JSON")
    try:
        pages = _extract_pages(data, media_type)
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("generated registry source is invalid JSON") from error
    if role is not SourceRole.REGISTRY:
        raise ValueError("generated source capture supports registry records only")
    source = _registry_source(trial_id, label, data, media_type, pages)
    target = destination / Path(source.captured_path).name
    _verify_under(sources_root, destination)
    manifest = destination / _REGISTRY_MANIFEST
    if manifest.exists() or manifest.is_symlink():
        try:
            existing_source = _registry_manifest_sources(
                root,
                destination,
                expected_identity=projection_identity(source, pages),
            )[0]
        except ValueError as error:
            raise ValueError("existing registry source conflicts") from error
        if existing_source != source:
            raise ValueError("existing registry source conflicts")
        return source
    if target.exists():
        raise ValueError("registry source exists without a manifest")
    staging_root = _safe_dir(root, (".rob2-kit", "capture-staging"))
    staging = Path(tempfile.mkdtemp(prefix="source-", dir=staging_root))
    staged = staging / target.name
    staged_manifest = staging / _REGISTRY_MANIFEST
    published = False
    try:
        _write_capture(staged, data)
        _write_capture(
            staged_manifest,
            _registry_manifest_bytes(source, projection_identity(source, pages)),
        )
        _verify_under(staging_root, staged)
        _verify_under(staging_root, staged_manifest)
        _verify_under(sources_root, destination)
        os.rename(staged, target)
        published = True
        _verify_under(sources_root, target)
        _publish_registry_manifest(staged_manifest, manifest)
    except Exception:
        if published:
            _remove_published_registry_source(target, source, data, pages)
        raise
    finally:
        if staging.exists():
            _remove_verified(staging, staging_root)
    materialize_projection(root, source, pages)
    return source


def registry_source(workspace: str | Path, trial_id: str) -> Source | None:
    """Return the one captured registry Source for a Trial, if present and valid."""
    root = Path(workspace).resolve(strict=True)
    directory = root / ".rob2-kit" / "sources" / trial_id
    if not directory.exists():
        return None
    _verify_under(root / ".rob2-kit" / "sources", directory)
    if not (directory / _REGISTRY_MANIFEST).exists() and _has_registry_orphan(directory):
        raise ValueError("registry source manifest is missing")
    sources = _registry_manifest_sources(root, directory, allow_missing=True)
    if not sources:
        return None
    if len(sources) != 1:
        raise ValueError("multiple registry sources are not supported")
    return sources[0]


def _registry_manifest_bytes(source: Source, identity: TextProjectionIdentity) -> bytes:
    payload = {
        "schema": _REGISTRY_SCHEMA,
        "sources": [source.model_dump(mode="json")],
        "projections": [identity.model_dump(mode="json")],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _publish_registry_manifest(staged: Path, manifest: Path) -> None:
    os.replace(staged, manifest)


def _remove_published_registry_source(
    target: Path, source: Source, data: bytes, pages: tuple[str, ...]
) -> None:
    if (
        _is_link_or_reparse(target)
        or not target.is_file()
        or target.read_bytes() != data
        or _registry_source(
            source.trial_id,
            source.label,
            data,
            source.media_type,
            pages,
        )
        != source
    ):
        raise ValueError("published registry source changed before rollback")
    target.unlink()


def _registry_manifest_sources(
    root: Path,
    directory: Path,
    *,
    allow_missing: bool = False,
    expected_identity=None,
) -> tuple[Source, ...]:
    manifest = directory / _REGISTRY_MANIFEST
    if not manifest.exists():
        if allow_missing:
            return ()
        raise ValueError("registry source manifest is missing")
    _verify_under(root / ".rob2-kit" / "sources", manifest)
    try:
        payload = json.loads(manifest.read_bytes())
        if not isinstance(payload, dict) or payload.get("schema") != _REGISTRY_SCHEMA:
            raise ValueError
        rows = payload.get("sources")
        if not isinstance(rows, list):
            raise ValueError
        sources = tuple(Source.model_validate(row) for row in rows)
        projection_rows = payload.get("projections")
        if not isinstance(projection_rows, list) or len(projection_rows) != 1:
            raise ValueError
        manifest_identity = TextProjectionIdentity.model_validate(projection_rows[0])
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("registry source manifest is invalid") from error
    if len(sources) != 1:
        raise ValueError("registry source manifest must contain exactly one Source")
    source = sources[0]
    try:
        path = _captured_registry_path(root, source)
        data = path.read_bytes()
        identity = manifest_identity if expected_identity is None else expected_identity
        captured_batch = read_captured_batch(root)
        canonical_identity = (
            identity if captured_batch is None else canonical_projection_identity(root, source)
        )
        if canonical_identity != identity:
            raise ValueError("registry projection identity differs from Captured Batch")
        pages = VerifiedProjection(root).pages(source, identity)
        expected = _registry_source(
            directory.name,
            source.label,
            data,
            _media_type(path, data),
            pages,
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("registry source manifest does not bind captured bytes") from error
    if source != expected:
        raise ValueError("registry source manifest does not bind captured bytes")
    return sources


def _has_registry_orphan(directory: Path) -> bool:
    """Recognize an unmanifested generated provider record without rejecting local JSON Sources."""
    for entry in directory.glob("source_*.json"):
        try:
            if _is_link_or_reparse(entry):
                return True
            payload = json.loads(entry.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("protocolSection"), dict):
            return True
    return False


def _registry_source(
    trial_id: str, label: str, data: bytes, media_type: str, pages: tuple[str, ...]
) -> Source:
    if (
        label != "ClinicalTrials.gov registry record"
        or media_type != "application/json"
        or len(pages) != 1
    ):
        raise ValueError("registry Source invariants are invalid")
    digest = sha256_bytes(data)
    source_id = (
        "source_"
        + hashlib.sha256(
            f"{trial_id}\0{SourceRole.REGISTRY}\0{label}\0{digest}".encode()
        ).hexdigest()
    )
    return Source(
        id=source_id,
        trial_id=trial_id,
        role=SourceRole.REGISTRY,
        label=label,
        sha256=digest,
        media_type="application/json",
        page_count=1,
        extraction_warnings=(),
        captured_path=(Path(".rob2-kit") / "sources" / trial_id / f"{source_id}.json").as_posix(),
    )


def _captured_registry_path(root: Path, source: Source) -> Path:
    expected = Path(".rob2-kit") / "sources" / source.trial_id / f"{source.id}.json"
    if Path(source.captured_path).as_posix() != expected.as_posix():
        raise ValueError("registry Source path is invalid")
    path = _under(root, source.captured_path)
    current = root
    for part in expected.parts:
        current /= part
        if _is_link_or_reparse(current):
            raise ValueError("registry Source path is redirected")
    if path.parent != (root / ".rob2-kit" / "sources" / source.trial_id).resolve(strict=True):
        raise ValueError("registry Source path escapes its Trial directory")
    return path


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
        main_pages = _extract_pages(main_data, "application/pdf")
    except (ValueError, pymupdf.FileDataError):
        return _main_article_pdf_condition(trial.id)
    prepared = _prepare_all(root, trial, main_pages=main_pages)
    _publish_trial(root, trial.id, prepared)
    ordered = list_sources([item.source for item in prepared])
    pages_by_id = {item.source.id: item.pages for item in prepared}
    return IngestedTrial(
        trial_id=trial.id,
        sources=ordered,
        projection_pages=tuple(pages_by_id[source.id] for source in ordered),
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


def _prepare_all(
    root: Path, trial: TrialInput, *, main_pages: tuple[str, ...] | None = None
) -> tuple[_PreparedSource, ...]:
    raw = tuple(
        _read_source(
            root,
            trial.id,
            item,
            pages_override=main_pages if item.role is SourceRole.MAIN_ARTICLE else None,
        )
        for item in trial.sources
    )
    occurrences: Counter[str] = Counter()
    prepared: list[_PreparedSource] = []
    for source_input, data, media_type, pages, fingerprint in raw:
        occurrence = occurrences[fingerprint]
        occurrences[fingerprint] += 1
        source_id = local_source_id(
            trial.id,
            source_input.role,
            source_input.path,
            source_input.label,
            sha256_bytes(data),
            occurrence,
        )
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
                pages,
                Path(source_input.path).as_posix(),
                occurrence,
            )
        )
    return tuple(prepared)


def _read_source(
    root: Path,
    trial_id: str,
    item: SourceInput,
    *,
    pages_override: tuple[str, ...] | None = None,
) -> tuple[SourceInput, bytes, str, tuple[str, ...], str]:
    path = _under(root, item.path)
    if not path.is_file():
        raise ValueError(f"source is not a file: {item.path}")
    data = path.read_bytes()
    media_type = _media_type(path, data)
    if media_type not in {"application/pdf", "text/plain", "application/json"}:
        raise ValueError(f"unsupported source media type: {item.path}")
    if pages_override is None:
        try:
            pages = _extract_pages(data, media_type)
        except (UnicodeDecodeError, ValueError, pymupdf.FileDataError) as error:
            raise ValueError(f"unable to extract source: {item.path}") from error
    else:
        pages = pages_override
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
        _materialize_prepared(root, prepared)
        return
    staging = Path(tempfile.mkdtemp(prefix="trial-", dir=staging_root))
    published = False
    try:
        _verify_under(staging_root, staging)
        for item in prepared:
            _write_capture(staging / Path(item.source.captured_path).name, item.data)
        _write_capture(staging / _LOCAL_MANIFEST, _local_manifest_bytes(prepared))
        _verify_under(staging_root, staging)
        _verify_under(sources_root, destination.parent)
        if destination.exists():
            _verify_existing(destination, prepared)
            _materialize_prepared(root, prepared)
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
    _materialize_prepared(root, prepared)


def _materialize_prepared(root: Path, prepared: tuple[_PreparedSource, ...]) -> None:
    for item in prepared:
        materialize_projection(root, item.source, item.pages)


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


def _local_manifest_bytes(prepared: tuple[_PreparedSource, ...]) -> bytes:
    return json.dumps(
        {
            "schema": _LOCAL_SCHEMA,
            "sources": [
                LocalSourceRecord(
                    source=item.source, input_path=item.input_path, occurrence=item.occurrence
                ).model_dump(mode="json")
                for item in sorted(prepared, key=lambda item: item.source.id)
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def local_source_records(workspace: str | Path, trial_id: str) -> tuple[LocalSourceRecord, ...]:
    """Return the exact validated local captured Source inventory for one Trial."""
    root = Path(workspace).resolve(strict=True)
    directory = root / ".rob2-kit" / "sources" / trial_id
    if not directory.is_dir() or _is_link_or_reparse(directory):
        raise ValueError("trial capture is unavailable")
    manifest = directory / _LOCAL_MANIFEST
    try:
        payload = json.loads(manifest.read_bytes())
        if not isinstance(payload, dict) or payload.get("schema") != _LOCAL_SCHEMA:
            raise ValueError
        rows = payload.get("sources")
        if not isinstance(rows, list):
            raise ValueError
        records = tuple(LocalSourceRecord.model_validate(row) for row in rows)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("local source manifest is invalid") from error
    sources = tuple(record.source for record in records)
    if len({source.id for source in sources}) != len(sources):
        raise ValueError("local source manifest has duplicate Sources")
    from rob2_kit.sources import verified_source_bytes

    for record in records:
        source = record.source
        data = verified_source_bytes(root, source)
        expected_id = local_source_id(
            trial_id,
            source.role,
            record.input_path,
            source.label,
            sha256_bytes(data),
            record.occurrence,
        )
        if (
            source.trial_id != trial_id
            or source.id != expected_id
            or sha256_bytes(data) != source.sha256
        ):
            raise ValueError("local source manifest does not bind captured bytes")
    expected = {Path(source.captured_path).name for source in sources} | {_LOCAL_MANIFEST}
    entries = {entry.name for entry in directory.iterdir()}
    registry = _registry_manifest_sources(root, directory, allow_missing=True)
    allowed = expected | {Path(source.captured_path).name for source in registry}
    if registry:
        allowed.add(_REGISTRY_MANIFEST)
    if entries - allowed:
        raise ValueError("trial capture contains unknown entries")
    return records


def local_sources(workspace: str | Path, trial_id: str) -> tuple[Source, ...]:
    """Return the exact validated local captured Source inventory for one Trial."""
    return tuple(record.source for record in local_source_records(workspace, trial_id))


def _published_matches(directory: Path, prepared: tuple[_PreparedSource, ...]) -> bool:
    expected = {Path(item.source.captured_path).name: item.data for item in prepared}
    try:
        entries = {entry.name: entry for entry in directory.iterdir()}
        extras = set(entries) - set(expected)
        registry_sources = _registry_manifest_sources(
            directory.parent.parent.parent, directory, allow_missing=True
        )
        registry_names = {Path(source.captured_path).name for source in registry_sources}
        return (
            set(expected).issubset(entries)
            and all(
                not _is_link_or_reparse(entries[name])
                and entries[name].is_file()
                and entries[name].read_bytes() == data
                for name, data in expected.items()
            )
            and entries[_LOCAL_MANIFEST].read_bytes() == _local_manifest_bytes(prepared)
            and extras
            == registry_names
            | {_LOCAL_MANIFEST}
            | ({_REGISTRY_MANIFEST} if registry_sources else set())
            and _LOCAL_MANIFEST in entries
        )
    except OSError:
        return False


def _remove_verified(path: Path, root: Path) -> None:
    _verify_under(root, path)
    shutil.rmtree(path)
