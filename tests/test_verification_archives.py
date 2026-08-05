import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from rob2_kit.domain.assessment import (
    AlgorithmicJudgmentRevision,
    AssessmentRevision,
    DecisionTrace,
)
from rob2_kit.domain.releases import PolicyRelease
from rob2_kit.domain.results import Comparison, Estimate, Result, ResultSpecRevision
from rob2_kit.domain.revisions import Dependency, RecordReference
from rob2_kit.domain.sources import SourceInventoryRevision
from rob2_kit.reports.archives import (
    ArchiveBuilder,
    ArchiveVerificationError,
    verify_archive,
)
from rob2_kit.storage.artifacts import ArtifactStore
from rob2_kit.storage.ledger import (
    DependencyInput,
    Transition,
    WorkflowEventOutcome,
    WorkflowLedger,
    dependency_fingerprint,
)
from tests.fixtures import actor

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)
REPOSITORY_ROOT = Path(__file__).parents[1]


def verification_pins() -> dict[str, bytes]:
    return {
        path.relative_to(REPOSITORY_ROOT).as_posix(): path.read_bytes()
        for directory in ("schemas", "packs")
        for path in (REPOSITORY_ROOT / directory).rglob("*")
        if path.is_file()
    }


def archive_ledger(tmp_path: Path) -> WorkflowLedger:
    ledger = WorkflowLedger(
        tmp_path / "workflow.sqlite3", ArtifactStore(tmp_path / "artifacts")
    )
    lease = ledger.acquire_lease("process:archive-test", NOW, timedelta(minutes=5))
    def commit(
        record: object,
        dependencies: tuple[DependencyInput, ...] = (),
        *,
        content: bytes | None = None,
    ) -> str:
        revision_id = getattr(record, "revision_id")
        result = ledger.commit(
            Transition(
                scope="assessment:one",
                operation="operation:freeze-record",
                operation_key=f"idempotency:{revision_id.removeprefix('revision:')}",
                actor=actor(),
                observed_at=NOW,
                entity_id=getattr(record, "entity_id"),
                revision_id=revision_id,
                artifact=content or getattr(record, "model_dump_json")().encode(),
                artifact_media_type=(
                    "application/pdf" if content is not None else "application/json"
                ),
                dependencies=dependencies,
                expected_dependency_fingerprint=dependency_fingerprint(dependencies),
                outcome=WorkflowEventOutcome.COMPLETED,
            ),
            lease,
            now=NOW,
        )
        return result.artifact_hash

    class SourceRecord:
        entity_id = "source-artifact:one"
        revision_id = "revision:source-1"

    source_hash = commit(SourceRecord(), content=b"restricted source bytes")
    source_reference = RecordReference(
        entity_id=SourceRecord.entity_id,
        revision_id=SourceRecord.revision_id,
        content_hash=source_hash,
    )
    result_spec = ResultSpecRevision(
        entity_id="result-spec:one",
        revision_id="revision:result-spec-1",
        actor=actor(),
        observed_at=NOW,
        result=Result(
            result_id="result:one",
            trial_id="trial:one",
            randomization_id="randomization:one",
            comparison=Comparison(
                experimental_arm_id="arm:treatment",
                comparator_arm_id="arm:control",
            ),
            effect_of_interest="assignment",
            outcome_construct="Mortality",
            measurement_instrument="Vital status",
            time_point="30 days",
            analysis_population="Intention to treat",
            analysis_model="Risk ratio",
            effect_measure="RR",
            source_locator="source:one#result",
        ),
        estimate=Estimate(value="0.8"),
        provenance_note="Archive fixture",
    )
    result_hash = commit(result_spec)
    result_reference = RecordReference(
        entity_id=result_spec.entity_id,
        revision_id=result_spec.revision_id,
        content_hash=result_hash,
    )
    inventory_dependencies = (
        Dependency(**result_reference.model_dump(), role="dependency:result-spec"),
        Dependency(**source_reference.model_dump(), role="dependency:source-artifact"),
    )
    inventory = SourceInventoryRevision(
        entity_id="source-inventory:one",
        revision_id="revision:source-inventory-1",
        actor=actor(),
        observed_at=NOW,
        dependencies=inventory_dependencies,
        result_spec=result_reference,
        sources=(),
    )
    inventory_hash = commit(
        inventory,
        tuple(
            DependencyInput.model_validate(item.model_dump())
            for item in inventory_dependencies
        ),
    )
    trace = DecisionTrace(
        entity_id="decision-trace:one",
        revision_id="revision:decision-trace-1",
        actor=actor(),
        observed_at=NOW,
        active_question_ids=("sq:1.1",),
        inactive_question_ids=(),
        matched_rule_ids=("rule:low",),
        resulting_judgment="low",
    )
    trace_hash = commit(trace)
    trace_reference = RecordReference(
        entity_id=trace.entity_id,
        revision_id=trace.revision_id,
        content_hash=trace_hash,
    )
    trace_dependency = Dependency(
        **trace_reference.model_dump(), role="dependency:decision-trace"
    )
    judgment = AlgorithmicJudgmentRevision(
        entity_id="judgment:one",
        revision_id="revision:judgment-1",
        actor=actor(),
        observed_at=NOW,
        dependencies=(trace_dependency,),
        domain_id="domain:1",
        judgment="low",
        answer_revisions=(),
        decision_trace=trace_reference,
    )
    judgment_hash = commit(
        judgment,
        (DependencyInput.model_validate(trace_dependency.model_dump()),),
    )
    policy = PolicyRelease(
        entity_id="policy-release:one",
        revision_id="revision:policy-1",
        actor=actor(),
        observed_at=NOW,
        kind="evidence_search_policy",
        family_id="policy:evidence-search",
        release_id="1.0.0",
        canonical_content_hash="sha256:" + ("b" * 64),
        required_schema_version="1.0.0",
        inventory=(),
    )
    policy_hash = commit(policy)
    inventory_reference = RecordReference(
        entity_id=inventory.entity_id,
        revision_id=inventory.revision_id,
        content_hash=inventory_hash,
    )
    judgment_reference = RecordReference(
        entity_id=judgment.entity_id,
        revision_id=judgment.revision_id,
        content_hash=judgment_hash,
    )
    policy_reference = RecordReference(
        entity_id=policy.entity_id,
        revision_id=policy.revision_id,
        content_hash=policy_hash,
    )
    assessment_dependencies = (
        Dependency(**result_reference.model_dump(), role="dependency:result-spec"),
        Dependency(
            **inventory_reference.model_dump(), role="dependency:source-inventory"
        ),
        Dependency(
            **judgment_reference.model_dump(),
            role="dependency:algorithmic-judgment",
        ),
        Dependency(**policy_reference.model_dump(), role="dependency:policy-release"),
    )
    assessment = AssessmentRevision(
        entity_id="assessment:one",
        revision_id="revision:assessment-1",
        actor=actor(),
        observed_at=NOW,
        dependencies=assessment_dependencies,
        result_spec=result_reference,
        source_inventory=inventory_reference,
        evidence_bundles=(),
        answers=(),
        judgments=(judgment_reference,),
    )
    commit(
        assessment,
        tuple(
            DependencyInput.model_validate(item.model_dump())
            for item in assessment_dependencies
        ),
    )
    return ledger


def test_complete_archive_verifies_without_live_project(tmp_path: Path) -> None:
    ledger = archive_ledger(tmp_path)
    builder = ArchiveBuilder(ledger)
    archive = builder.build(
        "revision:assessment-1",
        pinned_files=verification_pins(),
    )
    repeated = builder.build(
        "revision:assessment-1",
        pinned_files=verification_pins(),
    )

    ledger.path.unlink()
    receipt = verify_archive(archive)

    assert receipt.ok is True
    assert receipt.archive_kind == "complete"
    assert receipt.source_integrity_independently_verifiable is True
    assert receipt.checked_artifacts == 12
    assert archive == repeated


def test_reference_archive_declares_source_integrity_limitation(tmp_path: Path) -> None:
    archive = ArchiveBuilder(archive_ledger(tmp_path)).build(
        "revision:assessment-1",
        kind="reference",
    )

    receipt = verify_archive(archive)
    manifest = json.loads(ZipFile(io.BytesIO(archive)).read("manifest.json"))

    assert receipt.ok is True
    assert receipt.archive_kind == "reference"
    assert receipt.source_integrity_independently_verifiable is False
    assert receipt.message == "source integrity not independently verifiable"
    assert manifest["limitations"] == ["source integrity not independently verifiable"]
    assert "artifacts/revision_source-1" not in ZipFile(io.BytesIO(archive)).namelist()


@pytest.mark.parametrize("mutation", ["corrupt", "missing"])
def test_verifier_rejects_corrupt_or_missing_transitive_artifacts(
    tmp_path: Path, mutation: str
) -> None:
    archive = ArchiveBuilder(archive_ledger(tmp_path)).build(
        "revision:assessment-1",
        pinned_files=verification_pins(),
    )
    source = ZipFile(io.BytesIO(archive))
    target_stream = io.BytesIO()
    with source, ZipFile(target_stream, "w", compression=ZIP_DEFLATED) as target:
        for name in source.namelist():
            if name == "artifacts/revision_policy-1" and mutation == "missing":
                continue
            content = source.read(name)
            if name == "artifacts/revision_policy-1" and mutation == "corrupt":
                content += b"corruption"
            target.writestr(name, content)

    with pytest.raises(ArchiveVerificationError, match="revision:policy-1"):
        verify_archive(target_stream.getvalue())


def test_verifier_rejects_dependency_hash_inconsistent_with_manifest(
    tmp_path: Path,
) -> None:
    archive = ArchiveBuilder(archive_ledger(tmp_path)).build(
        "revision:assessment-1",
        pinned_files=verification_pins(),
    )
    source = ZipFile(io.BytesIO(archive))
    members = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(members["manifest.json"])
    assessment = next(
        item
        for item in manifest["artifacts"]
        if item["revision_id"] == "revision:assessment-1"
    )
    assessment["dependencies"][1]["content_hash"] = "sha256:" + ("f" * 64)
    members["manifest.json"] = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode()

    with pytest.raises(ArchiveVerificationError, match="pinned identity and hash"):
        verify_archive(_zip_members(members))


def test_verifier_validates_pinned_json_schemas(tmp_path: Path) -> None:
    archive = ArchiveBuilder(archive_ledger(tmp_path)).build(
        "revision:assessment-1",
        pinned_files=verification_pins(),
    )
    source = ZipFile(io.BytesIO(archive))
    members = {name: source.read(name) for name in source.namelist()}
    schema_path = "pins/schemas/logic-pack.schema.json"
    members[schema_path] = b'{"type":"not-a-json-schema-type"}'
    manifest = json.loads(members["manifest.json"])
    pin = next(item for item in manifest["pins"] if item["archive_path"] == schema_path)
    pin["content_hash"] = (
        "sha256:" + hashlib.sha256(members[schema_path]).hexdigest()
    )
    members["manifest.json"] = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode()

    with pytest.raises(ArchiveVerificationError, match="valid JSON Schema"):
        verify_archive(_zip_members(members))


def test_verifier_rejects_schema_invalid_canonical_assessment(tmp_path: Path) -> None:
    ledger = archive_ledger(tmp_path)
    valid_assessment = ledger.events()[-1]
    dependencies = valid_assessment.dependencies
    lease = ledger.acquire_lease("process:archive-test", NOW, timedelta(minutes=5))
    ledger.commit(
        Transition(
            scope="assessment:one",
            operation="operation:freeze-record",
            operation_key="idempotency:invalid-assessment",
            actor=actor(),
            observed_at=NOW,
            entity_id="assessment:invalid",
            revision_id="revision:assessment-invalid",
            artifact=b'{"schema_version":"1.0.0","not":"an assessment"}',
            artifact_media_type="application/json",
            dependencies=dependencies,
            expected_dependency_fingerprint=dependency_fingerprint(dependencies),
            outcome=WorkflowEventOutcome.COMPLETED,
        ),
        lease,
        now=NOW,
    )
    archive = ArchiveBuilder(ledger).build(
        "revision:assessment-invalid",
        pinned_files=verification_pins(),
    )

    with pytest.raises(ArchiveVerificationError, match="supported record schema"):
        verify_archive(archive)


def test_verifier_independently_requires_complete_archive_pins(tmp_path: Path) -> None:
    archive = ArchiveBuilder(archive_ledger(tmp_path)).build(
        "revision:assessment-1",
        pinned_files=verification_pins(),
    )
    source = ZipFile(io.BytesIO(archive))
    members = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(members["manifest.json"])
    pin_paths = {pin["archive_path"] for pin in manifest["pins"]}
    manifest["pins"] = []
    members["manifest.json"] = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode()
    for path in pin_paths:
        del members[path]

    with pytest.raises(ArchiveVerificationError, match="no pinned schemas"):
        verify_archive(_zip_members(members))


def _zip_members(members: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return stream.getvalue()
