"""Project-folder discovery, source custody, and coverage-explicit parsing."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import version
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Protocol
from zipfile import BadZipFile, ZipFile

import yaml
from pydantic import AliasChoices, ConfigDict, Field

from rob2_kit.application.preparation import TrialFailed, TrialFailureReason
from rob2_kit.domain.results import ResultSpecRevision, derive_result_spec_revision_id
from rob2_kit.domain.revisions import Actor, ContentHash, FrozenModel, Identifier
from rob2_kit.domain.sources import (
    AcquisitionMethod,
    AcquisitionOutcome,
    AcquisitionReceipt,
    ClassificationProvenance,
    CoverageState,
    PageCoverage,
    ParseRecord,
    ParserQualityPolicy,
    SourceAvailability,
    SourceComponentAnnotation,
    SourceCriticality,
    SourceDescriptor,
    SourceFailureCategory,
    SourceProcessing,
    SourceRole,
    TrialSourceInventory,
)
from rob2_kit.registry import (
    RegistryAcquisition,
    RegistryAcquisitionStatus,
    RegistryCandidate,
    RegistrySourceText,
)
from rob2_kit.storage import ArtifactStore, WorkflowLedger

CLASSIFIER_VERSION = "source-classifier:1.0.0"
CANONICALIZATION_VERSION = "liteparse-adapter:2.2.0"
PARSER_QUALITY_POLICY = ParserQualityPolicy()
RECOVERY_POLICY_RELEASE = "policy:source-recovery-1.0.0"
RECOVERY_REASONS = frozenset(PARSER_QUALITY_POLICY.recovery_reasons)
LIMITED_REASONS = frozenset(PARSER_QUALITY_POLICY.limited_reasons)
BLANK_REASONS = frozenset(PARSER_QUALITY_POLICY.blank_reasons)
VISUAL_REASONS = frozenset(PARSER_QUALITY_POLICY.visual_reasons)
DEFAULT_ZIP_MAX_MEMBERS = 100
DEFAULT_ZIP_MAX_EXPANDED_BYTES = 100 * 1024 * 1024
LITEPARSE_CONFIGURATION: dict[str, object] = {
    "include_complexity": True,
    "emit_word_boxes": True,
    "extract_content_bounds": True,
    "extract_form_fields": True,
    "extract_structure_tree": True,
    "extract_text_metadata": True,
    "keep_headers_footers": False,
    "render_form_fields": False,
    "quiet": True,
}


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


class PageWord(FrozenModel):
    """One LiteParse word box in its 72-DPI, top-left coordinate space."""

    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float | None = None


class PageTextItem(FrozenModel):
    """Spatial text retained from LiteParse without exposing parser objects."""

    text: str
    x: float
    y: float
    width: float
    height: float
    words: tuple[PageWord, ...] = ()
    rotation: float = 0.0
    confidence: float | None = None
    # A parser-native fragment identity, when supplied.  It is deliberately
    # opaque: ingestion preserves it for canonical lineage rather than using
    # it to infer semantic role or reading order.
    fragment_id: Identifier | None = Field(
        default=None,
        validation_alias=AliasChoices("fragment_id", "id", "fragment_identifier"),
    )
    # Structure metadata is optional because LiteParse versions and custom
    # parser adapters may expose different levels of reconstruction.  Unknown
    # values remain explicit diagnostics rather than being guessed as prose.
    unit_kind: str | None = Field(
        default=None,
        validation_alias=AliasChoices("unit_kind", "kind"),
    )
    trial_id: Identifier | None = None
    result_id: Identifier | None = None
    domain_id: Identifier | None = None
    question_ids: tuple[Identifier, ...] = ()
    table_headers: tuple[str, ...] = ()
    caption: str | None = None
    applicability: str | None = None
    applicable_result_ids: tuple[Identifier, ...] = ()
    section_path: tuple[str, ...] = ()
    hierarchy_path: tuple[str, ...] = ()
    reading_order: int = Field(default=0, ge=0)
    document_zone: str | None = Field(
        default=None,
        validation_alias=AliasChoices("document_zone", "zone"),
    )
    discourse_scope: str | None = Field(
        default=None,
        validation_alias=AliasChoices("discourse_scope", "trial_scope"),
    )


class PageExtraction(FrozenModel):
    page_number: int = Field(ge=1)
    parse_id: Identifier | None = None
    markdown: str = ""
    # Optional parser-native structure tree. LiteParse versions differ in
    # whether this is exposed; retain only JSON-shaped data and fail closed
    # when unavailable rather than fabricating semantic labels.
    structure_tree: dict[str, Any] | None = None
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    text: str
    reasons: tuple[str, ...] = ()
    text_items: tuple[PageTextItem, ...] = ()
    content_bounds: tuple[float, float, float, float] | None = None
    has_form_fields: bool = False
    section_path: tuple[str, ...] = ()
    hierarchy_path: tuple[str, ...] = ()
    document_zone: str | None = Field(
        default=None,
        validation_alias=AliasChoices("document_zone", "zone"),
    )
    discourse_scope: str | None = Field(
        default=None,
        validation_alias=AliasChoices("discourse_scope", "trial_scope"),
    )


class ParserResult(FrozenModel):
    pages: tuple[PageExtraction, ...]
    raw_output: bytes


class PageRender(FrozenModel):
    """Immutable LiteParse base render retained for visual citation routing."""

    page_number: int = Field(ge=1)
    dpi: float = Field(gt=0)
    pixel_width: int = Field(gt=0)
    pixel_height: int = Field(gt=0)
    image_hash: ContentHash
    image_bytes: bytes
    media_type: str = "image/png"


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

    def screenshot(
        self,
        data: bytes,
        *,
        page_numbers: tuple[int, ...],
        dpi: int,
    ) -> tuple[PageRender, ...]: ...


def _content_bounds(page: Any) -> tuple[float, float, float, float] | None:
    bounds = getattr(page, "content_bounds", None)
    if bounds is None:
        return None
    if len(bounds) != 4:
        raise SourceParseError("LiteParse returned invalid content bounds")
    return (
        float(bounds[0]),
        float(bounds[1]),
        float(bounds[2]),
        float(bounds[3]),
    )


def _optional_metadata(value: object) -> str | None:
    """Normalize optional parser labels without turning None into ``"None"``."""

    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


class LiteParseAdapter:
    """Convert LiteParse's version-specific objects to stable ingestion records."""

    name = "liteparse"

    @property
    def configuration(self) -> dict[str, object]:
        """Return the resolved non-volatile LiteParse configuration."""

        return dict(LITEPARSE_CONFIGURATION)

    def __init__(self) -> None:
        self.version = version("liteparse")

    def parse(
        self,
        data: bytes,
        *,
        ocr_enabled: bool,
        target_pages: tuple[int, ...] | None = None,
    ) -> ParserResult:
        from liteparse import LiteParse, ParseError

        target = None if target_pages is None else ",".join(str(page) for page in target_pages)
        options: dict[str, Any] = {
            "ocr_enabled": ocr_enabled,
            "include_complexity": True,
            "target_pages": target,
            "quiet": True,
        }
        # Keep compatibility with small test doubles and older adapters while
        # enabling every spatial/form-safety option exposed by LiteParse 2.10.
        try:
            supported = inspect.signature(LiteParse).parameters
        except (TypeError, ValueError):
            supported = {}
        options.update(
            {key: value for key, value in LITEPARSE_CONFIGURATION.items() if key in supported}
        )
        try:
            parsed = LiteParse(**options).parse(data)
        except (ParseError, ValueError) as error:
            raise SourceParseError(str(error)) from error
        pages = tuple(
            PageExtraction(
                page_number=page.page_num,
                width=page.width,
                height=page.height,
                text=page.text,
                markdown=str(getattr(page, "markdown", "") or ""),
                structure_tree=(
                    getattr(page, "structure_tree", None)
                    if isinstance(getattr(page, "structure_tree", None), dict)
                    else None
                ),
                reasons=tuple(page.complexity.reasons if page.complexity else ()),
                text_items=tuple(
                    PageTextItem(
                        text=item.text,
                        x=item.x,
                        y=item.y,
                        width=item.width,
                        height=item.height,
                        words=tuple(
                            PageWord(
                                text=word.text,
                                x=word.x,
                                y=word.y,
                                width=word.width,
                                height=word.height,
                                confidence=getattr(word, "confidence", None),
                            )
                            for word in getattr(item, "words", ())
                        ),
                        rotation=float(getattr(item, "rotation", 0.0) or 0.0),
                        confidence=getattr(item, "confidence", None),
                        fragment_id=_optional_metadata(
                            getattr(
                                item,
                                "fragment_id",
                                getattr(item, "fragment_identifier", getattr(item, "id", None)),
                            )
                        ),
                        unit_kind=_optional_metadata(
                            getattr(item, "unit_kind", getattr(item, "kind", None))
                        ),
                        trial_id=_optional_metadata(getattr(item, "trial_id", None)),
                        result_id=_optional_metadata(getattr(item, "result_id", None)),
                        domain_id=_optional_metadata(getattr(item, "domain_id", None)),
                        question_ids=tuple(getattr(item, "question_ids", ()) or ()),
                        table_headers=tuple(getattr(item, "table_headers", ()) or ()),
                        caption=_optional_metadata(getattr(item, "caption", None)),
                        applicability=_optional_metadata(getattr(item, "applicability", None)),
                        applicable_result_ids=tuple(
                            getattr(item, "applicable_result_ids", ()) or ()
                        ),
                        section_path=tuple(getattr(item, "section_path", ()) or ()),
                        hierarchy_path=tuple(getattr(item, "hierarchy_path", ()) or ()),
                        reading_order=int(getattr(item, "reading_order", 0) or 0),
                        document_zone=_optional_metadata(
                            getattr(item, "document_zone", getattr(item, "zone", None))
                        ),
                        discourse_scope=_optional_metadata(
                            getattr(item, "discourse_scope", getattr(item, "trial_scope", None))
                        ),
                    )
                    for item in getattr(page, "text_items", ())
                ),
                content_bounds=_content_bounds(page),
                has_form_fields=bool(getattr(page, "form_fields", None)),
                section_path=tuple(getattr(page, "section_path", ()) or ()),
                hierarchy_path=tuple(getattr(page, "hierarchy_path", ()) or ()),
                document_zone=_optional_metadata(
                    getattr(page, "document_zone", getattr(page, "zone", None))
                ),
                discourse_scope=_optional_metadata(
                    getattr(page, "discourse_scope", getattr(page, "trial_scope", None))
                ),
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
                        "markdown": page.markdown,
                        "structure_tree": page.structure_tree,
                        "reasons": page.reasons,
                        "text_items": [
                            {
                                "text": item.text,
                                "x": item.x,
                                "y": item.y,
                                "width": item.width,
                                "height": item.height,
                                "words": [word.model_dump(mode="json") for word in item.words],
                                "rotation": item.rotation,
                                "confidence": item.confidence,
                                "fragment_id": item.fragment_id,
                                "unit_kind": item.unit_kind,
                                "section_path": item.section_path,
                                "hierarchy_path": item.hierarchy_path,
                                "reading_order": item.reading_order,
                                "trial_id": item.trial_id,
                                "result_id": item.result_id,
                                "domain_id": item.domain_id,
                                "question_ids": item.question_ids,
                                "table_headers": item.table_headers,
                                "caption": item.caption,
                                "applicability": item.applicability,
                                "applicable_result_ids": item.applicable_result_ids,
                                "document_zone": item.document_zone,
                                "discourse_scope": item.discourse_scope,
                            }
                            for item in page.text_items
                        ],
                        "content_bounds": page.content_bounds,
                        "has_form_fields": page.has_form_fields,
                        "section_path": page.section_path,
                        "hierarchy_path": page.hierarchy_path,
                        "document_zone": page.document_zone,
                        "discourse_scope": page.discourse_scope,
                    }
                    for page in pages
                ]
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return ParserResult(pages=pages, raw_output=raw)

    def screenshot(
        self,
        data: bytes,
        *,
        page_numbers: tuple[int, ...],
        dpi: int,
    ) -> tuple[PageRender, ...]:
        """Render selected pages through LiteParse's pinned PNG surface.

        LiteParse's screenshot API is path-based even though ``parse`` accepts
        bytes.  The temporary path is confined to the process and removed
        immediately; callers receive immutable bytes plus a content hash.
        """

        if dpi not in {144, 180, 216}:
            raise ValueError("screenshot DPI must be one of 144, 180, or 216")
        if not page_numbers or any(page < 1 for page in page_numbers):
            raise ValueError("screenshot page numbers must be one-based")
        from liteparse import LiteParse, ParseError

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
                temporary.write(data)
                temporary.flush()
                temporary_path = Path(temporary.name)
            screenshots = LiteParse(
                dpi=float(dpi),
                quiet=True,
                render_form_fields=False,
            ).screenshot(temporary_path, page_numbers=list(page_numbers))
        except (OSError, ParseError, ValueError) as error:
            raise SourceParseError(str(error)) from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        result: list[PageRender] = []
        for screenshot in screenshots:
            image = bytes(screenshot.image_bytes)
            result.append(
                PageRender(
                    page_number=screenshot.page_num,
                    dpi=float(dpi),
                    pixel_width=screenshot.width,
                    pixel_height=screenshot.height,
                    image_hash=_hash_bytes(image),
                    image_bytes=image,
                )
            )
        returned_pages = tuple(item.page_number for item in result)
        if returned_pages != tuple(page_numbers):
            raise SourceParseError("LiteParse screenshot output did not preserve requested pages")
        return tuple(result)


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
        "policy:parser-quality-1.0.0",
    )
    export_preferences: tuple[str, ...] = ("json", "markdown", "html")
    archive_preference: str = "complete"
    # The stable method fields are kept alongside the historical ``supported_scope``
    # string so callers can validate the fixed RoB 2 boundary without parsing YAML.
    method_version: str = "2019-08-22"
    effect_of_interest: str = "assignment"
    outcome_target_specs: tuple[OutcomeTarget, ...] = ()


class OutcomeTarget(FrozenModel):
    """Project-level outcome intent used to propose Trial-specific Results."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_by_name=True,
        serialize_by_alias=True,
    )

    target_id: Identifier
    label: str = Field(min_length=1)
    outcome_construct: str | None = Field(default=None, alias="construct")
    time_point: str | None = None
    accepted_effect_measures: tuple[str, ...] = ()
    accepted_instruments: tuple[str, ...] = ()
    effect_of_interest: str | None = None


class ResultCandidate(FrozenModel):
    """Engine-issued mapping candidate for one Trial × Outcome target."""

    candidate_id: Identifier
    trial_id: Identifier
    outcome_target_id: Identifier | None = None
    result_id: Identifier | None = None
    label: str = Field(min_length=1)
    source_locator: str | None = None
    status: Literal["resolved", "needs_input"]


class SourceRoleCandidate(FrozenModel):
    """Engine-issued advisory candidate for one Source's role(s).

    ``roles`` is the classifier's proposed cue, carried alongside its
    ``classification`` provenance (authority, cues, classifier version). It
    never binds ``SourceDescriptor.roles`` by itself; only an accepted
    ``RunProposalSelection`` (matched by ``source_id``) does.
    """

    candidate_id: Identifier
    trial_id: Identifier
    source_id: Identifier
    roles: tuple[SourceRole, ...]
    classification: ClassificationProvenance


class InitializationDiagnosticKind(StrEnum):
    PRIMARY_REPORT_AMBIGUOUS = "primary_report_ambiguous"
    TRIAL_FAILED = "trial_failed"
    OPTIONAL_SOURCE_ACQUISITION_FAILED = "optional_source_acquisition_failed"
    OPTIONAL_SOURCE_PROCESSING_FAILED = "optional_source_processing_failed"
    REGISTRY_CANDIDATES = "registry_candidates"
    REGISTRY_UNAVAILABLE = "registry_unavailable"
    REGISTRY_ACQUISITION_FAILED = "registry_acquisition_failed"
    CONFLICTING_REGISTRY_IDENTIFIERS = "conflicting_registry_identifiers"


class InitializationDiagnostic(FrozenModel):
    kind: InitializationDiagnosticKind
    trial_id: Identifier
    source_id: Identifier | None = None
    detail: str = Field(min_length=1)


class TrialInitialization(FrozenModel):
    trial_id: Identifier
    status: Literal["inventory_ready", "trial_failed"]
    inventory: TrialSourceInventory
    failure: TrialFailed | None = None
    registry_acquisition: RegistryAcquisition | None = None
    registry_candidates: tuple[RegistryCandidate, ...] = ()


class ProjectInitialization(FrozenModel):
    manifest: ProjectManifest
    trials: tuple[TrialInitialization, ...]
    result_specs: tuple[ResultSpecRevision, ...] = ()
    acquisition_receipts: tuple[AcquisitionReceipt, ...]
    diagnostics: tuple[InitializationDiagnostic, ...]
    registry_candidates: tuple[RegistryCandidate, ...] = ()
    result_candidates: tuple[ResultCandidate, ...] = ()
    source_role_candidates: tuple[SourceRoleCandidate, ...] = ()


@dataclass(frozen=True)
class _DeclaredDocument:
    path: str
    roles: tuple[SourceRole, ...]
    components: tuple[SourceComponentAnnotation, ...]
    decision_relevant_pages: tuple[int, ...] = ()


def initialize_project(
    project_root: Path,
    *,
    actor: Actor,
    parser: DocumentParser | None = None,
    registry_adapter: Any | None = None,
    registry: Any | None = None,
    allow_unknown_result_trials: bool = False,
    now: Callable[[], datetime] | None = None,
) -> ProjectInitialization:
    """Initialize layout and build an immutable inventory for every Trial folder."""
    clock = now or (lambda: datetime.now(UTC))
    root = project_root.resolve()
    input_root = root / "input"
    output_root = root / "output"
    state_root = root / ".rob2"
    _validate_project_tree(root, (input_root, output_root, state_root))
    configuration = _read_project_configuration(root)
    _validate_method_configuration(configuration)
    for path in (input_root, output_root, state_root):
        if path.is_symlink():
            raise ValueError(f"project state symlinks are not permitted: {path}")
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"project state path escapes project root: {path}")
        path.mkdir(parents=True, exist_ok=True)
    store = ArtifactStore(state_root / "artifacts")
    WorkflowLedger(state_root / "ledger.sqlite3", store)
    parser = parser or LiteParseAdapter()
    registry_adapter = registry_adapter or registry
    registry_enabled = _registry_enabled(configuration)
    outcome_target_specs = _outcome_target_specs(configuration)
    declared_outcomes = configuration.get("outcome_targets") or ()
    manifest = ProjectManifest(
        project_name=root.name,
        input_root="input",
        output_root="output",
        state_root=".rob2",
        outcome_targets=tuple(str(item["id"]) for item in declared_outcomes),
        supported_scope=_supported_scope(configuration),
        method_version=_method_version(configuration),
        effect_of_interest=_effect_of_interest(configuration),
        outcome_target_specs=outcome_target_specs,
    )
    store.put(manifest.model_dump_json().encode(), "application/json")

    trials: list[TrialInitialization] = []
    receipts: list[AcquisitionReceipt] = []
    findings: list[InitializationDiagnostic] = []
    registry_candidates: list[RegistryCandidate] = []
    input_root_resolved = input_root.resolve()
    trial_paths: list[Path] = []
    for path in input_root.iterdir():
        if not path.is_dir():
            continue
        if path.is_symlink():
            raise ValueError(f"Trial directory symlinks are not permitted: {path}")
        resolved = path.resolve()
        if not resolved.is_relative_to(input_root_resolved):
            raise ValueError(f"Trial directory escapes input root: {path}")
        trial_paths.append(resolved)
    for trial_path in sorted(trial_paths):
        trial, trial_receipts, trial_findings = _initialize_trial(
            trial_path, store, actor, parser, now=clock
        )
        if registry_adapter is not None and registry_enabled and trial.status != "trial_failed":
            trial, registry_receipt, registry_finding = _initialize_registry(
                trial_path,
                trial,
                store,
                actor,
                parser,
                registry_adapter=registry_adapter,
                now=clock,
            )
            if registry_receipt is not None:
                trial_receipts = trial_receipts + (registry_receipt,)
            trial_findings = trial_findings + registry_finding
        trials.append(trial)
        receipts.extend(trial_receipts)
        findings.extend(trial_findings)
        registry_candidates.extend(trial.registry_candidates)
    result_specs = _declared_result_specs(
        configuration,
        actor,
        {trial.trial_id for trial in trials},
        allow_unknown_trial_refs=allow_unknown_result_trials,
        now=clock,
    )
    result_candidates = _result_candidates(tuple(trials), result_specs, outcome_target_specs)
    source_role_candidates = _source_role_candidates(tuple(trials))
    return ProjectInitialization(
        manifest=manifest,
        trials=tuple(trials),
        result_specs=result_specs,
        acquisition_receipts=tuple(receipts),
        diagnostics=tuple(findings),
        registry_candidates=tuple(registry_candidates),
        result_candidates=result_candidates,
        source_role_candidates=source_role_candidates,
    )


def _read_project_configuration(root: Path) -> dict[str, Any]:
    path = root / "rob2.yaml"
    if path.is_symlink():
        raise ValueError(f"rob2.yaml symlinks are not permitted: {path}")
    if not path.is_file():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("rob2.yaml must contain a mapping")
    if payload.get("schema_version") != 1:
        raise ValueError("rob2.yaml schema_version must be 1")
    return payload


def _validate_project_tree(root: Path, paths: tuple[Path, ...]) -> None:
    """Reject all confined-tree symlinks before any derived-state mutation."""

    for path in paths:
        if path.is_symlink():
            raise ValueError(f"project path symlinks are not permitted: {path}")
        if not path.exists():
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"project path escapes project root: {path}")
        if not path.is_dir():
            raise ValueError(f"project path must be a directory: {path}")
        for nested in path.rglob("*"):
            if nested.is_symlink():
                raise ValueError(f"project path symlinks are not permitted: {nested}")
            if not nested.resolve().is_relative_to(root):
                raise ValueError(f"project path escapes project root: {nested}")


SUPPORTED_METHOD_VERSION = "2019-08-22"
SUPPORTED_VARIANT = "individually-randomized-parallel"
SUPPORTED_EFFECT = "assignment"


def _rob2_configuration(configuration: Mapping[str, Any]) -> Mapping[str, Any]:
    value = configuration.get("rob2", {})
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("rob2.yaml rob2 must be a mapping")
    return value


def _method_version(configuration: Mapping[str, Any]) -> str:
    value = _rob2_configuration(configuration).get("version", SUPPORTED_METHOD_VERSION)
    normalized = str(value)
    # The project documents the release by date while packs use a dotted label.
    if normalized in {"2019", "2019.1", "2019-08-22", "22 August 2019"}:
        return SUPPORTED_METHOD_VERSION
    return normalized


def _effect_of_interest(configuration: Mapping[str, Any]) -> str:
    return str(_rob2_configuration(configuration).get("effect_of_interest", SUPPORTED_EFFECT))


def _supported_scope(configuration: Mapping[str, Any]) -> str:
    explicit = configuration.get("supported_scope")
    if explicit is not None:
        return str(explicit)
    variant = str(_rob2_configuration(configuration).get("variant", SUPPORTED_VARIANT))
    return f"rob2:{variant}"


def _validate_method_configuration(configuration: Mapping[str, Any]) -> None:
    method = _method_version(configuration)
    scope = _supported_scope(configuration)
    variant = scope.removeprefix("rob2:")
    effect = _effect_of_interest(configuration)
    if method != SUPPORTED_METHOD_VERSION:
        raise ValueError(
            "unsupported RoB 2 method version "
            f"{method!r}; supported method is {SUPPORTED_METHOD_VERSION!r}"
        )
    if scope != f"rob2:{SUPPORTED_VARIANT}" or variant != SUPPORTED_VARIANT:
        raise ValueError(
            f"unsupported RoB 2 trial design {variant!r}; supported design is {SUPPORTED_VARIANT!r}"
        )
    if effect != SUPPORTED_EFFECT:
        raise ValueError(
            "unsupported RoB 2 effect of interest "
            f"{effect!r}; supported effect is {SUPPORTED_EFFECT!r}"
        )


def _registry_enabled(configuration: Mapping[str, Any]) -> bool:
    acquisition = configuration.get("acquisition", {})
    if acquisition is None:
        return True
    if not isinstance(acquisition, Mapping):
        raise ValueError("rob2.yaml acquisition must be a mapping")
    value = acquisition.get("clinicaltrials_gov", True)
    if not isinstance(value, bool):
        raise ValueError("rob2.yaml acquisition.clinicaltrials_gov must be boolean")
    return value


def _outcome_target_specs(configuration: Mapping[str, Any]) -> tuple[OutcomeTarget, ...]:
    declared = configuration.get("outcome_targets", ())
    if declared == () or declared is None:
        return ()
    if not isinstance(declared, list):
        raise ValueError("rob2.yaml outcome_targets must be a list")
    targets: list[OutcomeTarget] = []
    seen: set[str] = set()
    for item in declared:
        if not isinstance(item, Mapping):
            raise ValueError("each outcome target must be a mapping")
        target_id = str(item.get("id", ""))
        if not target_id:
            raise ValueError("each outcome target requires an id")
        if target_id in seen:
            raise ValueError(f"outcome target IDs must be unique: {target_id}")
        seen.add(target_id)
        target_effect = item.get("effect_of_interest")
        if target_effect is not None and str(target_effect) != SUPPORTED_EFFECT:
            raise ValueError(
                "unsupported RoB 2 Outcome target effect of interest "
                f"{target_effect!r}; supported effect is {SUPPORTED_EFFECT!r}"
            )
        targets.append(
            OutcomeTarget(
                target_id=f"outcome-target:{target_id}",
                label=str(item.get("label", target_id)),
                construct=(str(item["construct"]) if item.get("construct") is not None else None),
                time_point=(
                    str(item["timepoint"])
                    if item.get("timepoint") is not None
                    else (str(item["time_point"]) if item.get("time_point") is not None else None)
                ),
                accepted_effect_measures=tuple(
                    str(value) for value in item.get("accepted_effect_measures", ())
                ),
                accepted_instruments=tuple(
                    str(value) for value in item.get("accepted_instruments", ())
                ),
                effect_of_interest=(
                    str(item["effect_of_interest"])
                    if item.get("effect_of_interest") is not None
                    else None
                ),
            )
        )
    return tuple(targets)


def _result_candidates(
    trials: tuple[TrialInitialization, ...],
    result_specs: tuple[ResultSpecRevision, ...],
    outcome_targets: tuple[OutcomeTarget, ...],
) -> tuple[ResultCandidate, ...]:
    candidates: list[ResultCandidate] = []
    by_trial_target: set[tuple[str, str]] = set()
    for spec in result_specs:
        result = spec.result
        matching_targets: list[OutcomeTarget] = []
        for target in outcome_targets:
            construct_match = (
                target.outcome_construct is None
                or target.outcome_construct.casefold() in result.outcome_construct.casefold()
            )
            time_match = target.time_point is None or target.time_point.casefold() in (
                result.time_point.casefold()
            )
            effect_match = not target.accepted_effect_measures or any(
                value.casefold() in result.effect_measure.casefold()
                for value in target.accepted_effect_measures
            )
            effect_of_interest_match = (
                result.effect_of_interest == SUPPORTED_EFFECT
                and target.effect_of_interest in {None, SUPPORTED_EFFECT}
            )
            instrument_match = not target.accepted_instruments or any(
                value.casefold() in result.measurement_instrument.casefold()
                for value in target.accepted_instruments
            )
            if (
                construct_match
                and time_match
                and effect_match
                and effect_of_interest_match
                and instrument_match
            ):
                matching_targets.append(target)
                by_trial_target.add((result.trial_id, target.target_id))
        targets = matching_targets or [None]
        for target in targets:
            target_key = target.target_id if target is not None else "unmatched"
            digest = hashlib.sha256(
                f"{result.result_id}|{spec.revision_id}|{target_key}".encode()
            ).hexdigest()[:24]
            candidates.append(
                ResultCandidate(
                    candidate_id=f"result-candidate:{digest}",
                    trial_id=result.trial_id,
                    outcome_target_id=(target.target_id if target is not None else None),
                    result_id=result.result_id,
                    label=(
                        f"{result.outcome_construct} at {result.time_point} "
                        f"({result.effect_measure}, {result.analysis_population})"
                    ),
                    source_locator=result.source_locator,
                    status="resolved",
                )
            )
    # Outcome targets are project-level intents.  If no exact ResultSpec was
    # declared for a Trial, expose a needs_input candidate rather than
    # fabricating a Result identity or silently dropping the target.
    for trial in trials:
        if trial.status == "trial_failed":
            # A failed Trial receives a diagnostic terminal outcome during
            # Run preparation; it must not create an agent-mapping ambiguity
            # or enter the normal Result assessment queue.
            continue
        for target in outcome_targets:
            if (trial.trial_id, target.target_id) in by_trial_target:
                continue
            digest = hashlib.sha256(f"{trial.trial_id}|{target.target_id}".encode()).hexdigest()[
                :24
            ]
            candidates.append(
                ResultCandidate(
                    candidate_id=f"result-candidate:{digest}",
                    trial_id=trial.trial_id,
                    outcome_target_id=target.target_id,
                    result_id=f"result:{digest}",
                    label=target.label,
                    status="needs_input",
                )
            )
    return tuple(candidates)


def _source_role_candidates(
    trials: tuple[TrialInitialization, ...],
) -> tuple[SourceRoleCandidate, ...]:
    """Expose every classified Source's role(s) as a reviewable candidate.

    Registry sources are excluded: their role is assigned deterministically
    by acquisition (see ``_registry_source_descriptor``), not by the
    filename/folder heuristic this candidate exists to make advisory.
    """

    candidates: list[SourceRoleCandidate] = []
    for trial in trials:
        if trial.status == "trial_failed":
            continue
        for source in trial.inventory.sources:
            if SourceRole.REGISTRY_CURRENT in source.roles:
                continue
            digest = hashlib.sha256(f"{source.source_id}|{trial.trial_id}".encode()).hexdigest()[
                :24
            ]
            candidates.append(
                SourceRoleCandidate(
                    candidate_id=f"source-role-candidate:{digest}",
                    trial_id=trial.trial_id,
                    source_id=source.source_id,
                    roles=source.roles,
                    classification=source.classification,
                )
            )
    return tuple(candidates)


def _declared_result_specs(
    configuration: dict[str, Any],
    actor: Actor,
    trial_ids: set[str],
    *,
    allow_unknown_trial_refs: bool = False,
    now: Callable[[], datetime] | None = None,
) -> tuple[ResultSpecRevision, ...]:
    declared = configuration.get("results", [])
    if not isinstance(declared, list):
        raise ValueError("rob2.yaml results must be a list")
    observed_at = (now or (lambda: datetime.now(UTC)))()
    specs = []
    for item in declared:
        if not isinstance(item, dict):
            raise ValueError("each rob2.yaml result must be a mapping")
        result = item.get("result")
        if not isinstance(result, dict):
            raise ValueError("each declared ResultSpec requires a result mapping")
        trial_id = result.get("trial_id")
        if trial_id is not None:
            trial_id = str(trial_id)
            if not trial_id.startswith("trial:"):
                trial_id = f"trial:{trial_id}"
            result = {**result, "trial_id": trial_id}
        effect_of_interest = str(result.get("effect_of_interest", SUPPORTED_EFFECT))
        if effect_of_interest != SUPPORTED_EFFECT:
            raise ValueError(
                "unsupported RoB 2 Result effect of interest "
                f"{effect_of_interest!r}; supported effect is {SUPPORTED_EFFECT!r}"
            )
        if trial_id not in trial_ids and not allow_unknown_trial_refs:
            raise ValueError(f"declared Result references unknown Trial {trial_id}")
        result_id = str(result.get("result_id", ""))
        entity_id = f"result-spec:{result_id.removeprefix('result:')}"
        # A ResultSpec revision binds every caller-authored revision field.
        # In particular, an identical declaration observed later is a distinct
        # immutable observation, not a re-use of the earlier revision ID.
        # ``revision_id`` is deliberately absent from its own preimage.
        preimage = {
            "schema_version": item.get("schema_version", "1.0.0"),
            "entity_id": entity_id,
            "dependencies": item.get("dependencies", ()),
            "actor": actor.model_dump(mode="json"),
            "observed_at": observed_at.isoformat(),
            "supersedes": item.get("supersedes"),
            "result": result,
            "estimate": item.get("estimate", {}),
            "provenance_note": str(item.get("provenance_note", "")),
            "analysis_priority": item.get("analysis_priority"),
            "preference_source_locator": item.get("preference_source_locator"),
        }
        normalized = ResultSpecRevision(
            **preimage,
            revision_id="revision:result-spec-pending",
        )
        normalized_preimage = normalized.model_dump(mode="json", exclude={"revision_id"})
        specs.append(
            normalized.model_copy(
                update={"revision_id": derive_result_spec_revision_id(normalized_preimage)}
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
    *,
    now: Callable[[], datetime] | None = None,
) -> tuple[
    TrialInitialization,
    tuple[AcquisitionReceipt, ...],
    tuple[InitializationDiagnostic, ...],
]:
    trial_slug = _slug(trial_path.name)
    trial_id = f"trial:{trial_slug}"
    declarations = _read_trial_manifest(trial_path)
    paths = _source_paths(trial_path, declarations)
    primary, ambiguous = _choose_primary(trial_path, paths, declarations)
    findings: list[InitializationDiagnostic] = []
    if ambiguous:
        findings.append(
            InitializationDiagnostic(
                kind=InitializationDiagnosticKind.PRIMARY_REPORT_AMBIGUOUS,
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
        findings.append(
            InitializationDiagnostic(
                kind=InitializationDiagnosticKind.TRIAL_FAILED,
                trial_id=trial_id,
                detail=failure.detail,
            )
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
        attempted_at = (now or (lambda: datetime.now(UTC)))()
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
                    InitializationDiagnostic(
                        kind=InitializationDiagnosticKind.OPTIONAL_SOURCE_ACQUISITION_FAILED,
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
                    artifact_store=store,
                    allow_recovery=(
                        criticality is SourceCriticality.REQUIRED
                        or bool(declaration and declaration.decision_relevant_pages)
                    ),
                    relevant_pages=(declaration.decision_relevant_pages if declaration else ()),
                )
                processing = (
                    SourceProcessing.COVERAGE_LIMITED
                    if any(
                        item.state
                        in {
                            CoverageState.COVERAGE_LIMITED,
                            CoverageState.RECOVERY_REQUIRED,
                            CoverageState.VISUAL_REQUIRED,
                        }
                        for item in coverage
                    )
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
                    InitializationDiagnostic(
                        kind=InitializationDiagnosticKind.OPTIONAL_SOURCE_PROCESSING_FAILED,
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
        findings.append(
            InitializationDiagnostic(
                kind=InitializationDiagnosticKind.TRIAL_FAILED,
                trial_id=trial_id,
                detail=failure.detail,
            )
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


def _initialize_registry(
    trial_path: Path,
    trial: TrialInitialization,
    store: ArtifactStore,
    actor: Actor,
    parser: DocumentParser,
    *,
    now: Callable[[], datetime] | None = None,
    registry_adapter: Any,
) -> tuple[TrialInitialization, AcquisitionReceipt | None, tuple[InitializationDiagnostic, ...]]:
    """Resolve one Trial's declared/discovered NCT through the bounded adapter.

    The adapter is injected at this seam so tests can replay recorded registry
    responses.  The normal RunEngine supplies the ClinicalTrials.gov adapter;
    no arbitrary URL or registry client can enter the ingestion model.
    """

    declared_nct = _declared_trial_nct(trial_path)
    adapter_nct = declared_nct.upper() if declared_nct is not None else None
    source_texts: list[RegistrySourceText] = []
    for source in trial.inventory.sources:
        if source.artifact_hash is None or not source.parse_records:
            continue
        try:
            parsed = parser.parse(store.read(source.artifact_hash), ocr_enabled=False)
        except SourceParseError:
            continue
        for page in parsed.pages:
            text = page.text.strip()
            if text:
                source_texts.append(
                    RegistrySourceText(
                        locator=f"{source.relative_path}#page={page.page_number}",
                        text=text,
                    )
                )

    exact_identifier_present = declared_nct is not None or any(
        re.search(r"\bNCT\d{8}\b", item.text, re.IGNORECASE) for item in source_texts
    )
    meaningful_search_text = sum(len(item.text) for item in source_texts) >= 20
    adapter_source_texts = (
        tuple(source_texts) if exact_identifier_present or meaningful_search_text else ()
    )
    acquisition = registry_adapter.acquire(
        declared_nct_id=adapter_nct,
        source_texts=adapter_source_texts,
    )
    candidates = _registry_candidates(
        trial.trial_id,
        acquisition,
        declared_nct_id=declared_nct,
    )
    registry_source, receipt = _registry_source_descriptor(
        trial.trial_id,
        acquisition,
        actor,
    )
    if registry_source is not None and registry_source.artifact_hash is not None:
        try:
            parse_records, coverage = _parse_source(
                parser,
                store.read(registry_source.artifact_hash),
                registry_source.source_id,
                registry_source.artifact_hash,
                artifact_store=store,
                allow_recovery=False,
            )
        except Exception:
            # A registry acquisition can retain a raw response even when the
            # configured parser cannot produce canonical text.  Preserve the
            # custody record and let the normal initialization diagnostic carry the
            # processing limitation.
            parse_records, coverage = (), ()
        registry_source = registry_source.model_copy(
            update={"parse_records": parse_records, "coverage": coverage}
        )
    inventory = trial.inventory.model_copy(
        update={
            "sources": trial.inventory.sources + ((registry_source,) if registry_source else ())
        }
    )
    updated = trial.model_copy(
        update={
            "inventory": inventory,
            "registry_acquisition": acquisition,
            "registry_candidates": candidates,
        }
    )
    finding_kinds = {
        "fuzzy_registry_candidates": InitializationDiagnosticKind.REGISTRY_CANDIDATES,
        "conflicting_exact_identifiers": (
            InitializationDiagnosticKind.CONFLICTING_REGISTRY_IDENTIFIERS
        ),
        "registry_unavailable": InitializationDiagnosticKind.REGISTRY_UNAVAILABLE,
        "registry_acquisition_failed": InitializationDiagnosticKind.REGISTRY_ACQUISITION_FAILED,
    }
    findings = tuple(
        InitializationDiagnostic(
            kind=finding_kinds[finding.kind.value],
            trial_id=trial.trial_id,
            source_id=(registry_source.source_id if registry_source else None),
            detail=f"ClinicalTrials.gov: {finding.detail}",
        )
        for finding in acquisition.findings
        if finding.kind.value in finding_kinds
    )
    declared_conflicts = tuple(
        dict.fromkeys(
            match.group().upper()
            for source in source_texts
            for match in re.finditer(r"\bNCT\d{8}\b", source.text, re.IGNORECASE)
            if declared_nct is not None and match.group().upper() != declared_nct.upper()
        )
    )
    if declared_conflicts:
        conflict_candidates = tuple(
            RegistryCandidate(
                candidate_id=(
                    f"registry-candidate:{hashlib.sha256(f'{trial.trial_id}|{nct_id}|conflict'.encode()).hexdigest()[:24]}"
                ),
                trial_id=trial.trial_id,
                nct_id=nct_id,
                source="source text",
                locator="source text",
                explicit=False,
                status="fuzzy",
                acquisition_status=acquisition.status,
            )
            for nct_id in declared_conflicts
        )
        updated = updated.model_copy(
            update={
                "registry_candidates": updated.registry_candidates + conflict_candidates,
            }
        )
        findings += (
            InitializationDiagnostic(
                kind=InitializationDiagnosticKind.CONFLICTING_REGISTRY_IDENTIFIERS,
                trial_id=trial.trial_id,
                source_id=(registry_source.source_id if registry_source else None),
                detail=(
                    f"trial.yaml declares {declared_nct}; source text also contains "
                    f"{', '.join(declared_conflicts)}"
                ),
            ),
        )
    return updated, receipt, findings


def _declared_trial_nct(trial_path: Path) -> str | None:
    path = trial_path / "trial.yaml"
    if path.is_symlink():
        raise ValueError(f"trial.yaml symlinks are not permitted: {path}")
    if not path.is_file():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, Mapping):
        raise ValueError("trial.yaml must contain a mapping")
    value = payload.get("nct")
    if value is None:
        value = payload.get("nct_id")
    if value is None:
        return None
    text = str(value).strip()
    if not re.fullmatch(r"NCT\d{8}", text, flags=re.IGNORECASE):
        raise ValueError("trial.yaml nct must be NCT followed by eight digits")
    return text


def _registry_candidates(
    trial_id: Identifier,
    acquisition: RegistryAcquisition,
    *,
    declared_nct_id: str | None = None,
) -> tuple[RegistryCandidate, ...]:
    resolution = acquisition.resolution
    candidates: list[RegistryCandidate] = []
    status = "declared" if resolution.explicit else "discovered"
    if resolution.nct_id:
        digest = hashlib.sha256(
            f"{trial_id}|{resolution.nct_id}|{resolution.locator}|{status}".encode()
        ).hexdigest()[:24]
        candidates.append(
            RegistryCandidate(
                candidate_id=f"registry-candidate:{digest}",
                trial_id=trial_id,
                nct_id=resolution.nct_id,
                declared_nct_id=(declared_nct_id if resolution.explicit else None),
                source=("trial.yaml" if resolution.explicit else "source text"),
                locator=("trial.yaml" if resolution.explicit else resolution.locator),
                explicit=resolution.explicit,
                status=status,
                acquisition_status=acquisition.status,
                raw_record_hash=acquisition.raw_record_hash,
                projection=acquisition.projection,
            )
        )
    for nct_id in resolution.candidate_nct_ids:
        digest = hashlib.sha256(f"{trial_id}|{nct_id}|fuzzy".encode()).hexdigest()[:24]
        candidates.append(
            RegistryCandidate(
                candidate_id=f"registry-candidate:{digest}",
                trial_id=trial_id,
                nct_id=nct_id,
                source="ClinicalTrials.gov candidate search",
                locator=None,
                explicit=False,
                status="fuzzy",
                acquisition_status=acquisition.status,
            )
        )
    if not candidates:
        digest = hashlib.sha256(f"{trial_id}|unavailable".encode()).hexdigest()[:24]
        candidates.append(
            RegistryCandidate(
                candidate_id=f"registry-candidate:{digest}",
                trial_id=trial_id,
                source="ClinicalTrials.gov",
                status="unavailable",
                acquisition_status=acquisition.status,
            )
        )
    return tuple(candidates)


def _registry_source_descriptor(
    trial_id: Identifier,
    acquisition: RegistryAcquisition,
    actor: Actor,
) -> tuple[SourceDescriptor | None, AcquisitionReceipt | None]:
    # A fuzzy or conflicting candidate is not an evidence link.  Keep its
    # engine-issued RegistryCandidate and initialization diagnostic in the proposal, but
    # do not project an unconfirmed identifier as the current registry source.
    if (
        acquisition.status is not RegistryAcquisitionStatus.ACQUIRED
        and not acquisition.resolution.explicit
    ):
        return None, None
    candidate = acquisition.resolution.nct_id or (
        acquisition.resolution.candidate_nct_ids[0]
        if acquisition.resolution.candidate_nct_ids
        else "candidate"
    )
    suffix = re.sub(r"[^A-Za-z0-9_-]+", "-", candidate.lower()).strip("-")
    source_id = f"source:{trial_id.removeprefix('trial:')}-registry-{suffix or 'current'}"
    acquired = acquisition.status is RegistryAcquisitionStatus.ACQUIRED
    availability = {
        RegistryAcquisitionStatus.ACQUIRED: SourceAvailability.ACQUIRED,
        RegistryAcquisitionStatus.REVIEW_REQUIRED: SourceAvailability.DECLARED_OR_DISCOVERED,
        RegistryAcquisitionStatus.UNAVAILABLE: SourceAvailability.UNAVAILABLE,
        RegistryAcquisitionStatus.ACQUISITION_FAILED: SourceAvailability.ACQUISITION_FAILED,
        RegistryAcquisitionStatus.TRIAL_FAILED: SourceAvailability.UNAVAILABLE,
    }[acquisition.status]
    processing = SourceProcessing.USABLE if acquired else SourceProcessing.NOT_ATTEMPTED
    receipt_failure = (
        SourceFailureCategory.CORRUPT_OR_UNREADABLE
        if acquisition.status is RegistryAcquisitionStatus.ACQUISITION_FAILED
        else None
    )
    receipt = AcquisitionReceipt(
        receipt_id=f"receipt:{trial_id.removeprefix('trial:')}-registry-{suffix or 'current'}",
        source_id=source_id,
        method=AcquisitionMethod.REGISTRY_FETCH,
        origin=(
            f"clinicaltrials.gov:{acquisition.resolution.nct_id}"
            if acquisition.resolution.nct_id
            else "clinicaltrials.gov:candidate-search"
        ),
        attempted_at=acquisition.retrieved_at,
        actor=actor.actor_id,
        declared_metadata=(
            ("policy_release", acquisition.policy_release),
            (
                "dataset_timestamp",
                acquisition.dataset_timestamp.isoformat() if acquisition.dataset_timestamp else "",
            ),
        ),
        artifact_hash=acquisition.raw_record_hash,
        outcome=(AcquisitionOutcome.ACQUIRED if acquired else AcquisitionOutcome.FAILED),
        failure_category=receipt_failure,
    )
    source = SourceDescriptor(
        source_id=source_id,
        title=(
            f"ClinicalTrials.gov {acquisition.resolution.nct_id}"
            if acquisition.resolution.nct_id
            else "ClinicalTrials.gov candidate registry record"
        ),
        relative_path=f"registry/clinicaltrials.gov/{suffix or 'candidate'}.json",
        roles=(SourceRole.REGISTRY_CURRENT,),
        criticality=SourceCriticality.EXPECTED,
        classification=ClassificationProvenance(
            authority="clinicaltrials.gov",
            cues=(acquisition.resolution.locator or "registry candidate",),
            classifier_version="clinicaltrials.gov-adapter:1.0.0",
        ),
        availability=availability,
        processing=processing,
        artifact_hash=acquisition.raw_record_hash,
        external_identifiers=(
            (acquisition.resolution.nct_id,)
            if acquisition.resolution.nct_id
            else acquisition.resolution.candidate_nct_ids
        ),
        acquisition_receipt_ids=(receipt.receipt_id,),
    )
    return source, receipt


def _parse_source(
    parser: DocumentParser,
    data: bytes,
    source_id: Identifier,
    artifact_hash: ContentHash,
    *,
    artifact_store: ArtifactStore | None = None,
    allow_recovery: bool,
    relevant_pages: tuple[int, ...] = (),
) -> tuple[tuple[ParseRecord, ...], tuple[PageCoverage, ...]]:
    initial = parser.parse(data, ocr_enabled=False)
    _validate_parse_pages(initial.pages, target_pages=None)
    relevant = frozenset(relevant_pages)
    initial_page_numbers = frozenset(page.page_number for page in initial.pages)
    missing_relevant = sorted(relevant - initial_page_numbers)
    if missing_relevant:
        raise SourceParseError(
            "decision-relevant pages are absent from the OCR-off parse: "
            + ", ".join(str(page) for page in missing_relevant)
        )
    initial_record = _parse_record(
        parser, initial, source_id, artifact_hash, False, None, "initial"
    )
    if artifact_store is not None:
        initial_artifact = artifact_store.put(
            initial.raw_output,
            "application/octet-stream",
        )
        initial_pages_artifact = artifact_store.put(
            _page_artifact_bytes(initial.pages),
            "application/json",
        )
        initial_record = initial_record.model_copy(
            update={
                "output_artifact_hash": initial_artifact.content_hash,
                "page_artifact_hash": initial_pages_artifact.content_hash,
            }
        )
    records = [initial_record]
    recovery_pages = tuple(
        page.page_number
        for page in initial.pages
        if _needs_recovery(
            page,
            relevant_pages=relevant,
            allow_suspect=bool(relevant),
        )
        and (not relevant or page.page_number in relevant)
    )
    if allow_recovery and not relevant and _genuinely_scanned(parser, data, initial.pages):
        recovery_pages = tuple(page.page_number for page in initial.pages)
    recovered: Mapping[int, PageExtraction] = {}
    recovery_record: ParseRecord | None = None
    recovery_error: str | None = None
    if recovery_pages and allow_recovery:
        try:
            recovery = parser.parse(data, ocr_enabled=True, target_pages=recovery_pages)
            _validate_parse_pages(recovery.pages, target_pages=recovery_pages)
            recovered = {page.page_number: page for page in recovery.pages}
            recovery_record = _parse_record(
                parser,
                recovery,
                source_id,
                artifact_hash,
                True,
                recovery_pages,
                "recovery",
            )
            if artifact_store is not None:
                recovery_artifact = artifact_store.put(
                    recovery.raw_output,
                    "application/octet-stream",
                )
                recovery_pages_artifact = artifact_store.put(
                    _page_artifact_bytes(recovery.pages),
                    "application/json",
                )
                recovery_record = recovery_record.model_copy(
                    update={
                        "output_artifact_hash": recovery_artifact.content_hash,
                        "page_artifact_hash": recovery_pages_artifact.content_hash,
                    }
                )
            records.append(recovery_record)
        except SourceParseError as error:
            recovery_error = str(error)
    coverage = tuple(
        _coverage_for(
            page,
            recovered.get(page.page_number),
            page.page_number in recovery_pages and allow_recovery,
            parse_record=initial_record,
            recovery_record=recovery_record,
            artifact_hash=artifact_hash,
            recovery_error=recovery_error,
        )
        for page in initial.pages
    )
    return tuple(records), coverage


def _page_artifact_bytes(pages: tuple[PageExtraction, ...]) -> bytes:
    return json.dumps(
        [page.model_dump(mode="json") for page in pages],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _normalized_parse_output(
    result: ParserResult,
    *,
    source_id: Identifier,
) -> bytes:
    """Bind parser bytes and every canonical metadata field deterministically."""

    payload = {
        "source_id": source_id,
        "raw_output": base64.b64encode(result.raw_output).decode("ascii"),
        "pages": [page.model_dump(mode="json") for page in result.pages],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _pages_from_artifact(data: bytes) -> tuple[PageExtraction, ...]:
    try:
        payload = json.loads(data)
        return tuple(PageExtraction.model_validate(item) for item in payload)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise SourceParseError("stored parser page artifact is invalid") from error


def _parse_index_pages(
    parser: DocumentParser,
    data: bytes,
    parse_records: tuple[ParseRecord, ...],
    artifact_store: ArtifactStore | None = None,
) -> tuple[PageExtraction, ...]:
    """Rehydrate OCR-off pages plus any recorded targeted recovery pages.

    Parse records intentionally retain the requested recovery page set but not
    parser-specific objects.  Evidence indexing therefore replays exactly the
    bounded OCR calls recorded during initialization and merges those pages
    into the canonical page stream; it must never silently drop recovered text
    by indexing only the OCR-off pass.
    """

    initial_record = next(
        (record for record in parse_records if not record.ocr_enabled),
        None,
    )
    if artifact_store is not None and initial_record and initial_record.page_artifact_hash:
        initial_pages = _pages_from_artifact(artifact_store.read(initial_record.page_artifact_hash))
    else:
        initial_pages = parser.parse(data, ocr_enabled=False).pages
    _validate_parse_pages(initial_pages, target_pages=None)
    pages = {
        page.page_number: page.model_copy(update={"parse_id": initial_record.parse_id})
        if initial_record is not None
        else page
        for page in initial_pages
    }
    for record in parse_records:
        if not record.ocr_enabled or not record.target_pages:
            continue
        if artifact_store is not None and record.page_artifact_hash:
            recovered_pages = _pages_from_artifact(artifact_store.read(record.page_artifact_hash))
        else:
            recovered_pages = parser.parse(
                data,
                ocr_enabled=True,
                target_pages=record.target_pages,
            ).pages
        recovered = ParserResult(pages=recovered_pages, raw_output=b"")
        _validate_parse_pages(recovered.pages, target_pages=record.target_pages)
        pages.update(
            {
                page.page_number: page.model_copy(update={"parse_id": record.parse_id})
                for page in recovered.pages
            }
        )
    return tuple(pages[number] for number in sorted(pages))


def _validate_parse_pages(
    pages: tuple[PageExtraction, ...],
    *,
    target_pages: tuple[int, ...] | None,
) -> None:
    """Reject incomplete or duplicate parser output before deriving coverage."""

    numbers = tuple(page.page_number for page in pages)
    if not numbers:
        raise SourceParseError("LiteParse returned no pages")
    if len(numbers) != len(set(numbers)):
        raise SourceParseError("LiteParse returned duplicate page numbers")
    if target_pages is None:
        expected = tuple(range(1, len(numbers) + 1))
        if numbers != expected:
            raise SourceParseError(
                "LiteParse OCR-off output must contain every page in one-based order"
            )
    else:
        expected = tuple(sorted(set(target_pages)))
        if tuple(sorted(numbers)) != expected:
            raise SourceParseError(
                "LiteParse targeted recovery output did not cover every requested page"
            )


def _needs_recovery(
    page: PageExtraction,
    *,
    relevant_pages: frozenset[int],
    allow_suspect: bool,
) -> bool:
    if RECOVERY_REASONS.intersection(page.reasons):
        return not _trustworthy_page_text(page)
    if not allow_suspect:
        return False
    return bool(
        LIMITED_REASONS.intersection(page.reasons)
        or VISUAL_REASONS.intersection(page.reasons)
        or "\ufffd" in page.text
    )


def _trustworthy_page_text(page: PageExtraction) -> bool:
    text = page.text.strip()
    if not text or "\ufffd" in text:
        return False
    if LIMITED_REASONS.intersection(page.reasons):
        return False
    # LiteParse can label a sparse one- or two-word header ``no-text`` even
    # though a tiny canonical fragment is available.  Treat that fragment as
    # suspect; a substantive three-word passage is retained without needless
    # OCR unless another suspect signal is present.
    return len(text.split()) >= 3


def _genuinely_scanned(
    parser: DocumentParser,
    data: bytes,
    pages: tuple[PageExtraction, ...],
) -> bool:
    """Require representative missing-text and visual observations before whole OCR."""

    if not pages:
        return False
    representative_indexes = {0, len(pages) // 2, len(pages) - 1}
    if not all(
        not pages[index].text.strip() and bool(RECOVERY_REASONS.intersection(pages[index].reasons))
        for index in representative_indexes
    ):
        return False
    screenshot = getattr(parser, "screenshot", None)
    if screenshot is None:
        # Lightweight parser doubles may not expose LiteParse's screenshot
        # surface; their representative page observations remain the bounded
        # fallback used by the ingestion tests.
        return True
    requested = tuple(sorted(pages[index].page_number for index in representative_indexes))
    try:
        renders = screenshot(data, page_numbers=requested, dpi=144)
    except (SourceParseError, OSError, ValueError):
        return False
    return tuple(render.page_number for render in renders) == requested and all(
        render.image_bytes for render in renders
    )


def _parse_record(
    parser: DocumentParser,
    result: ParserResult,
    source_id: Identifier,
    artifact_hash: ContentHash,
    ocr_enabled: bool,
    target_pages: tuple[int, ...] | None,
    suffix: str,
) -> ParseRecord:
    configured = getattr(parser, "configuration", {})
    config = {
        **(dict(configured) if isinstance(configured, Mapping) else {}),
        "ocr_enabled": ocr_enabled,
        "include_complexity": True,
        "target_pages": target_pages,
        "quality_policy_release": PARSER_QUALITY_POLICY.policy_release,
        "quality_policy": PARSER_QUALITY_POLICY.model_dump(mode="json"),
        "recovery_policy_release": RECOVERY_POLICY_RELEASE,
    }
    config.setdefault("render_form_fields", False)
    config.setdefault("emit_word_boxes", False)
    config.setdefault("extract_content_bounds", False)
    return ParseRecord(
        parse_id=f"parse:{source_id.removeprefix('source:')}-{suffix}",
        source_id=source_id,
        artifact_hash=artifact_hash,
        parser_name=parser.name,
        parser_version=parser.version,
        configuration_hash=_hash_json(config),
        canonicalization_version=CANONICALIZATION_VERSION,
        output_hash=_hash_bytes(_normalized_parse_output(result, source_id=source_id)),
        ocr_enabled=ocr_enabled,
        target_pages=target_pages,
        quality_observations=tuple(
            sorted({reason for page in result.pages for reason in page.reasons})
        ),
        configuration=tuple(
            (key, json.dumps(value, sort_keys=True, separators=(",", ":")))
            for key, value in sorted(config.items())
        ),
        page_count=len(result.pages),
        page_numbers=tuple(page.page_number for page in result.pages),
    )


def _coverage_for(
    initial: PageExtraction,
    recovered: PageExtraction | None,
    recovery_attempted: bool,
    *,
    parse_record: ParseRecord | None = None,
    recovery_record: ParseRecord | None = None,
    artifact_hash: ContentHash | None = None,
    recovery_error: str | None = None,
) -> PageCoverage:
    before_state = _coverage_state(initial, recovered=None, recovery_attempted=False)
    state = _coverage_state(
        initial,
        recovered=recovered,
        recovery_attempted=recovery_attempted,
    )
    diagnostics = tuple(
        initial.reasons
        + tuple(
            f"unknown-reason:{reason}"
            for reason in initial.reasons
            if reason not in PARSER_QUALITY_POLICY.known_reasons
        )
        + ((f"recovery-error:{recovery_error}",) if recovery_error else ())
    )
    return PageCoverage(
        page_index=initial.page_number - 1,
        state=state,
        diagnostics=diagnostics,
        recovery_attempted=recovery_attempted,
        parse_id=parse_record.parse_id if parse_record else None,
        recovery_parse_id=(
            recovery_record.parse_id
            if recovered is not None and recovery_record is not None
            else None
        ),
        artifact_hash=artifact_hash,
        configuration_hash=(
            recovery_record.configuration_hash
            if recovered is not None and recovery_record is not None
            else (parse_record.configuration_hash if parse_record else None)
        ),
        before_state=before_state,
    )


def _coverage_state(
    initial: PageExtraction,
    *,
    recovered: PageExtraction | None,
    recovery_attempted: bool,
) -> CoverageState:
    reasons = set(initial.reasons)
    if reasons & BLANK_REASONS:
        return CoverageState.INTENTIONALLY_BLANK
    if recovered and recovered.text.strip():
        return CoverageState.TEXT_USABLE
    if recovery_attempted:
        return CoverageState.COVERAGE_LIMITED
    if reasons & RECOVERY_REASONS:
        return CoverageState.RECOVERY_REQUIRED
    if reasons & LIMITED_REASONS or "\ufffd" in initial.text:
        return CoverageState.COVERAGE_LIMITED
    if reasons & VISUAL_REASONS:
        return CoverageState.VISUAL_REQUIRED
    if initial.has_form_fields:
        return CoverageState.COVERAGE_LIMITED
    if initial.text.strip():
        return CoverageState.TEXT_USABLE
    return CoverageState.COVERAGE_LIMITED


def _read_trial_manifest(trial_path: Path) -> dict[str, _DeclaredDocument]:
    path = trial_path / "trial.yaml"
    if path.is_symlink():
        raise ValueError(f"trial.yaml symlinks are not permitted: {path}")
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    declarations: dict[str, _DeclaredDocument] = {}
    for item in payload.get("documents", ()):
        relative = str(item["path"]).replace("\\", "/")
        source_path = trial_path / relative
        if source_path.is_symlink():
            raise ValueError(f"trial.yaml document symlinks are not permitted: {relative}")
        resolved = source_path.resolve()
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
        raw_relevant_pages = item.get("decision_relevant_pages", item.get("relevant_pages", ()))
        if raw_relevant_pages is None:
            raw_relevant_pages = ()
        if not isinstance(raw_relevant_pages, (list, tuple)):
            raise ValueError(
                "trial.yaml decision_relevant_pages must be a list of one-based page numbers"
            )
        if any(type(page) is not int for page in raw_relevant_pages):
            raise ValueError("trial.yaml decision_relevant_pages must contain integer page numbers")
        relevant_pages = tuple(sorted(set(raw_relevant_pages)))
        if any(page < 1 for page in relevant_pages):
            raise ValueError("trial.yaml decision_relevant_pages must be positive")
        declarations[relative] = _DeclaredDocument(
            relative,
            roles,
            components,
            relevant_pages,
        )
    return declarations


def _source_paths(
    trial_path: Path, declarations: Mapping[str, _DeclaredDocument]
) -> tuple[Path, ...]:
    root = trial_path.resolve()
    discovered: set[Path] = set()
    for path in trial_path.rglob("*"):
        if path.is_symlink():
            resolved = path.resolve()
            raise ValueError(f"Trial source symlinks are not permitted: {path} -> {resolved}")
        if not path.is_file() or path.name.lower() == "trial.yaml":
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"Trial source path escapes Trial folder: {path}")
        # Trial folders may contain nested reports and supplements.  Keep the
        # conservative role classifier, but inventory every regular file so
        # nested PDFs cannot disappear from the bounded initialization view.
        discovered.add(resolved)
    discovered.update((trial_path / item.path).resolve() for item in declarations.values())
    return tuple(sorted(discovered, key=lambda path: path.relative_to(root).as_posix()))


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
