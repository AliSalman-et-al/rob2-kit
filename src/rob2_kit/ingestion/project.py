"""Project-folder discovery, source custody, and coverage-explicit parsing."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import version
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Protocol
from zipfile import BadZipFile, ZipFile

import yaml
from pydantic import Field

from rob2_kit.application.preparation import TrialFailed, TrialFailureReason
from rob2_kit.domain.results import ResultSpecRevision
from rob2_kit.domain.revisions import Actor, ContentHash, FrozenModel, Identifier
from rob2_kit.domain.sources import (
    AcquisitionMethod,
    AcquisitionOutcome,
    AcquisitionReceipt,
    ClassificationProvenance,
    CoverageState,
    PageCoverage,
    ParseRecord,
    SourceAvailability,
    SourceComponentAnnotation,
    SourceCriticality,
    SourceDescriptor,
    SourceFailureCategory,
    SourceProcessing,
    SourceRole,
    TrialSourceInventory,
)
from rob2_kit.storage import ArtifactStore, WorkflowLedger

CLASSIFIER_VERSION = "source-classifier:1.0.0"
CANONICALIZATION_VERSION = "liteparse-adapter:1.0.0"
RECOVERY_REASONS = frozenset({"no-text", "scanned"})
LIMITED_REASONS = frozenset({"garbled"})
BLANK_REASONS = frozenset({"intentionally-blank", "intentionally_blank", "blank"})
VISUAL_REASONS = frozenset({"parse-render-discrepancy"})
DEFAULT_ZIP_MAX_MEMBERS = 100
DEFAULT_ZIP_MAX_EXPANDED_BYTES = 100 * 1024 * 1024


class BoundedZipError(ValueError):
    """A ZIP failed traversal, member-count, or expanded-size validation."""


class SourceParseError(ValueError):
    """A supplied source could not be parsed by the configured adapter."""


def read_bounded_zip(
    data: bytes,
    *,
    max_members: int = DEFAULT_ZIP_MAX_MEMBERS,
    max_expanded_bytes: int = DEFAULT_ZIP_MAX_EXPANDED_BYTES,
) -> dict[str, bytes]:
    """Read a ZIP only after validating every name and declared expanded size."""
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = tuple(info for info in archive.infolist() if not info.is_dir())
            if len(members) > max_members:
                raise BoundedZipError("ZIP exceeds the member-count limit")
            total = 0
            for info in members:
                normalized = PurePosixPath(info.filename.replace("\\", "/"))
                windows_path = PureWindowsPath(info.filename)
                if (
                    normalized.is_absolute()
                    or windows_path.is_absolute()
                    or windows_path.drive
                    or ".." in normalized.parts
                ):
                    raise BoundedZipError(f"ZIP contains unsafe member path: {info.filename}")
                total += info.file_size
                if total > max_expanded_bytes:
                    raise BoundedZipError("ZIP exceeds the expanded-size limit")
            extracted: dict[str, bytes] = {}
            actual_total = 0
            for info in members:
                content = archive.read(info)
                actual_total += len(content)
                if actual_total > max_expanded_bytes:
                    raise BoundedZipError("ZIP exceeds the expanded-size limit")
                extracted[info.filename.replace("\\", "/")] = content
            return dict(sorted(extracted.items()))
    except BadZipFile as error:
        raise BoundedZipError("malformed ZIP container") from error


class PageExtraction(FrozenModel):
    page_number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    text: str
    reasons: tuple[str, ...] = ()


class ParserResult(FrozenModel):
    pages: tuple[PageExtraction, ...]
    raw_output: bytes


class DocumentParser(Protocol):
    name: str
    version: str

    def parse(
        self,
        data: bytes,
        *,
        ocr_enabled: bool,
        target_pages: tuple[int, ...] | None = None,
    ) -> ParserResult: ...


class LiteParseAdapter:
    """Convert LiteParse's version-specific objects to stable ingestion records."""

    name = "liteparse"

    def __init__(self) -> None:
        self.version = version("liteparse")

    def parse(
        self,
        data: bytes,
        *,
        ocr_enabled: bool,
        target_pages: tuple[int, ...] | None = None,
    ) -> ParserResult:
        from liteparse import LiteParse

        target = None if target_pages is None else ",".join(str(page) for page in target_pages)
        try:
            parsed = LiteParse(
                ocr_enabled=ocr_enabled,
                include_complexity=True,
                target_pages=target,
                quiet=True,
            ).parse(data)
        except ValueError as error:
            raise SourceParseError(str(error)) from error
        pages = tuple(
            PageExtraction(
                page_number=page.page_num,
                width=page.width,
                height=page.height,
                text=page.text,
                reasons=tuple(page.complexity.reasons if page.complexity else ()),
            )
            for page in parsed.pages
        )
        raw = json.dumps(
            {
                "pages": [
                    {
                        "page_number": page.page_number,
                        "width": page.width,
                        "height": page.height,
                        "text": page.text,
                        "reasons": page.reasons,
                    }
                    for page in pages
                ]
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return ParserResult(pages=pages, raw_output=raw)


class ProjectManifest(FrozenModel):
    project_name: str = Field(min_length=1)
    input_root: str
    output_root: str
    state_root: str
    supported_scope: str = "rob2:individually-randomized-parallel"
    outcome_targets: tuple[str, ...] = ()
    source_adapters: tuple[str, ...] = ("adapter:local-folder",)
    logic_releases: tuple[str, ...] = ("logic:rob2-parallel-assignment-2019.1",)
    guidance_releases: tuple[str, ...] = ("guidance:rob2-parallel-assignment-en-2019.1",)
    policy_releases: tuple[str, ...] = (
        "policy:source-recovery-1.0.0",
        "policy:review-1.0.0",
    )
    export_preferences: tuple[str, ...] = ("json", "markdown", "html")
    archive_preference: str = "complete"


class ReviewFindingKind(StrEnum):
    PRIMARY_REPORT_AMBIGUOUS = "primary_report_ambiguous"
    OPTIONAL_SOURCE_ACQUISITION_FAILED = "optional_source_acquisition_failed"
    OPTIONAL_SOURCE_PROCESSING_FAILED = "optional_source_processing_failed"


class ReviewFinding(FrozenModel):
    kind: ReviewFindingKind
    trial_id: Identifier
    source_id: Identifier | None = None
    detail: str = Field(min_length=1)


class TrialInitialization(FrozenModel):
    trial_id: Identifier
    status: Literal["inventory_ready", "trial_failed"]
    inventory: TrialSourceInventory
    failure: TrialFailed | None = None


class ProjectInitialization(FrozenModel):
    manifest: ProjectManifest
    trials: tuple[TrialInitialization, ...]
    result_specs: tuple[ResultSpecRevision, ...] = ()
    acquisition_receipts: tuple[AcquisitionReceipt, ...]
    review_findings: tuple[ReviewFinding, ...]


@dataclass(frozen=True)
class _DeclaredDocument:
    path: str
    roles: tuple[SourceRole, ...]
    components: tuple[SourceComponentAnnotation, ...]


def initialize_project(
    project_root: Path,
    *,
    actor: Actor,
    parser: DocumentParser | None = None,
) -> ProjectInitialization:
    """Initialize layout and build an immutable inventory for every Trial folder."""
    root = project_root.resolve()
    input_root = root / "input"
    output_root = root / "output"
    state_root = root / ".rob2"
    for path in (input_root, output_root, state_root):
        path.mkdir(parents=True, exist_ok=True)
    store = ArtifactStore(state_root / "artifacts")
    WorkflowLedger(state_root / "ledger.sqlite3", store)
    parser = parser or LiteParseAdapter()
    configuration = _read_project_configuration(root)
    manifest = ProjectManifest(
        project_name=root.name,
        input_root="input",
        output_root="output",
        state_root=".rob2",
        outcome_targets=tuple(
            str(item["id"]) for item in configuration.get("outcome_targets", ())
        ),
    )
    store.put(manifest.model_dump_json().encode(), "application/json")

    trials: list[TrialInitialization] = []
    receipts: list[AcquisitionReceipt] = []
    findings: list[ReviewFinding] = []
    for trial_path in sorted(path for path in input_root.iterdir() if path.is_dir()):
        trial, trial_receipts, trial_findings = _initialize_trial(trial_path, store, actor, parser)
        trials.append(trial)
        receipts.extend(trial_receipts)
        findings.extend(trial_findings)
    result_specs = _declared_result_specs(
        configuration,
        actor,
        {trial.trial_id for trial in trials},
    )
    return ProjectInitialization(
        manifest=manifest,
        trials=tuple(trials),
        result_specs=result_specs,
        acquisition_receipts=tuple(receipts),
        review_findings=tuple(findings),
    )


def _read_project_configuration(root: Path) -> dict[str, Any]:
    path = root / "rob2.yaml"
    if not path.is_file():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("rob2.yaml must contain a mapping")
    if payload.get("schema_version") != 1:
        raise ValueError("rob2.yaml schema_version must be 1")
    return payload


def _declared_result_specs(
    configuration: dict[str, Any],
    actor: Actor,
    trial_ids: set[str],
) -> tuple[ResultSpecRevision, ...]:
    declared = configuration.get("results", [])
    if not isinstance(declared, list):
        raise ValueError("rob2.yaml results must be a list")
    observed_at = datetime.now(UTC)
    specs = []
    for item in declared:
        if not isinstance(item, dict):
            raise ValueError("each rob2.yaml result must be a mapping")
        result = item.get("result")
        if not isinstance(result, dict):
            raise ValueError("each declared ResultSpec requires a result mapping")
        trial_id = result.get("trial_id")
        if trial_id not in trial_ids:
            raise ValueError(f"declared Result references unknown Trial {trial_id}")
        result_id = str(result.get("result_id", ""))
        digest = hashlib.sha256(
            json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        specs.append(
            ResultSpecRevision(
                entity_id=f"result-spec:{result_id.removeprefix('result:')}",
                revision_id=f"revision:result-spec-{digest}",
                actor=actor,
                observed_at=observed_at,
                result=result,
                estimate=item.get("estimate", {}),
                provenance_note=str(item.get("provenance_note", "")),
            )
        )
    result_ids = [item.result.result_id for item in specs]
    if len(result_ids) != len(set(result_ids)):
        raise ValueError("rob2.yaml Result IDs must be unique")
    return tuple(specs)


def _initialize_trial(
    trial_path: Path,
    store: ArtifactStore,
    actor: Actor,
    parser: DocumentParser,
) -> tuple[TrialInitialization, tuple[AcquisitionReceipt, ...], tuple[ReviewFinding, ...]]:
    trial_slug = _slug(trial_path.name)
    trial_id = f"trial:{trial_slug}"
    declarations = _read_trial_manifest(trial_path)
    paths = _source_paths(trial_path, declarations)
    primary, ambiguous = _choose_primary(trial_path, paths, declarations)
    findings: list[ReviewFinding] = []
    if ambiguous:
        findings.append(
            ReviewFinding(
                kind=ReviewFindingKind.PRIMARY_REPORT_AMBIGUOUS,
                trial_id=trial_id,
                detail=f"Multiple top-level PDFs found; proposed {primary.name if primary else ''}",
            )
        )

    sources: list[SourceDescriptor] = []
    receipts: list[AcquisitionReceipt] = []
    required_failure: SourceDescriptor | None = None
    if primary is None:
        missing = _missing_primary(trial_slug)
        inventory = TrialSourceInventory(
            inventory_id=f"inventory:{trial_slug}-1",
            trial_id=trial_id,
            sources=(missing,),
            coverage_limitations=("required primary report unavailable",),
        )
        failure = TrialFailed(
            trial_id=trial_id,
            reason=TrialFailureReason.REQUIRED_PRIMARY_UNRECOVERABLE,
            detail="No top-level primary-report candidate was supplied",
        )
        return (
            TrialInitialization(
                trial_id=trial_id,
                status="trial_failed",
                inventory=inventory,
                failure=failure,
            ),
            (),
            tuple(findings),
        )
    for index, path in enumerate(paths, start=1):
        relative = path.relative_to(trial_path).as_posix()
        declaration = declarations.get(relative)
        roles, classification = _classify(path, trial_path, declaration, path == primary)
        criticality = _criticality(roles, path == primary)
        source_id = f"source:{trial_slug}-{index}"
        attempted_at = datetime.now(UTC)
        try:
            data = path.read_bytes()
        except OSError as error:
            receipt = AcquisitionReceipt(
                receipt_id=f"receipt:{trial_slug}-{index}",
                source_id=source_id,
                method=AcquisitionMethod.LOCAL_IMPORT,
                origin=relative,
                attempted_at=attempted_at,
                actor=actor.actor_id,
                declared_metadata=(("relative_path", relative),),
                outcome=AcquisitionOutcome.FAILED,
                failure_category=SourceFailureCategory.CORRUPT_OR_UNREADABLE,
            )
            receipts.append(receipt)
            source = SourceDescriptor(
                source_id=source_id,
                title=path.name,
                relative_path=relative,
                roles=roles,
                criticality=criticality,
                classification=classification,
                availability=SourceAvailability.ACQUISITION_FAILED,
                processing=SourceProcessing.NOT_ATTEMPTED,
                acquisition_receipt_ids=(receipt.receipt_id,),
                failure_category=SourceFailureCategory.CORRUPT_OR_UNREADABLE,
            )
            sources.append(source)
            if criticality is SourceCriticality.REQUIRED:
                required_failure = source
            else:
                findings.append(
                    ReviewFinding(
                        kind=ReviewFindingKind.OPTIONAL_SOURCE_ACQUISITION_FAILED,
                        trial_id=trial_id,
                        source_id=source_id,
                        detail=f"{relative}: {error}",
                    )
                )
            continue
        artifact = store.put(data, _media_type(path))
        receipt = AcquisitionReceipt(
            receipt_id=f"receipt:{trial_slug}-{index}",
            source_id=source_id,
            method=AcquisitionMethod.LOCAL_IMPORT,
            origin=relative,
            attempted_at=attempted_at,
            actor=actor.actor_id,
            declared_metadata=(
                ("relative_path", relative),
                ("roles", ",".join(role.value for role in roles)),
            ),
            artifact_hash=artifact.content_hash,
            outcome=AcquisitionOutcome.ACQUIRED,
        )
        receipts.append(receipt)
        parse_records: tuple[ParseRecord, ...] = ()
        coverage: tuple[PageCoverage, ...] = ()
        failure_category: str | None = None
        if path.suffix.lower() == ".pdf":
            try:
                parse_records, coverage = _parse_source(
                    parser,
                    data,
                    source_id,
                    artifact.content_hash,
                    allow_recovery=criticality is SourceCriticality.REQUIRED,
                )
                processing = (
                    SourceProcessing.COVERAGE_LIMITED
                    if any(item.state is CoverageState.COVERAGE_LIMITED for item in coverage)
                    else SourceProcessing.USABLE
                )
            except SourceParseError as error:
                processing = SourceProcessing.FAILED
                failure_category = _parse_failure_category(error)
        else:
            processing = SourceProcessing.FAILED
            failure_category = SourceFailureCategory.UNSUPPORTED_FORMAT

        source = SourceDescriptor(
            source_id=source_id,
            title=path.name,
            relative_path=relative,
            roles=roles,
            criticality=criticality,
            classification=classification,
            availability=SourceAvailability.ACQUIRED,
            processing=processing,
            artifact_hash=artifact.content_hash,
            acquisition_receipt_ids=(receipt.receipt_id,),
            parse_records=parse_records,
            coverage=coverage,
            components=declaration.components if declaration else (),
            failure_category=failure_category,
        )
        sources.append(source)
        primary_has_no_usable_page = (
            criticality is SourceCriticality.REQUIRED
            and processing is SourceProcessing.COVERAGE_LIMITED
            and not any(item.state is CoverageState.TEXT_USABLE for item in coverage)
        )
        if processing is SourceProcessing.FAILED or primary_has_no_usable_page:
            if criticality is SourceCriticality.REQUIRED:
                required_failure = source
            else:
                findings.append(
                    ReviewFinding(
                        kind=ReviewFindingKind.OPTIONAL_SOURCE_PROCESSING_FAILED,
                        trial_id=trial_id,
                        source_id=source_id,
                        detail=f"{relative}: {failure_category}",
                    )
                )

    inventory = TrialSourceInventory(
        inventory_id=f"inventory:{trial_slug}-1",
        trial_id=trial_id,
        sources=tuple(sources),
        coverage_limitations=tuple(
            source.relative_path
            for source in sources
            if source.processing in {SourceProcessing.COVERAGE_LIMITED, SourceProcessing.FAILED}
        ),
    )
    failure = None
    status: Literal["inventory_ready", "trial_failed"] = "inventory_ready"
    if required_failure:
        status = "trial_failed"
        failure = TrialFailed(
            trial_id=trial_id,
            reason=TrialFailureReason.REQUIRED_PRIMARY_UNRECOVERABLE,
            detail=f"Required primary {required_failure.relative_path} could not be parsed",
        )
    return (
        TrialInitialization(
            trial_id=trial_id,
            status=status,
            inventory=inventory,
            failure=failure,
        ),
        tuple(receipts),
        tuple(findings),
    )


def _parse_source(
    parser: DocumentParser,
    data: bytes,
    source_id: Identifier,
    artifact_hash: ContentHash,
    *,
    allow_recovery: bool,
) -> tuple[tuple[ParseRecord, ...], tuple[PageCoverage, ...]]:
    initial = parser.parse(data, ocr_enabled=False)
    recovery_pages = tuple(
        page.page_number
        for page in initial.pages
        if not page.text.strip() and RECOVERY_REASONS.intersection(page.reasons)
    )
    records = [_parse_record(parser, initial, source_id, artifact_hash, False, None, "initial")]
    recovered: Mapping[int, PageExtraction] = {}
    if recovery_pages and allow_recovery:
        recovery = parser.parse(data, ocr_enabled=True, target_pages=recovery_pages)
        recovered = {page.page_number: page for page in recovery.pages}
        records.append(
            _parse_record(
                parser,
                recovery,
                source_id,
                artifact_hash,
                True,
                recovery_pages,
                "recovery",
            )
        )
    coverage = tuple(
        _coverage_for(
            page,
            recovered.get(page.page_number),
            page.page_number in recovery_pages and allow_recovery,
        )
        for page in initial.pages
    )
    return tuple(records), coverage


def _parse_record(
    parser: DocumentParser,
    result: ParserResult,
    source_id: Identifier,
    artifact_hash: ContentHash,
    ocr_enabled: bool,
    target_pages: tuple[int, ...] | None,
    suffix: str,
) -> ParseRecord:
    config = {
        "ocr_enabled": ocr_enabled,
        "include_complexity": True,
        "target_pages": target_pages,
    }
    return ParseRecord(
        parse_id=f"parse:{source_id.removeprefix('source:')}-{suffix}",
        source_id=source_id,
        artifact_hash=artifact_hash,
        parser_name=parser.name,
        parser_version=parser.version,
        configuration_hash=_hash_json(config),
        canonicalization_version=CANONICALIZATION_VERSION,
        output_hash=_hash_bytes(result.raw_output),
        ocr_enabled=ocr_enabled,
        target_pages=target_pages,
        quality_observations=tuple(
            sorted({reason for page in result.pages for reason in page.reasons})
        ),
    )


def _coverage_for(
    initial: PageExtraction,
    recovered: PageExtraction | None,
    recovery_attempted: bool,
) -> PageCoverage:
    reasons = set(initial.reasons)
    if reasons & BLANK_REASONS:
        state = CoverageState.INTENTIONALLY_BLANK
    elif recovered and recovered.text.strip():
        state = CoverageState.TEXT_USABLE
    elif recovery_attempted:
        state = CoverageState.COVERAGE_LIMITED
    elif reasons & RECOVERY_REASONS:
        state = CoverageState.RECOVERY_REQUIRED
    elif reasons & LIMITED_REASONS or "\ufffd" in initial.text:
        state = CoverageState.COVERAGE_LIMITED
    elif reasons & VISUAL_REASONS:
        state = CoverageState.VISUAL_REQUIRED
    elif initial.text.strip():
        state = CoverageState.TEXT_USABLE
    else:
        state = CoverageState.COVERAGE_LIMITED
    return PageCoverage(
        page_index=initial.page_number - 1,
        state=state,
        diagnostics=initial.reasons,
        recovery_attempted=recovery_attempted,
    )


def _read_trial_manifest(trial_path: Path) -> dict[str, _DeclaredDocument]:
    path = trial_path / "trial.yaml"
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    declarations: dict[str, _DeclaredDocument] = {}
    for item in payload.get("documents", ()):
        relative = str(item["path"]).replace("\\", "/")
        resolved = (trial_path / relative).resolve()
        if not resolved.is_relative_to(trial_path.resolve()):
            raise ValueError(f"trial.yaml path escapes Trial folder: {relative}")
        role_values = item.get("roles") or ([item["role"]] if item.get("role") else [])
        roles = tuple(SourceRole(value) for value in role_values)
        components = tuple(
            SourceComponentAnnotation(
                page_start=component["pages"][0],
                page_end=component["pages"][1],
                roles=tuple(SourceRole(value) for value in component["roles"]),
                classification=ClassificationProvenance(
                    authority="explicit_trial_metadata",
                    cues=(relative,),
                    classifier_version=CLASSIFIER_VERSION,
                ),
            )
            for component in item.get("components", ())
        )
        declarations[relative] = _DeclaredDocument(relative, roles, components)
    return declarations


def _source_paths(
    trial_path: Path, declarations: Mapping[str, _DeclaredDocument]
) -> tuple[Path, ...]:
    discovered = {
        path.resolve() for path in trial_path.glob("*.pdf") if path.name.lower() != "trial.yaml"
    }
    supplements = trial_path / "supplements"
    if supplements.is_dir():
        discovered.update(path.resolve() for path in supplements.rglob("*") if path.is_file())
    discovered.update((trial_path / item.path).resolve() for item in declarations.values())
    return tuple(sorted(discovered, key=lambda path: path.relative_to(trial_path).as_posix()))


def _choose_primary(
    trial_path: Path,
    paths: tuple[Path, ...],
    declarations: Mapping[str, _DeclaredDocument],
) -> tuple[Path | None, bool]:
    explicit = [
        trial_path / item.path
        for item in declarations.values()
        if SourceRole.PRIMARY_REPORT in item.roles
    ]
    if len(explicit) > 1:
        raise ValueError("trial.yaml declares multiple primary reports")
    if explicit:
        return explicit[0].resolve(), False
    candidates = [
        path
        for path in paths
        if path.parent == trial_path.resolve() and path.suffix.lower() == ".pdf"
    ]
    if not candidates:
        return None, False
    return candidates[0], len(candidates) > 1


def _missing_primary(trial_slug: str) -> SourceDescriptor:
    return SourceDescriptor(
        source_id=f"source:{trial_slug}-missing-primary",
        title="Required primary report",
        relative_path=".",
        roles=(SourceRole.PRIMARY_REPORT,),
        criticality=SourceCriticality.REQUIRED,
        classification=ClassificationProvenance(
            authority="folder_position",
            cues=("no top-level PDF supplied",),
            classifier_version=CLASSIFIER_VERSION,
        ),
        availability=SourceAvailability.UNAVAILABLE,
        processing=SourceProcessing.NOT_ATTEMPTED,
        failure_category=SourceFailureCategory.CORRUPT_OR_UNREADABLE,
    )


def _classify(
    path: Path,
    trial_path: Path,
    declaration: _DeclaredDocument | None,
    is_primary: bool,
) -> tuple[tuple[SourceRole, ...], ClassificationProvenance]:
    relative = path.relative_to(trial_path).as_posix()
    if declaration and declaration.roles:
        return declaration.roles, ClassificationProvenance(
            authority="explicit_trial_metadata",
            cues=(relative,),
            classifier_version=CLASSIFIER_VERSION,
        )
    if is_primary:
        return (SourceRole.PRIMARY_REPORT,), ClassificationProvenance(
            authority="folder_position",
            cues=("top-level PDF proposed as primary",),
            classifier_version=CLASSIFIER_VERSION,
        )
    if path.parent != trial_path:
        lowered = path.stem.lower()
        role = (
            SourceRole.PROTOCOL
            if "protocol" in lowered
            else SourceRole.STATISTICAL_ANALYSIS_PLAN
            if re.search(r"(^|[-_ ])sap($|[-_ ])", lowered)
            else SourceRole.UNCLASSIFIED_SUPPORTING
        )
        return (role,), ClassificationProvenance(
            authority="folder_position_and_filename",
            cues=("supplements folder", path.name),
            classifier_version=CLASSIFIER_VERSION,
        )
    return (SourceRole.SECONDARY_REPORT,), ClassificationProvenance(
        authority="folder_position",
        cues=("additional top-level PDF",),
        classifier_version=CLASSIFIER_VERSION,
    )


def _criticality(
    roles: tuple[SourceRole, ...],
    is_primary: bool,
) -> SourceCriticality:
    if is_primary:
        return SourceCriticality.REQUIRED
    if SourceRole.PROTOCOL in roles or SourceRole.STATISTICAL_ANALYSIS_PLAN in roles:
        return SourceCriticality.EXPECTED
    return SourceCriticality.OPTIONAL


def _parse_failure_category(error: Exception) -> SourceFailureCategory:
    message = str(error).lower()
    if "password" in message or "encrypt" in message:
        return SourceFailureCategory.ENCRYPTED
    if "malform" in message:
        return SourceFailureCategory.MALFORMED
    return SourceFailureCategory.CORRUPT_OR_UNREADABLE


def _media_type(path: Path) -> str:
    return "application/pdf" if path.suffix.lower() == ".pdf" else "application/octet-stream"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._~-]+", "-", value.lower()).strip("-")
    return slug or "unnamed"


def _hash_bytes(value: bytes) -> ContentHash:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _hash_json(value: object) -> ContentHash:
    return _hash_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
