"""Portable, deterministic Verification archives and offline verification."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Literal
from zipfile import ZipFile

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from yaml import YAMLError

from rob2_kit.domain import assessment, evidence, projects, releases, results, sources
from rob2_kit.domain.canonical import canonical_json_bytes
from rob2_kit.domain.revisions import ContentHash, Identifier, Revision, SchemaVersion
from rob2_kit.evidence.search import CanonicalEvidenceUnit
from rob2_kit.logic.packs import parse_pack_yaml
from rob2_kit.reports._deterministic_zip import write_deterministic_zip
from rob2_kit.storage.artifacts import ArtifactNotFoundError
from rob2_kit.storage.ledger import (
    GENESIS_HASH,
    DependencyInput,
    WorkflowEvent,
    WorkflowLedger,
    workflow_event_hash_payload,
)

ArchiveKind = Literal["complete", "reference"]
_REFERENCE_LIMITATION = "source integrity not independently verifiable"
_SOURCE_ARTIFACT_ROLE = "dependency:source-artifact"
_REVISION_MODELS: tuple[type[Revision], ...] = (
    assessment.SQAnswerRevision,
    assessment.DecisionTrace,
    assessment.AlgorithmicJudgmentRevision,
    assessment.FinalJudgmentRevision,
    assessment.AssessmentRevision,
    evidence.EvidenceCandidate,
    evidence.EvidenceCandidateDispositionRecord,
    evidence.EvidenceReviewRevision,
    evidence.EvidenceClaim,
    evidence.EvidenceCoverageReceiptRecord,
    evidence.DerivedFact,
    evidence.VisualTranscription,
    evidence.EvidenceBundle,
    evidence.EvidenceConsiderationManifest,
    evidence.ContextViewManifest,
    projects.OutcomeTarget,
    projects.ProjectManifestRevision,
    releases.PackRelease,
    releases.PolicyRelease,
    releases.ProjectRule,
    results.ResultSpecRevision,
    sources.SourceComponent,
    sources.SourceInventoryRevision,
)
_RECORD_MODELS: tuple[type[BaseModel], ...] = (
    *_REVISION_MODELS,
    CanonicalEvidenceUnit,
    sources.SourceDescriptor,
)
_ANY_REVISION = _REVISION_MODELS
_EVIDENCE_ITEMS = (
    evidence.EvidenceClaim,
    evidence.DerivedFact,
    evidence.VisualTranscription,
)
_EXPECTED_DEPENDENCY_MODELS: dict[str, tuple[type[BaseModel], ...]] = {
    "dependency:algorithmic-judgment": (assessment.AlgorithmicJudgmentRevision,),
    "dependency:final-judgment": (assessment.FinalJudgmentRevision,),
    "dependency:assessment": (assessment.AssessmentRevision,),
    "dependency:canonical-unit": (CanonicalEvidenceUnit,),
    "dependency:compatible-release": (releases.PackRelease,),
    "dependency:considered-item": _EVIDENCE_ITEMS,
    "dependency:context-item": _RECORD_MODELS,
    "dependency:decision-trace": (assessment.DecisionTrace,),
    "dependency:derived-fact-input": (
        evidence.EvidenceClaim,
        evidence.DerivedFact,
    ),
    "dependency:evidence-bundle": (evidence.EvidenceBundle,),
    "dependency:evidence-review": (evidence.EvidenceReviewRevision,),
    "dependency:evidence-item": _EVIDENCE_ITEMS,
    "dependency:guidance-release": (releases.PackRelease,),
    "dependency:logic-release": (releases.PackRelease,),
    "dependency:outcome-target": (projects.OutcomeTarget,),
    "dependency:policy-release": (releases.PolicyRelease,),
    "dependency:project-rule": (releases.ProjectRule,),
    "dependency:release-item": _RECORD_MODELS,
    "dependency:result-spec": (results.ResultSpecRevision,),
    "dependency:source": (sources.SourceComponent, sources.SourceDescriptor),
    "dependency:source-inventory": (sources.SourceInventoryRevision,),
    "dependency:sq-answer": (assessment.SQAnswerRevision,),
}


class ArchiveVerificationError(RuntimeError):
    """Raised when an archive cannot independently establish its integrity."""


class VerificationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    archive_kind: ArchiveKind
    assessment_revision_id: str
    checked_artifacts: int
    checked_events: int
    source_integrity_independently_verifiable: bool
    message: str


class ArchiveArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    archive_path: str | None
    content_hash: ContentHash
    dependencies: tuple[DependencyInput, ...]
    entity_id: Identifier
    media_type: str = Field(min_length=1)
    omitted: bool
    revision_id: Identifier


class ArchivePin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    archive_path: str = Field(min_length=1)
    content_hash: ContentHash


class ArchiveEvents(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    archive_path: str = Field(min_length=1)
    content_hash: ContentHash


class ArchiveManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    archive_format: Literal["rob2-verification-archive"]
    archive_kind: ArchiveKind
    assessment_revision_id: Identifier
    artifacts: tuple[ArchiveArtifact, ...]
    events: ArchiveEvents
    format_version: SchemaVersion
    limitations: tuple[str, ...]
    pins: tuple[ArchivePin, ...]


class ArchiveBuilder:
    """Materialize the transitive closure of one Assessment revision."""

    def __init__(self, ledger: WorkflowLedger) -> None:
        self.ledger = ledger

    def build(
        self,
        assessment_revision_id: str,
        *,
        kind: ArchiveKind = "complete",
        pinned_files: Mapping[str, bytes] | None = None,
    ) -> bytes:
        self.ledger.preflight()
        events = self.ledger.events()
        closure, source_revisions = _dependency_closure(events, assessment_revision_id)
        selected = tuple(event for event in events if event.revision_id in closure)
        by_revision = {event.revision_id: event for event in selected}
        if assessment_revision_id not in by_revision:
            raise ValueError(f"assessment revision {assessment_revision_id!r} was not found")
        if kind == "complete":
            roles = {dependency.role for event in selected for dependency in event.dependencies}
            if not any("policy" in role for role in roles):
                raise ArchiveVerificationError(
                    "complete archive has no policy revision in its dependency closure"
                )
            pin_names = set(pinned_files or ())
            if not any(name.startswith("schemas/") for name in pin_names):
                raise ArchiveVerificationError("complete archive has no pinned schemas")
            if not any(name.startswith("packs/") for name in pin_names):
                raise ArchiveVerificationError("complete archive has no pinned packs")

        members: dict[str, bytes] = {}
        artifacts: list[dict[str, object]] = []
        for revision_id in sorted(closure):
            event = by_revision.get(revision_id)
            if event is None:
                raise ArchiveVerificationError(
                    f"transitive dependency {revision_id} is absent from the ledger"
                )
            content_hash = event.output_revision_hashes[0]
            omitted = kind == "reference" and revision_id in source_revisions
            archive_path = f"artifacts/{_safe_revision_name(revision_id)}"
            if not omitted:
                try:
                    content = self.ledger.artifacts.read(content_hash)
                except ArtifactNotFoundError as error:
                    raise ArchiveVerificationError(
                        f"artifact for {revision_id} is missing"
                    ) from error
                members[archive_path] = content
            artifacts.append(
                {
                    "archive_path": None if omitted else archive_path,
                    "content_hash": content_hash,
                    "dependencies": [
                        dependency.model_dump(mode="json") for dependency in event.dependencies
                    ],
                    "entity_id": event.entity_id,
                    "media_type": _media_type(None if omitted else members[archive_path]),
                    "omitted": omitted,
                    "revision_id": revision_id,
                }
            )

        pins: list[dict[str, str]] = []
        for path, content in sorted((pinned_files or {}).items()):
            safe_path = _safe_pin_path(path)
            archive_path = f"pins/{safe_path}"
            members[archive_path] = content
            pins.append(
                {
                    "archive_path": archive_path,
                    "content_hash": _sha256(content),
                }
            )

        event_payload = canonical_json_bytes([event.model_dump(mode="json") for event in events])
        members["ledger/events.json"] = event_payload
        manifest = ArchiveManifest(
            archive_format="rob2-verification-archive",
            archive_kind=kind,
            assessment_revision_id=assessment_revision_id,
            artifacts=tuple(ArchiveArtifact.model_validate(item) for item in artifacts),
            events=ArchiveEvents(
                archive_path="ledger/events.json",
                content_hash=_sha256(event_payload),
            ),
            format_version="1.0.0",
            limitations=(_REFERENCE_LIMITATION,) if kind == "reference" else (),
            pins=tuple(ArchivePin.model_validate(item) for item in pins),
        )
        members["manifest.json"] = canonical_json_bytes(manifest)
        return write_deterministic_zip(members)


def verify_archive(archive: bytes | bytearray | memoryview) -> VerificationReceipt:
    """Verify an archive without consulting a project directory or SQLite."""
    try:
        with ZipFile(io.BytesIO(bytes(archive))) as bundle:
            names = set(bundle.namelist())
            if "manifest.json" not in names:
                raise ArchiveVerificationError("manifest.json is missing")
            manifest = _validate_manifest(json.loads(bundle.read("manifest.json")))
            checked_artifacts = 0
            artifacts = {artifact.revision_id: artifact for artifact in manifest.artifacts}
            if len(artifacts) != len(manifest.artifacts):
                raise ArchiveVerificationError("manifest has duplicate artifact revisions")
            for revision_id, artifact in artifacts.items():
                if artifact.omitted:
                    if manifest.archive_kind != "reference":
                        raise ArchiveVerificationError(
                            f"{revision_id} is omitted from a complete archive"
                        )
                    continue
                if artifact.archive_path is None:
                    raise ArchiveVerificationError(f"{revision_id} has no archive path")
                _verify_member(
                    bundle,
                    names,
                    artifact.archive_path,
                    artifact.content_hash,
                    revision_id,
                )
                checked_artifacts += 1
            for artifact in manifest.artifacts:
                for dependency in artifact.dependencies:
                    referenced = artifacts.get(dependency.revision_id)
                    if referenced is None:
                        raise ArchiveVerificationError(
                            f"transitive dependency {dependency.revision_id} is missing"
                        )
                    if (
                        referenced.entity_id != dependency.entity_id
                        or referenced.content_hash != dependency.content_hash
                    ):
                        raise ArchiveVerificationError(
                            f"transitive dependency {dependency.revision_id} "
                            "does not match its pinned identity and hash"
                        )
            pin_content: dict[str, bytes] = {}
            for pin in manifest.pins:
                _verify_member(
                    bundle,
                    names,
                    pin.archive_path,
                    pin.content_hash,
                    pin.archive_path,
                )
                pin_content[pin.archive_path] = bundle.read(pin.archive_path)
                checked_artifacts += 1
            _validate_pinned_schemas_and_packs(pin_content)
            records = _validate_revision_artifacts(bundle, manifest.artifacts)
            _verify_archive_completeness(manifest, artifacts, records)
            events_descriptor = manifest.events
            _verify_member(
                bundle,
                names,
                events_descriptor.archive_path,
                events_descriptor.content_hash,
                "ledger events",
            )
            events = [
                WorkflowEvent.model_validate(item)
                for item in json.loads(bundle.read(events_descriptor.archive_path))
            ]
            _verify_event_order(events)
            _cross_check_events(artifacts, events)
            expected_members = {
                "manifest.json",
                events_descriptor.archive_path,
                *(pin.archive_path for pin in manifest.pins),
                *(
                    artifact.archive_path
                    for artifact in manifest.artifacts
                    if artifact.archive_path is not None
                ),
            }
            if names != expected_members:
                raise ArchiveVerificationError(
                    "archive members do not exactly match the canonical manifest"
                )
    except ArchiveVerificationError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ArchiveVerificationError(f"archive structure is invalid: {error}") from error
    except Exception as error:
        raise ArchiveVerificationError(f"archive cannot be read: {error}") from error

    reference = manifest.archive_kind == "reference"
    return VerificationReceipt(
        ok=True,
        archive_kind=manifest.archive_kind,
        assessment_revision_id=manifest.assessment_revision_id,
        checked_artifacts=checked_artifacts,
        checked_events=len(events),
        source_integrity_independently_verifiable=not reference,
        message=_REFERENCE_LIMITATION if reference else "archive independently verified",
    )


def _dependency_closure(
    events: tuple[WorkflowEvent, ...], root_revision_id: str
) -> tuple[set[str], set[str]]:
    by_revision = {event.revision_id: event for event in events}
    closure: set[str] = set()
    source_revisions: set[str] = set()
    pending = [root_revision_id]
    while pending:
        revision_id = pending.pop()
        if revision_id in closure:
            continue
        closure.add(revision_id)
        event = by_revision.get(revision_id)
        if event is None:
            continue
        for dependency in event.dependencies:
            pending.append(dependency.revision_id)
            if dependency.role == _SOURCE_ARTIFACT_ROLE:
                source_revisions.add(dependency.revision_id)
    return closure, source_revisions


def _validate_manifest(manifest: object) -> ArchiveManifest:
    try:
        value = ArchiveManifest.model_validate(manifest)
    except PydanticValidationError as error:
        raise ArchiveVerificationError(f"manifest schema is invalid: {error}") from error
    if value.format_version != "1.0.0":
        raise ArchiveVerificationError("archive format version is unsupported")
    if value.archive_kind == "reference" and value.limitations != (_REFERENCE_LIMITATION,):
        raise ArchiveVerificationError("reference archive limitation is missing")
    if value.archive_kind == "complete" and value.limitations:
        raise ArchiveVerificationError("complete archive has unexpected limitations")
    return value


def _verify_archive_completeness(
    manifest: ArchiveManifest,
    artifacts: Mapping[str, ArchiveArtifact],
    records: Mapping[str, BaseModel],
) -> None:
    root = artifacts.get(manifest.assessment_revision_id)
    if root is None or not isinstance(
        records.get(manifest.assessment_revision_id), assessment.AssessmentRevision
    ):
        raise ArchiveVerificationError("canonical Assessment revision is missing from the archive")
    reachable: set[str] = set()
    pending = [root.revision_id]
    while pending:
        revision_id = pending.pop()
        if revision_id in reachable:
            continue
        reachable.add(revision_id)
        artifact = artifacts[revision_id]
        for dependency in artifact.dependencies:
            pending.append(dependency.revision_id)
    if reachable != set(artifacts):
        raise ArchiveVerificationError(
            "archive contains artifacts outside the Assessment dependency closure"
        )
    if manifest.archive_kind == "complete":
        if any(artifact.omitted for artifact in artifacts.values()):
            raise ArchiveVerificationError("complete archive omits a transitive artifact")
        pin_paths = {pin.archive_path for pin in manifest.pins}
        if not any(path.startswith("pins/schemas/") for path in pin_paths):
            raise ArchiveVerificationError("complete archive has no pinned schemas")
        if not any(path.startswith("pins/packs/") for path in pin_paths):
            raise ArchiveVerificationError("complete archive has no pinned packs")
        if not any(
            isinstance(records.get(revision_id), releases.PolicyRelease)
            for revision_id in reachable
        ):
            raise ArchiveVerificationError(
                "complete archive has no policy revision in its dependency closure"
            )


def _validate_revision_artifacts(
    bundle: ZipFile,
    artifacts: tuple[ArchiveArtifact, ...],
) -> dict[str, BaseModel]:
    source_revisions = {
        dependency.revision_id
        for artifact in artifacts
        for dependency in artifact.dependencies
        if dependency.role == _SOURCE_ARTIFACT_ROLE
    }
    records: dict[str, BaseModel] = {}
    incoming_roles: dict[str, set[str]] = {}
    for parent in artifacts:
        for dependency in parent.dependencies:
            incoming_roles.setdefault(dependency.revision_id, set()).add(dependency.role)
    for artifact in artifacts:
        if artifact.omitted or artifact.revision_id in source_revisions:
            continue
        if artifact.archive_path is None:
            raise ArchiveVerificationError(f"{artifact.revision_id} has no archived record")
        content = bundle.read(artifact.archive_path)
        matches: list[BaseModel] = []
        for model in _RECORD_MODELS:
            try:
                record = model.model_validate_json(content)
            except PydanticValidationError:
                continue
            if isinstance(record, Revision) and (
                record.entity_id != artifact.entity_id or record.revision_id != artifact.revision_id
            ):
                continue
            matches.append(record)
        if not matches:
            raise ArchiveVerificationError(
                f"{artifact.revision_id} does not match a supported record schema"
            )
        for role in incoming_roles.get(artifact.revision_id, set()):
            expected_models = _EXPECTED_DEPENDENCY_MODELS.get(role)
            if expected_models is None:
                continue
            if not any(isinstance(record, expected_models) for record in matches):
                raise ArchiveVerificationError(
                    f"{artifact.revision_id} does not match the schema required by {role}"
                )
        records[artifact.revision_id] = matches[0]
    return records


def _validate_pinned_schemas_and_packs(pins: Mapping[str, bytes]) -> None:
    schemas: dict[str, Mapping[str, object] | bool] = {}
    for path, content in pins.items():
        if not path.startswith("pins/schemas/") or not path.endswith(".json"):
            continue
        try:
            schema = json.loads(content)
            if not isinstance(schema, (dict, bool)):
                raise ArchiveVerificationError(f"{path} must contain a JSON Schema")
            Draft202012Validator.check_schema(schema)
        except (json.JSONDecodeError, SchemaError) as error:
            raise ArchiveVerificationError(f"{path} is not a valid JSON Schema") from error
        schemas[path] = schema
    for kind in ("logic", "guidance"):
        schema_path = f"pins/schemas/{kind}-pack.schema.json"
        pack_paths = sorted(
            path
            for path in pins
            if path.startswith(f"pins/packs/{kind}/") and path.endswith((".yaml", ".yml", ".json"))
        )
        if pack_paths and schema_path not in schemas:
            raise ArchiveVerificationError(f"{kind} pack schema pin is missing")
        for path in pack_paths:
            try:
                instance = parse_pack_yaml(pins[path])
                Draft202012Validator(schemas[schema_path]).validate(instance)
            except (ValidationError, YAMLError) as error:
                raise ArchiveVerificationError(
                    f"{path} does not conform to {schema_path}"
                ) from error


def _cross_check_events(
    artifacts: Mapping[str, ArchiveArtifact],
    events: list[WorkflowEvent],
) -> None:
    by_revision = {event.revision_id: event for event in events}
    for revision_id, artifact in artifacts.items():
        event = by_revision.get(revision_id)
        if event is None:
            raise ArchiveVerificationError(f"{revision_id} has no corresponding ledger event")
        if (
            event.entity_id != artifact.entity_id
            or event.output_revision_hashes != (artifact.content_hash,)
            or event.dependencies != artifact.dependencies
        ):
            raise ArchiveVerificationError(f"{revision_id} does not match its ledger event")


def _verify_member(
    bundle: ZipFile,
    names: set[str],
    path: str,
    expected_hash: str,
    label: str,
) -> None:
    if path not in names:
        raise ArchiveVerificationError(f"{label} is missing from the archive")
    if _sha256(bundle.read(path)) != expected_hash:
        raise ArchiveVerificationError(f"{label} has a hash mismatch")


def _verify_event_order(events: list[WorkflowEvent]) -> None:
    previous_hash = GENESIS_HASH
    previous_sequence = 0
    for event in events:
        if event.sequence <= previous_sequence:
            raise ArchiveVerificationError("ledger event order is invalid")
        if event.previous_event_hash != previous_hash:
            raise ArchiveVerificationError(f"ledger event {event.event_id} has a broken hash chain")
        event_data = workflow_event_hash_payload(event)
        claimed_hash = event.event_hash
        if _hash_event(event_data) != claimed_hash:
            raise ArchiveVerificationError(f"ledger event {event.event_id} has a hash mismatch")
        previous_sequence = event.sequence
        previous_hash = event.event_hash


def _hash_event(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(payload)


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _safe_revision_name(revision_id: str) -> str:
    return revision_id.replace(":", "_")


def _safe_pin_path(path: str) -> str:
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"unsafe pinned path {path!r}")
    return str(pure)


def _media_type(content: bytes | None) -> str:
    if content is None:
        return "application/octet-stream"
    try:
        json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "application/octet-stream"
    return "application/json"
